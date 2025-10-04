#!/usr/bin/env python3
import time
import subprocess
import logging
import signal
import sys
import RPi.GPIO as GPIO

# Configure logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('router-rebooter.log', mode='a'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# GPIO setup
RELAY_PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)

def cleanup_and_exit(signum=None, frame=None):
    """Clean up GPIO on exit."""
    logger.info("Shutting down router rebooter...")
    GPIO.cleanup()
    sys.exit(0)

# Register signal handlers for clean shutdown
signal.signal(signal.SIGINT, cleanup_and_exit)
signal.signal(signal.SIGTERM, cleanup_and_exit)

def check_internet(host="8.8.8.8"):
    """Check if internet is available by pinging a host."""
    try:
        result = subprocess.run(
            ["ping", "-c1", "-W2", host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Error checking internet: {e}")
        return False

def reboot_router():
    """Power cycle the router via relay."""
    logger.warning("Rebooting router...")
    GPIO.output(RELAY_PIN, GPIO.HIGH)  # Turn router OFF
    time.sleep(5)
    GPIO.output(RELAY_PIN, GPIO.LOW)   # Turn router ON
    logger.info("Router reboot complete.")

def main():
    """Main monitoring loop."""
    internet_was_online = True
    has_rebooted = False

    logger.info("Router rebooter started. Monitoring internet connection...")

    try:
        while True:
            internet_is_online = check_internet()

            if internet_is_online:
                if not internet_was_online:
                    logger.info("Internet connection restored!")
                    has_rebooted = False
                internet_was_online = True
                time.sleep(10)
            else:
                if internet_was_online:
                    logger.warning("Internet connection lost!")
                    internet_was_online = False

                if not has_rebooted:
                    reboot_router()
                    has_rebooted = True
                    time.sleep(60)
                else:
                    logger.info("Internet still down (already rebooted). Checking again in 30 seconds...")
                    time.sleep(30)

    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        cleanup_and_exit()

if __name__ == "__main__":
    main()
