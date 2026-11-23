# MDSS event-based RTP Lambda with failover

AWS Lambda template that forwards S3 events to an MDSS instance and fails over to another
instance when the first one is unavailable. Use it for multi-region active/active
deployments: each region's bucket triggers the Lambda in its own region, which prefers the
local MDSS and falls back to the remote one.

Nothing is synchronised between the MDSS instances. Each target carries its own
`storageClientId` and API key, because both differ per instance.

```
S3 bucket ──event──▶ Lambda ──health check──▶ target 1 (local MDSS)   ── healthy ─▶ POST /api/webhook/realtime
                                  │
                                  └── unhealthy / send failure ──▶ target 2 (remote MDSS) ─▶ POST /api/webhook/realtime
```

## Files

| File | Purpose |
|---|---|
| `lambda_function.py` | Lambda handler, Python 3.9+, standard library only (`boto3` is used only for Secrets Manager) |

## Setup

Follow the standard MDSS guide for the IAM role, the Lambda function and the S3 trigger
("AWS Lambda with S3 Trigger for MDSS Real-Time Processing" in the MDSS docs), then
replace the function code with `lambda_function.py` and set the environment variables below.

On **every** MDSS instance (primary and failover):

1. Add the bucket as a storage unit and note its **storage client ID** (it differs per instance).
2. Create an **API key** (Profile information, Configure API key, Generate, Save).
3. Start an **Event-Based Real-Time Processing** scan on that storage unit.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MDSS_TARGETS` | required | JSON list of targets, in order of preference (first = primary) |
| `HEALTH_PATH` | `/api/health` | Path of the availability check (unauthenticated apigateway endpoint) |
| `HEALTH_TIMEOUT` | `3` | Health check timeout, seconds |
| `HEALTH_CACHE_TTL` | `15` | Seconds a health result is reused by a warm container |
| `SEND_TIMEOUT` | `10` | Webhook request timeout, seconds |
| `LOG_LEVEL` | `INFO` | Python log level |

Target fields:

| Field | Required | Description |
|---|---|---|
| `name` | no | Label used in logs and as the health-cache key, must be unique |
| `base_url` | yes | MDSS base URL without trailing `/`, e.g. `https://mdss-use1.example.com` |
| `storage_client_id` | yes | Storage client ID **on that instance** |
| `api_key` | one of | API key in plain text (prefer the secret ARN) |
| `api_key_secret_arn` | one of | Secrets Manager secret holding the key as a plain string; the execution role needs `secretsmanager:GetSecretValue` on it |
| `scan_id` | no | Only when the instance runs Event-Based scans with a **partition**: the scan ID that must accompany every request (differs per instance) |

Example for the Lambda in us-east-1 (swap the order for the us-east-2 Lambda):

```json
[
  {"name": "use1", "base_url": "https://mdss-use1.example.com",
   "storage_client_id": "0c5454e3-d576-44c5-8ce4-cdc078011d0b",
   "api_key_secret_arn": "arn:aws:secretsmanager:us-east-1:111111111111:secret:mdss-use1-key"},
  {"name": "use2", "base_url": "https://mdss-use2.example.com",
   "storage_client_id": "5d1f7a52-81c3-4d6e-9a42-2b0e6c3f9a10",
   "api_key_secret_arn": "arn:aws:secretsmanager:us-east-1:111111111111:secret:mdss-use2-key"}
]
```

Secrets are read from the region in the secret ARN. To keep the Lambda independent of the other region, replicate both secrets to the Lambda's own region (Secrets Manager multi-region replication) and use the local replica ARNs.

The Lambda must reach all targets over the network (VPC, routing, security groups), and
its timeout must exceed `HEALTH_TIMEOUT` + `SEND_TIMEOUT` per target (60 s is a safe value).

## Behaviour

* **Availability check**: `GET <base_url>/api/health` must return 200. Results are cached per
  warm container for `HEALTH_CACHE_TTL`, and a failed send marks the target down immediately.
* **Order**: targets are tried in order, unhealthy ones are skipped. The primary is used again
  as soon as it passes the check (automatic failback).
* **Failover triggers**: connection error, timeout, or HTTP 5xx on the webhook.
* **No failover on 4xx** (unknown storage, RTP not enabled, not Event-Based, invalid key): this
  is a configuration error and failing over would hide it. The record is reported as failed.
* **Failed records**: the function processes all records, then raises if any failed, so Lambda's
  asynchronous retry (and a dead-letter queue or on-failure destination, if configured) re-delivers
  the event. Configure one for events that must not be lost.

## Extending

* **More availability checks**: add `def check_xxx(target) -> (ok, detail)` to `CHECKS`.
  A target is healthy only if all checks pass (for example latency, version, a deeper probe).
* **Routing policy**: change `order_targets()` for weighted, per-bucket or latency-based order.
* **More targets**: append to `MDSS_TARGETS`, no code change.

## Limitations

* Scan results and history stay on the instance that scanned the file.
* If MDSS accepted a file but answered with a 5xx, the failover instance scans it again
  (a duplicate scan, never a lost event).
* S3 events are regional: a full outage of the bucket's region also stops its Lambda.
* This covers event-based RTP only. For scheduled scans see `active-passive.py`.
