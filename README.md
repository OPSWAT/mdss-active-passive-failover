# Active-Passive Monitoring Script

This script monitors an active instance's health and automatically triggers scans on a passive instance when the active instance becomes unavailable.

## Overview

The script performs the following functions:
- Continuously monitors the active instance's web interface health
- Tracks consecutive failures with a configurable threshold
- Triggers a scan on the passive instance when the failure threshold is reached
- Re-arms the system when the active instance recovers
- Provides detailed logging with timestamps

## Prerequisites

### Python Requirements
- Python 3.7 or higher
- `requests` library

### Installation Steps

1. **Install Python dependencies:**
   ```bash
   pip install requests
   ```

2. **Make the script executable:**
   ```bash
   chmod +x active-passive.py
   ```

## Environment Variables

All configuration is done through environment variables with the `PASSIVE_MODE_` prefix:

| Variable | Description | Default | Required | How to Obtain |
|----------|-------------|---------|----------|---------------|
| `PASSIVE_MODE_ACTIVE_URL` | URL of the active instance (e.g., http://active-instance-hostname) | None | Yes | Same as browser base URL without a trailing / |
| `PASSIVE_MODE_ACTIVE_PORT` | Port of the active instance | None | Yes | 80 by default 443 when using https |
| `PASSIVE_MODE_PASSIVE_URL` | URL of the passive instance | None | Yes | Same as browser base URL without a trailing / |
| `PASSIVE_MODE_PASSIVE_PORT` | Port of the passive instance | None | Yes | 80 by default 443 when using https |
| `PASSIVE_MODE_API_KEY` | API key for authentication | None | Yes | Settings -> Users -> (username) -> Configure API Key |
| `PASSIVE_MODE_STORAGE_ID` | Storage ID for the scan | None | Yes | From browser dashboard URL, e.g. http://hostname/dashboard/**0198eb49-3ed3-753b-a46a-260feee38bd3** |
| `PASSIVE_MODE_WORKFLOW_ID` | Workflow ID for the scan | None | Yes | From browser workflows URL, e.g. http://hostname/workflows/**0198eb49-3ec3-7496-8e3f-42b450b4f1c4** |
| `PASSIVE_MODE_SCAN_NAME` | Name for the triggered scan | None | Yes | Can be set to any text value |
| `PASSIVE_MODE_PRIORITY` | Scan priority | 2 | No | 2 - High, 1 - Medium, 0 - Low |
| `PASSIVE_MODE_CHECK_INTERVAL` | Health check interval in seconds | 60 | No | Set based on desired monitoring frequency |
| `PASSIVE_MODE_TIMEOUT` | Request timeout in seconds | 10 | No | Adjust based on network conditions |
| `PASSIVE_MODE_FAILURE_THRESHOLD` | Number of consecutive failures before triggering passive scan | 3 | No | Set based on desired sensitivity |

## Configuration

### Method 1: Environment File

Create a `.env` file with your configuration:

```bash
# Active instance configuration
export PASSIVE_MODE_ACTIVE_URL="http://active-instance-hostname"
export PASSIVE_MODE_ACTIVE_PORT="80"

# Passive instance configuration
export PASSIVE_MODE_PASSIVE_URL="http://passive-instance-hostname"
export PASSIVE_MODE_PASSIVE_PORT="80"

# API configuration
export PASSIVE_MODE_API_KEY="your-api-key-here"

# Scan configuration
export PASSIVE_MODE_STORAGE_ID="your-storage-id-here"
export PASSIVE_MODE_WORKFLOW_ID="your-workflow-id-here"
export PASSIVE_MODE_SCAN_NAME="passive_failover_scan"
export PASSIVE_MODE_PRIORITY="2"

# Monitoring configuration
export PASSIVE_MODE_CHECK_INTERVAL="60"
export PASSIVE_MODE_TIMEOUT="10"
export PASSIVE_MODE_FAILURE_THRESHOLD="3"
```

### Method 2: Direct Export

Export variables directly in your shell:

```bash
export PASSIVE_MODE_ACTIVE_URL="http://passive-instance-hostname"
export PASSIVE_MODE_ACTIVE_PORT="80"
# ... (repeat for all variables)
```

## Usage

### Running the Script

1. **Load environment variables:**
   ```bash
   source .env
   ```

2. **Run the script:**
   ```bash
   python3 active-passive.py
   ```

3. **Run in background:**
   ```bash
   nohup python3 active-passive.py > active-passive.log 2>&1 &
   ```

### Example Execution

```bash
# Set up environment
export PASSIVE_MODE_ACTIVE_URL="https://active-instance-hostname"
export PASSIVE_MODE_ACTIVE_PORT="443"
export PASSIVE_MODE_PASSIVE_URL="https://passive-instance-hostname"
export PASSIVE_MODE_PASSIVE_PORT="443"
export PASSIVE_MODE_API_KEY="your-api-key-here"
export PASSIVE_MODE_STORAGE_ID="your-storage-id-here"
export PASSIVE_MODE_WORKFLOW_ID="your-workflow-id-here"
export PASSIVE_MODE_SCAN_NAME="emergency_scan"

# Run the script
python3 active-passive.py
```

## Monitoring and Logs

The script provides detailed logging including:
- Startup configuration information
- Health check results with response codes
- Failure count tracking
- Passive scan trigger events
- Recovery notifications

### Sample Log Output

```
2024-01-15 10:30:00 - __main__ - INFO - Monitoring active instance: http://active-instance-hostname:80
2024-01-15 10:30:00 - __main__ - INFO - Passive instance: http://passive-instance-hostname:80
2024-01-15 10:30:00 - __main__ - INFO - Check interval: 60 seconds
2024-01-15 10:30:00 - __main__ - INFO - Failure threshold: 3 consecutive failures
2024-01-15 10:30:00 - __main__ - INFO - Starting active-passive monitoring...
2024-01-15 10:30:01 - __main__ - INFO - Health check response: 200 - {"version":"1.0.0"}
2024-01-15 10:31:01 - __main__ - WARNING - Active instance check failed (1/3)
2024-01-15 10:32:01 - __main__ - WARNING - Active instance check failed (2/3)
2024-01-15 10:33:01 - __main__ - WARNING - Active instance check failed (3/3)
2024-01-15 10:33:01 - __main__ - WARNING - Failure threshold reached (3), triggering scan on passive instance...
2024-01-15 10:33:02 - __main__ - INFO - Successfully triggered scan on passive instance: 200
2024-01-15 10:33:02 - __main__ - INFO - Passive scan triggered successfully
```

## Troubleshooting

### Common Issues

1. **Missing environment variables:**
   - Error: `Missing required environment variables: PASSIVE_MODE_API_KEY`
   - Solution: Ensure all required environment variables are set

2. **Connection timeouts:**
   - Error: `Active instance health check failed: HTTPSConnectionPool timeout`
   - Solution: Check network connectivity or increase `PASSIVE_MODE_TIMEOUT`

3. **SSL certificate warnings:**
   - The script automatically suppresses SSL warnings for self-signed certificates
   - Ensure `verify=False` is appropriate for your security requirements

4. **API authentication failures:**
   - Error: `Failed to trigger scan on passive instance: 401`
   - Solution: Verify the API key is correct and has proper permissions

### Running as a Service

To run the script as a systemd service, create `/etc/systemd/system/active-passive-monitor.service`:

```ini
[Unit]
Description=Active-Passive Monitor
After=network.target

[Service]
Type=simple
User=monitor
WorkingDirectory=/path/to/script
EnvironmentFile=/path/to/script/.env
ExecStart=/usr/bin/python3 active-passive.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable active-passive-monitor
sudo systemctl start active-passive-monitor
```

## Security Considerations

- Store API keys securely and avoid committing them to version control
- Use appropriate file permissions for configuration files (600 or 640)
- Consider using HTTPS for all communications
- Regularly rotate API keys
- Monitor logs for unauthorized access attempts
