#!/usr/bin/env python3
import time
import subprocess
import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BCM)
relay_pin = 17
GPIO.setup(relay_pin, GPIO.OUT, initial=GPIO.LOW)

def internet_ok(host="8.8.8.8"):
    try:
        result = subprocess.run(["ping", "-c1", "-W2", host],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        return (result.returncode == 0)
    except Exception:
        return False

# State tracking variables
internet_was_online = True  # Assume internet starts online
has_rebooted_for_current_outage = False

print("Router rebooter started. Monitoring internet connection...")

while True:
    internet_is_online = internet_ok()

    if internet_is_online:
        if not internet_was_online:
            # Internet just came back online
            print("Internet connection restored!")
            has_rebooted_for_current_outage = False  # Reset for next outage
        internet_was_online = True
        time.sleep(10)  # Check again in 10 seconds
    else:
        if internet_was_online:
            # Internet just went offline
            print("Internet connection lost!")

        if not has_rebooted_for_current_outage:
            # First time detecting this outage - reboot the router
            print("Rebooting router...")
            GPIO.output(relay_pin, GPIO.HIGH)  # energize coil -> router power OFF
            time.sleep(5)                       # wait a few seconds
            GPIO.output(relay_pin, GPIO.LOW)   # de-energize coil -> router power ON
            has_rebooted_for_current_outage = True
            print("Router reboot complete. Waiting 60 seconds before next check...")
            time.sleep(60)  # wait 60s before next check
        else:
            # Already rebooted for this outage, just wait
            print("Internet still down (already rebooted for this outage). Checking again in 30 seconds...")
            time.sleep(30)  # Check more frequently but don't reboot

        internet_was_online = False
