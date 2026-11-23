"""
MDSS event-based RTP forwarder with endpoint availability check and failover.

S3 event -> Lambda -> first healthy MDSS target (ordered list) -> /api/webhook/realtime

Configuration (Lambda environment variables)
  MDSS_TARGETS      JSON list, ordered by preference (first = primary); names must be unique:
                    [{"name": "use1", "base_url": "https://mdss-use1.example.com",
                      "storage_client_id": "<id on that instance>",
                      "api_key": "<key>"                      # or:
                      "api_key_secret_arn": "arn:aws:secretsmanager:..."  # plain-string secret
                      "scan_id": "<optional, only for partition scans>"},
                     {"name": "use2", ...}]
  HEALTH_PATH       default /api/health        (unauthenticated apigateway endpoint)
  HEALTH_TIMEOUT    seconds, default 3
  HEALTH_CACHE_TTL  seconds a health result is reused by a warm container, default 15
  SEND_TIMEOUT      seconds, default 10
  LOG_LEVEL         default INFO

Failover rules
  * Targets are tried in order, unhealthy ones are skipped; the primary is used again as
    soon as it passes the check (no manual failback).
  * Connection error / timeout / HTTP 5xx on send  -> try the next target.
  * HTTP 4xx on send (wrong storage id, RTP not enabled, bad key) -> NOT failed over, it is
    a configuration error; the record is reported as failed so it is visible.
  * If any record fails, the function raises after processing all records, so Lambda's
    async retry (and a DLQ/destination, if configured) re-delivers the event.

Extending
  * Extra availability checks: write `def check_xxx(target) -> (ok, detail)` and add it to
    CHECKS. A target is healthy only if every check passes.
  * Extra failover logic: change `order_targets` (e.g. weighted, latency based, per-bucket).
  * Extra targets: append to MDSS_TARGETS, no code change.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request
from urllib.parse import unquote_plus

log = logging.getLogger()
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))

HEALTH_PATH = os.getenv("HEALTH_PATH", "/api/health")
HEALTH_TIMEOUT = float(os.getenv("HEALTH_TIMEOUT", "3"))
HEALTH_CACHE_TTL = float(os.getenv("HEALTH_CACHE_TTL", "15"))
SEND_TIMEOUT = float(os.getenv("SEND_TIMEOUT", "10"))
WEBHOOK_PATH = "/api/webhook/realtime"

_health_cache = {}   # target name -> (expires_at, ok, detail)
_secret_cache = {}   # secret arn -> value


class ConfigError(Exception):
    pass


class SendError(Exception):
    """Send failed in a way that justifies trying another target."""


class ClientError(Exception):
    """4xx from MDSS: configuration problem, do not fail over."""


# ----------------------------------------------------------------- configuration
def load_targets():
    raw = os.getenv("MDSS_TARGETS", "")
    try:
        targets = json.loads(raw)
    except ValueError as e:
        raise ConfigError(f"MDSS_TARGETS is not valid JSON: {e}")
    if not isinstance(targets, list) or not targets:
        raise ConfigError("MDSS_TARGETS must be a non-empty JSON list")
    for i, t in enumerate(targets):
        t.setdefault("name", f"target{i}")
        for k in ("base_url", "storage_client_id"):
            if not t.get(k):
                raise ConfigError(f"target {t['name']}: missing {k}")
        if not (t.get("api_key") or t.get("api_key_secret_arn")):
            raise ConfigError(f"target {t['name']}: need api_key or api_key_secret_arn")
        t["base_url"] = t["base_url"].rstrip("/")
    names = [t["name"] for t in targets]
    if len(set(names)) != len(names):  # name is the health-cache key
        raise ConfigError(f"target names must be unique: {names}")
    return targets


def api_key(target):
    if target.get("api_key"):
        return target["api_key"]
    arn = target["api_key_secret_arn"]
    if arn not in _secret_cache:
        import boto3  # bundled in the Lambda Python runtime
        # The endpoint region is not taken from SecretId: use the ARN's own region.
        region = arn.split(":")[3] if arn.count(":") >= 5 else None
        _secret_cache[arn] = boto3.client("secretsmanager", region_name=region).get_secret_value(
            SecretId=arn)["SecretString"].strip()
    return _secret_cache[arn]


# ----------------------------------------------------------------- availability checks
def check_http_health(target):
    """GET <base_url>/api/health must answer 200 within HEALTH_TIMEOUT."""
    try:
        with urllib.request.urlopen(target["base_url"] + HEALTH_PATH,
                                    timeout=HEALTH_TIMEOUT) as r:
            return r.status == 200, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:  # DNS, refused, timeout, TLS ...
        return False, f"{type(e).__name__}: {e}"


# Add more checks here, each takes the target dict and returns (ok, detail).
CHECKS = [check_http_health]


def is_healthy(target):
    now = time.monotonic()
    hit = _health_cache.get(target["name"])
    if hit and hit[0] > now:
        return hit[1]
    ok, detail = True, "ok"
    for check in CHECKS:
        ok, detail = check(target)
        if not ok:
            detail = f"{check.__name__}: {detail}"
            break
    _health_cache[target["name"]] = (now + HEALTH_CACHE_TTL, ok)
    if not ok:
        log.warning("target %s unhealthy (%s)", target["name"], detail)
    return ok


def mark_down(target):
    """A send failure overrides the cached health so the next record skips this target."""
    _health_cache[target["name"]] = (time.monotonic() + HEALTH_CACHE_TTL, False)


def order_targets(targets):
    """Preference order, healthy only. Replace for weighted / per-bucket routing."""
    return [t for t in targets if is_healthy(t)]


# ----------------------------------------------------------------- sending
def send(target, record):
    payload = {"metadata": json.dumps(record),
               "storageClientId": target["storage_client_id"]}
    if target.get("scan_id"):
        payload["scanId"] = target["scan_id"]
    req = urllib.request.Request(
        target["base_url"] + WEBHOOK_PATH,
        data=json.dumps(payload).encode("utf-8"),
        headers={"ApiKey": api_key(target), "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=SEND_TIMEOUT) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:  # the body is only diagnostic; the status code decides failover
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        finally:
            e.close()
        if 400 <= e.code < 500:
            raise ClientError(f"HTTP {e.code} {body}")
        raise SendError(f"HTTP {e.code} {body}")
    except Exception as e:
        raise SendError(f"{type(e).__name__}: {e}")


def forward(record, targets):
    candidates = order_targets(targets)
    if not candidates:
        raise SendError("no healthy MDSS target")
    last = None
    for t in candidates:
        try:
            resp = send(t, record)
            log.info("key=%s sent to %s%s %s", record["s3"]["object"]["key"], t["name"],
                     "" if t is targets[0] else " (FAILOVER)", resp)
            return t["name"]
        except SendError as e:
            log.error("send to %s failed: %s", t["name"], e)
            mark_down(t)
            last = e
    raise SendError(f"all targets failed, last error: {last}")


# ----------------------------------------------------------------- entry point
def lambda_handler(event, context):
    targets = load_targets()
    failed = []
    for record in event.get("Records", []):
        record["s3"]["object"]["key"] = unquote_plus(record["s3"]["object"]["key"])
        try:
            forward(record, targets)
        except (SendError, ClientError) as e:
            log.error("record failed: %s", e)
            failed.append(str(e))
    if failed:
        raise RuntimeError(f"{len(failed)} record(s) failed: {failed[0]}")
    return {"processed": len(event.get("Records", []))}
