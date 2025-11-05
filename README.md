# Router Rebooter

Automatic internet connection monitor for Raspberry Pi that power-cycles a router via relay when the connection is lost.

## Features

- **Automatic Internet Monitoring**: Pings a configurable host to check connectivity
- **Smart Retry Logic**: 5 retries with 1-second delays to avoid false positives from packet loss
- **Packet Loss Reporting**: Logs packet loss statistics for diagnostics
- **Automatic Router Reboot**: Power-cycles router via GPIO-controlled relay when internet is down
- **State Management**: Only reboots once per outage (won't repeatedly reboot while offline)
- **Web Interface**: View logs and manually trigger reboots from your browser
- **Configuration File**: Easy-to-edit INI-style config file for all settings
- **Comprehensive Logging**: Timestamped logs to both console and file

## Hardware Requirements

- Raspberry Pi (any model with GPIO)
- 5V Relay Module (active-high)
- Jumper wires

## Wiring

```
Raspberry Pi          Relay Module
-----------          ------------
GPIO Pin 17    -->   IN/Signal
5V             -->   VCC
GND            -->   GND

Relay Module          Router Power
------------          ------------
COM            -->    Power source hot wire
NO             -->    Router power input
```

## Installation

1. Clone or download this repository to your Raspberry Pi
2. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install RPi.GPIO
   ```

## Configuration

### Creating a Configuration File

Create a default configuration file:
```bash
python3 router-rebooter.py --create-config router-rebooter.conf
```

This will create a configuration file with default values. Edit it to customize your settings.

### Configuration File Format

```ini
[Network]
# Comma-separated list of hosts to ping for internet connectivity check
# Multiple hosts provide redundancy if one target goes down
# Each ping attempt randomly selects a host from this list
ping_hosts = 8.8.8.8, 1.1.1.1, 208.67.222.222, 9.9.9.9

# Number of ping retries before declaring internet is offline
ping_retries = 5

# Seconds to wait for each ping response
ping_timeout = 2

# Ping packet data size in bytes (0-65507)
# 0 bytes (default) sends minimal packet for reachability check only
# 56 bytes tests data integrity through the network
ping_packet_size = 0

# Seconds to wait between checks when internet is online
check_interval_online = 10

# Seconds to wait between checks when internet is offline (after reboot)
check_interval_offline = 30

[GPIO]
# GPIO pin number (BCM mode) connected to the relay
relay_pin = 17

[HTTP]
# Port for the web interface
port = 8080

# HTTP Basic Authentication (optional)
# Leave both empty to disable authentication
auth_username =
auth_password =

# SSL/HTTPS (optional)
# Set to true to enable HTTPS with self-signed certificate
ssl_enabled = false
ssl_cert = cert.pem
ssl_key = key.pem

[Logging]
# Path to the log file (relative or absolute)
log_file = router-rebooter.log

# Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
log_level = INFO
```

### Using a Custom Config File

```bash
python3 router-rebooter.py --config /path/to/custom.conf
```

### Configuring Ping Behavior

You can customize how the script checks internet connectivity:

**Ping Hosts (`ping_hosts`):**
- Comma-separated list of hosts to ping for connectivity checks
- Default: `8.8.8.8, 1.1.1.1, 208.67.222.222, 9.9.9.9`
  - 8.8.8.8 - Google Public DNS
  - 1.1.1.1 - Cloudflare DNS
  - 208.67.222.222 - OpenDNS
  - 9.9.9.9 - Quad9 DNS
- Each ping attempt uses a randomly selected host from the list
- With 5 retries (default), up to 5 different hosts may be tested per check
- Multiple hosts provide redundancy if one target goes down temporarily
- Prevents false positives from single target failures

**Ping Timeout (`ping_timeout`):**
- How long to wait for each ping response (in seconds)
- Default: `2` seconds
- Lower values = faster detection but may cause false positives on slow connections
- Higher values = more tolerant of latency but slower to detect outages

**Ping Packet Size (`ping_packet_size`):**
- Size of data payload in ping packets (in bytes)
- Default: `0` bytes (minimal packet for reachability check)
- Range: `0` to `65507` bytes

**Choosing packet size:**
- **0 bytes (default)**: Minimal ICMP header only
  - Smallest possible packet
  - Only verifies host reachability (sufficient for router rebooter)
  - Fastest and lowest bandwidth usage

- **56 bytes**: Standard ping, tests data integrity through the network
  - Verifies that data can traverse the network without corruption
  - More robust connectivity check
  - Use if you want to detect network degradation, not just complete outages

### Enabling HTTPS/SSL (Optional)

To enable HTTPS with a self-signed certificate, edit your config file:

```ini
[HTTP]
port = 8080
ssl_enabled = true
ssl_cert = cert.pem
ssl_key = key.pem
```

**How it works:**
- When `ssl_enabled = true`, the script will automatically generate a self-signed certificate on first run
- Requires `openssl` command to be installed: `sudo apt-get install openssl`
- Certificate is valid for 365 days
- Browser will show a security warning (expected for self-signed certificates)
- Click "Advanced" → "Proceed" to access the interface

**Note:** Self-signed certificates provide encryption but not identity verification. For production use, consider a proper SSL certificate from Let's Encrypt or a reverse proxy.

### Enabling HTTP Authentication (Optional)

To protect the web interface with a username and password, edit your config file:

```ini
[HTTP]
port = 8080
auth_username = admin
auth_password = your_secure_password
```

**Security Notes:**
- If either `auth_username` or `auth_password` is empty, authentication is disabled
- The password is stored in plain text in the config file
- Use a strong, unique password
- Use HTTPS (ssl_enabled = true) to encrypt credentials in transit
- Restrict file permissions: `chmod 600 router-rebooter.conf`

## Usage

### First Time Setup

1. Create a configuration file:
   ```bash
   python3 router-rebooter.py --create-config router-rebooter.conf
   ```

2. Edit the configuration file to customize settings:
   ```bash
   nano router-rebooter.conf
   ```

### Run Manually

```bash
python3 router-rebooter.py --config router-rebooter.conf
```

Or if using the default config file location:
```bash
python3 router-rebooter.py
```

### Access Web Interface

Open a browser and navigate to:
```
http://<raspberry-pi-ip>:8080
```

To find your Raspberry Pi's IP address:
```bash
hostname -I
```

### Run as a Service (Recommended)

1. Create a systemd service file:
   ```bash
   sudo nano /etc/systemd/system/router-rebooter.service
   ```

2. Add the following content (adjust paths as needed):
   ```ini
   [Unit]
   Description=Router Rebooter Service
   After=network.target
   
   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/router-rebooter
   ExecStart=/home/pi/router-rebooter/venv/bin/python3 /home/pi/router-rebooter/router-rebooter.py --config /home/pi/router-rebooter/router-rebooter.conf
   Restart=always
   RestartSec=10
   
   [Install]
   WantedBy=multi-user.target
   ```

3. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable router-rebooter.service
   sudo systemctl start router-rebooter.service
   ```

4. Check service status:
   ```bash
   sudo systemctl status router-rebooter.service
   ```

5. View logs:
   ```bash
   sudo journalctl -u router-rebooter.service -f
   ```

## Web Interface Features

- **Real-time Log Viewing**: See all events with color-coded log levels
- **Manual Refresh**: Update logs on demand
- **Scroll to Bottom**: Jump to latest entries
- **View Raw Logs**: Open plain text log file in new tab
- **Manual Reboot**: Trigger router reboot from the web interface
- **Clear Log**: Clear the log file (with confirmation)

## How It Works

1. **Internet Check**: Pings configured host (default: 8.8.8.8) with retry logic
2. **Packet Loss Handling**: Retries up to 5 times with 1-second delays
3. **State Tracking**: Monitors internet state transitions (online ↔ offline)
4. **Smart Rebooting**: Only reboots when internet transitions from online to offline
5. **Power Cycle**: Turns relay ON (router OFF) for 5 seconds, then relay OFF (router ON)
6. **Recovery Wait**: Waits for router to boot and connection to restore
7. **Continuous Monitoring**: Checks every 10 seconds when online, 30 seconds when offline

## Troubleshooting

### GPIO Permissions

If you get permission errors, add your user to the `gpio` group:
```bash
sudo usermod -a -G gpio $USER
```

Then log out and log back in.

### Relay Not Switching

- Check wiring connections
- Verify GPIO pin number in config file matches your wiring
- Test relay manually with a simple GPIO script
- Some relays are active-low instead of active-high (swap HIGH/LOW in code)

### False Positives

If the router reboots too often due to temporary packet loss:
- Increase `ping_retries` in config file (e.g., 7 or 10)
- Increase `check_interval_online` to reduce check frequency

### Web Interface Not Accessible

- Check firewall settings
- Verify the port in config file is not blocked
- Ensure the script is running: `sudo systemctl status router-rebooter.service`

### HTTP Server Errors

If you see "Failed to start HTTP server on port X":
- **Permission denied (Errno 13)**: Ports below 1024 require root/sudo
  - Use a port >= 1024 in config file (recommended: 8080)
  - Or run with sudo: `sudo python3 router-rebooter.py`
- **Address already in use (Errno 98)**: Another service is using that port
  - Change the port in config file
  - Or stop the other service using that port
