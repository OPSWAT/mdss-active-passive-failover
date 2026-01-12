#!/usr/bin/env python3

import os
import sys
import time
import json
import logging
import requests
from typing import Optional
import urllib3

# Disable SSL warnings for unverified HTTPS requests
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class ActivePassiveMonitor:
    def __init__(self):
        """Initialize the monitor with environment variables."""
        self.active_url = os.getenv('PASSIVE_MODE_ACTIVE_URL')
        self.active_port = os.getenv('PASSIVE_MODE_ACTIVE_PORT')
        self.passive_url = os.getenv('PASSIVE_MODE_PASSIVE_URL')
        self.passive_port = os.getenv('PASSIVE_MODE_PASSIVE_PORT')
        self.api_key = os.getenv('PASSIVE_MODE_API_KEY')
        self.storage_id = os.getenv('PASSIVE_MODE_STORAGE_ID')
        self.workflow_id = os.getenv('PASSIVE_MODE_WORKFLOW_ID')
        self.scan_name = os.getenv('PASSIVE_MODE_SCAN_NAME')
        self.priority = int(os.getenv('PASSIVE_MODE_PRIORITY', '2'))
        self.check_interval = int(os.getenv('PASSIVE_MODE_CHECK_INTERVAL', '60'))
        self.timeout = int(os.getenv('PASSIVE_MODE_TIMEOUT', '10'))
        self.failure_threshold = int(os.getenv('PASSIVE_MODE_FAILURE_THRESHOLD', '3'))
        
        # State tracking
        self.consecutive_failures = 0
        self.passive_scan_triggered = False
        
        # Validate required environment variables
        required_vars = [
            'PASSIVE_MODE_ACTIVE_URL', 'PASSIVE_MODE_ACTIVE_PORT',
            'PASSIVE_MODE_PASSIVE_URL', 'PASSIVE_MODE_PASSIVE_PORT',
            'PASSIVE_MODE_API_KEY', 'PASSIVE_MODE_STORAGE_ID',
            'PASSIVE_MODE_WORKFLOW_ID', 'PASSIVE_MODE_SCAN_NAME'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            sys.exit(1)
        
        self.active_instance_url = f"{self.active_url}:{self.active_port}"
        self.passive_instance_url = f"{self.passive_url}:{self.passive_port}"
        
        logger.info(f"Monitoring active instance: {self.active_instance_url}")
        logger.info(f"Passive instance: {self.passive_instance_url}")
        logger.info(f"Check interval: {self.check_interval} seconds")
        logger.info(f"Failure threshold: {self.failure_threshold} consecutive failures")

    def check_active_instance_health(self) -> bool:
        """Check if the active instance web interface is working."""
        try:
            health_url = f"{self.active_instance_url}/api/version"
            response = requests.get(
                health_url,
                timeout=self.timeout,
                verify=False
            )
            
            logger.info(f"Health check response: {response.status_code} - {response.text[:200]}")
            
            if response.status_code == 200:
                logger.debug(f"Active instance health check passed: {response.status_code}")
                return True
            else:
                logger.warning(f"Active instance health check failed: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Active instance health check failed: {e}")
            return False

    def trigger_passive_scan(self) -> bool:
        """Trigger a scan on the passive instance."""
        try:
            scan_url = f"{self.passive_instance_url}/api/scan/start"
            
            payload = {
                "name": self.scan_name,
                "workflowId": self.workflow_id,
                "storageIds": [self.storage_id],
                "priority": self.priority,
                "scanConfigDto": {
                    "realTimeScanConfig": {
                        "isEnabled": True,
                        "handlingType": 0
                    }
                }
            }
            
            headers = {
                'ApiKey': self.api_key,
                'Connection': 'keep-alive',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                scan_url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
                verify=False
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully triggered scan on passive instance: {response.status_code}")
                return True
            else:
                logger.error(f"Failed to trigger scan on passive instance: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to trigger scan on passive instance: {e}")
            return False

    def run(self):
        """Main monitoring loop."""
        logger.info("Starting active-passive monitoring...")
        
        while True:
            try:
                if self.check_active_instance_health():
                    # Active instance is healthy
                    if self.consecutive_failures > 0:
                        logger.info(f"Active instance recovered after {self.consecutive_failures} failed checks")
                    
                    # Reset counters and re-arm the system
                    self.consecutive_failures = 0
                    if self.passive_scan_triggered:
                        logger.info("Re-arming passive scan trigger - active instance is healthy")
                        self.passive_scan_triggered = False
                    
                    logger.debug("Active instance is healthy")
                else:
                    # Active instance failed
                    self.consecutive_failures += 1
                    logger.warning(f"Active instance check failed ({self.consecutive_failures}/{self.failure_threshold})")
                    
                    # Trigger passive scan only once when threshold is reached
                    if self.consecutive_failures >= self.failure_threshold and not self.passive_scan_triggered:
                        logger.warning(f"Failure threshold reached ({self.failure_threshold}), triggering scan on passive instance...")
                        if self.trigger_passive_scan():
                            logger.info("Passive scan triggered successfully")
                            self.passive_scan_triggered = True
                        else:
                            logger.error("Failed to trigger passive scan")
                
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in monitoring loop: {e}")
                time.sleep(self.check_interval)

def main():
    """Main function."""
    monitor = ActivePassiveMonitor()
    monitor.run()

if __name__ == "__main__":
    main()
