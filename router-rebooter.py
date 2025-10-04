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

while True:
    if not internet_ok():
        # Internet down: power-cycle router
        GPIO.output(relay_pin, GPIO.HIGH)  # energize coil -> router power OFF:contentReference[oaicite:14]{index=14}
        time.sleep(5)                       # wait a few seconds
        GPIO.output(relay_pin, GPIO.LOW)   # de-energize coil -> router power ON
        time.sleep(60)                     # wait 60s before next check
    else:
        time.sleep(10)                     # ping again in 10s
