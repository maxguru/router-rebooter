#!/usr/bin/env python3
"""
Router Rebooter - Automatic Internet Connection Monitor and Router Power Cycler

DESCRIPTION:
    This script monitors internet connectivity by pinging a remote host (default: 8.8.8.8).
    When the internet connection is lost, it automatically power-cycles the router using
    a relay connected to a Raspberry Pi GPIO pin. The script includes intelligent state
    tracking to ensure it only reboots once per outage (won't repeatedly reboot if the
    internet doesn't come back immediately).

    Features:
    - Monitors internet connectivity continuously
    - Automatically reboots router when connection is lost
    - Only reboots once per outage (waits for connection to restore before rebooting again)
    - Logs all events to both console and a log file with timestamps
    - Built-in HTTP server for viewing logs via web browser
    - Graceful shutdown with proper GPIO cleanup

HARDWARE REQUIREMENTS:
    - Raspberry Pi (any model with GPIO)
    - Relay module connected to GPIO pin 17 (configurable)
    - Router connected to relay's normally-open (NO) contacts

WIRING:
    - GPIO Pin 17 -> Relay IN/Signal pin
    - GND -> Relay GND
    - Router power -> Relay COM (common)
    - Power source -> Relay NO (normally open)

    When GPIO pin goes HIGH, relay energizes and cuts power to router.
    When GPIO pin goes LOW, relay de-energizes and restores power to router.

INSTALLATION:
    1. Create a virtual environment:
       python3 -m venv venv

    2. Activate the virtual environment:
       source venv/bin/activate

    3. Install required packages:
       pip install RPi.GPIO

    Note: RPi.GPIO is the only external dependency. All other modules
          (time, subprocess, logging, signal, sys, threading, http.server)
          are part of Python's standard library.

USAGE:
    1. Create a configuration file:
       python3 router-rebooter.py --create-config router-rebooter.conf

       Then edit the configuration file to customize settings.

    2. Make the script executable (optional):
       chmod +x router-rebooter.py

    3. Run the script:
       ./router-rebooter.py --config router-rebooter.conf

       Or with Python directly:
       python3 router-rebooter.py --config router-rebooter.conf

       Or use default config file location:
       python3 router-rebooter.py

    4. Access the web interface:
       Open a browser and navigate to:
       http://<raspberry-pi-ip>:8080

       To find your Raspberry Pi's IP address:
       hostname -I

RUNNING AS A SERVICE (Optional):
    To run this script automatically on boot, create a systemd service:

    1. Create service file:
       sudo nano /etc/systemd/system/router-rebooter.service

    2. Add the following content:
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

    3. Enable and start the service:
       sudo systemctl daemon-reload
       sudo systemctl enable router-rebooter.service
       sudo systemctl start router-rebooter.service

    4. Check status:
       sudo systemctl status router-rebooter.service

CONFIGURATION:
    The script requires a configuration file (default: router-rebooter.conf).
    Create one using the --create-config option.

    Configuration file format (INI style):

    [Network]
    ping_host = 8.8.8.8              # Host to ping for internet check
    ping_retries = 5                  # Number of ping retries before declaring offline
    ping_timeout = 2                  # Seconds to wait for ping response
    ping_packet_size = 0              # Ping packet data size in bytes (0-65507, default 0)
    check_interval_online = 10        # Seconds between checks when internet is up
    check_interval_offline = 30       # Seconds between checks when internet is down

    [GPIO]
    relay_pin = 17                    # GPIO pin number for relay control

    [HTTP]
    port = 8080                       # Web interface port
    auth_username =                   # HTTP Basic Auth username (leave empty to disable)
    auth_password =                   # HTTP Basic Auth password (leave empty to disable)
    ssl_enabled = false               # Enable HTTPS with self-signed certificate
    ssl_cert = cert.pem               # Path to SSL certificate file
    ssl_key = key.pem                 # Path to SSL private key file

    [Logging]
    log_file = router-rebooter.log    # Log file path
    log_level = INFO                  # Log level (DEBUG, INFO, WARNING, ERROR)

    Create a config file:
    python3 router-rebooter.py --create-config router-rebooter.conf

    Use a custom config file:
    python3 router-rebooter.py --config /path/to/custom.conf

LOG FILE:
    All events are logged to 'router-rebooter.log' with timestamps.
    The log file is appended to (not overwritten) on each restart.
    View logs via web interface at http://<ip>:8080 or directly in the file.

"""

import time
import subprocess
import logging
import signal
import sys
import threading
import socket
import argparse
import configparser
import os
import base64
import ssl
from http.server import HTTPServer, BaseHTTPRequestHandler
from queue import Queue
import RPi.GPIO as GPIO

# Default configuration file path
DEFAULT_CONFIG_FILE = 'router-rebooter.conf'

# Global event queue for communication between web server and main loop
reboot_queue = Queue()

# Global configuration (will be loaded from config file in main)
# Declared here for reference by functions
config = {}

def create_default_config(config_path):
    """Create a default configuration file and exit."""
    if os.path.exists(config_path):
        print(f"Error: Configuration file already exists: {config_path}")
        print("Remove it first or specify a different path.")
        sys.exit(1)

    parser = configparser.ConfigParser()

    # Add comments by writing manually
    with open(config_path, 'w') as f:
        f.write("# Router Rebooter Configuration File\n")
        f.write("# Edit these settings as needed\n\n")

    parser['Network'] = {
        'ping_host': '8.8.8.8',
        'ping_retries': '5',
        'ping_timeout': '2',
        'ping_packet_size': '0',
        'check_interval_online': '10',
        'check_interval_offline': '30'
    }

    parser['GPIO'] = {
        'relay_pin': '17'
    }

    parser['HTTP'] = {
        'port': '8080',
        'auth_username': '',
        'auth_password': '',
        'ssl_enabled': 'false',
        'ssl_cert': 'cert.pem',
        'ssl_key': 'key.pem'
    }

    parser['Logging'] = {
        'log_file': 'router-rebooter.log',
        'log_level': 'INFO'
    }

    with open(config_path, 'a') as f:
        parser.write(f)

    print(f"Created default configuration file: {config_path}")
    sys.exit(0)

def load_config(config_path):
    """Load configuration from file."""
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found: {config_path}")
        print(f"\nCreate a default configuration file with:")
        print(f"  {sys.argv[0]} --create-config {config_path}")
        sys.exit(1)

    parser = configparser.ConfigParser()
    parser.read(config_path)

    # Load configuration into global dict
    cfg = {
        'ping_host': parser.get('Network', 'ping_host'),
        'ping_retries': parser.getint('Network', 'ping_retries'),
        'ping_timeout': parser.getint('Network', 'ping_timeout', fallback=2),
        'ping_packet_size': parser.getint('Network', 'ping_packet_size', fallback=0),
        'check_interval_online': parser.getint('Network', 'check_interval_online'),
        'check_interval_offline': parser.getint('Network', 'check_interval_offline'),
        'relay_pin': parser.getint('GPIO', 'relay_pin'),
        'http_port': parser.getint('HTTP', 'port'),
        'http_auth_username': parser.get('HTTP', 'auth_username', fallback=''),
        'http_auth_password': parser.get('HTTP', 'auth_password', fallback=''),
        'ssl_enabled': parser.getboolean('HTTP', 'ssl_enabled', fallback=False),
        'ssl_cert': parser.get('HTTP', 'ssl_cert', fallback='cert.pem'),
        'ssl_key': parser.get('HTTP', 'ssl_key', fallback='key.pem'),
        'log_file': parser.get('Logging', 'log_file'),
        'log_level': parser.get('Logging', 'log_level'),
        'config_path': config_path
    }

    return cfg

# Logger will be configured after loading config
logger = logging.getLogger(__name__)

def setup_logging(log_file, log_level):
    """Configure logging after config is loaded."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, mode='a'),
            logging.StreamHandler()
        ],
        force=True  # Reconfigure if already configured
    )

def setup_gpio(relay_pin):
    """Configure GPIO after config is loaded."""
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(relay_pin, GPIO.OUT, initial=GPIO.LOW)

class LogViewerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for viewing logs."""

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass

    def check_auth(self):
        """Check HTTP Basic Authentication if enabled."""
        # If no auth configured, allow access
        if not config.get('http_auth_username') or not config.get('http_auth_password'):
            return True

        # Get Authorization header
        auth_header = self.headers.get('Authorization')
        if not auth_header:
            return False

        # Parse Basic Auth
        try:
            auth_type, auth_string = auth_header.split(' ', 1)
            if auth_type.lower() != 'basic':
                return False

            # Decode base64 credentials
            decoded = base64.b64decode(auth_string).decode('utf-8')
            username, password = decoded.split(':', 1)

            # Check credentials
            return (username == config['http_auth_username'] and
                    password == config['http_auth_password'])
        except Exception:
            return False

    def send_auth_required(self):
        """Send 401 Unauthorized response."""
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Router Rebooter"')
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<html><body><h1>401 Unauthorized</h1><p>Authentication required.</p></body></html>')

    def do_GET(self):
        """Handle GET requests."""
        # Check authentication
        if not self.check_auth():
            self.send_auth_required()
            return

        if self.path == '/' or self.path == '/logs':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

            html = self.generate_log_page()
            self.wfile.write(html.encode())
        elif self.path == '/raw':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()

            try:
                with open(config['log_file'], 'r') as f:
                    self.wfile.write(f.read().encode())
            except FileNotFoundError:
                self.wfile.write(b"Log file not found.")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 - Not Found")

    def do_POST(self):
        """Handle POST requests."""
        # Check authentication
        if not self.check_auth():
            self.send_auth_required()
            return

        if self.path == '/reboot':
            # Queue a reboot request
            reboot_queue.put('manual_reboot')
            logger.info("Manual reboot requested via web interface")

            # Send response
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

            html = """<!DOCTYPE html>
<html>
<head>
    <title>Reboot Requested</title>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="3;url=/">
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #1e1e1e;
            color: #d4d4d4;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .message {
            text-align: center;
            padding: 40px;
            background-color: #252526;
            border-radius: 10px;
            border: 2px solid #0e639c;
        }
        h1 { color: #4ec9b0; }
        p { font-size: 18px; }
    </style>
</head>
<body>
    <div class="message">
        <h1>✅ Router Reboot Requested</h1>
        <p>The router will be rebooted shortly...</p>
        <p><small>Redirecting to logs in 3 seconds...</small></p>
    </div>
</body>
</html>"""
            self.wfile.write(html.encode())
        elif self.path == '/clear-log':
            # Clear the log file
            try:
                with open(config['log_file'], 'w') as f:
                    f.write('')
                logger.info("Log file cleared via web interface")

                # Send simple success response
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b"OK")
            except Exception as e:
                logger.error(f"Error clearing log file: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(f"Error: {e}".encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 - Not Found")

    def generate_log_page(self):
        """Generate HTML page with log content."""
        try:
            with open(config['log_file'], 'r') as f:
                log_content = f.read()
        except FileNotFoundError:
            log_content = "Log file not found."

        # Get last 1000 lines to avoid huge pages
        lines = log_content.split('\n')
        if len(lines) > 1000:
            log_content = '\n'.join(lines[-1000:])
            truncated_msg = f"(Showing last 1000 lines of {len(lines)} total)\n\n"
        else:
            truncated_msg = ""

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Router Rebooter Logs</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
            background-color: #1e1e1e;
            color: #d4d4d4;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #4ec9b0;
            margin-bottom: 10px;
        }}
        .controls {{
            margin-bottom: 20px;
            padding: 10px;
            background-color: #252526;
            border-radius: 5px;
        }}
        .controls button {{
            background-color: #0e639c;
            color: white;
            border: none;
            padding: 8px 16px;
            margin-right: 10px;
            cursor: pointer;
            border-radius: 3px;
            font-size: 14px;
        }}
        .controls button:hover {{
            background-color: #1177bb;
        }}
        .controls button.reboot {{
            background-color: #d9534f;
        }}
        .controls button.reboot:hover {{
            background-color: #c9302c;
        }}
        .controls button.clear {{
            background-color: #f0ad4e;
        }}
        .controls button.clear:hover {{
            background-color: #ec971f;
        }}
        .log-box {{
            background-color: #252526;
            border: 1px solid #3e3e42;
            border-radius: 5px;
            padding: 15px;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 13px;
            line-height: 1.5;
            max-height: 80vh;
            overflow-y: auto;
        }}
        .warning {{
            color: #dcdcaa;
        }}
        .info {{
            color: #4ec9b0;
        }}
        .error {{
            color: #f48771;
        }}
        .truncated {{
            color: #ce9178;
            font-style: italic;
            margin-bottom: 10px;
        }}
    </style>
    <script>
        function refreshPage() {{
            location.reload();
        }}
        function scrollToBottom() {{
            var logBox = document.getElementById('logBox');
            logBox.scrollTop = logBox.scrollHeight;
        }}
        function rebootRouter() {{
            if (confirm('Are you sure you want to reboot the router?')) {{
                fetch('/reboot', {{
                    method: 'POST'
                }})
                .then(response => response.text())
                .then(html => {{
                    document.body.innerHTML = html;
                }})
                .catch(error => {{
                    alert('Error requesting reboot: ' + error);
                }});
            }}
        }}
        function clearLog() {{
            if (confirm('Are you sure you want to clear the log file? This cannot be undone.')) {{
                fetch('/clear-log', {{
                    method: 'POST'
                }})
                .then(response => {{
                    if (response.ok) {{
                        location.reload();  // Just reload the page to show empty log
                    }} else {{
                        alert('Error clearing log');
                    }}
                }})
                .catch(error => {{
                    alert('Error clearing log: ' + error);
                }});
            }}
        }}
        window.onload = function() {{
            scrollToBottom();
        }};
    </script>
</head>
<body>
    <div class="container">
        <h1>🔌 Router Rebooter</h1>
        <div class="controls">
            <button onclick="refreshPage()">🔄 Refresh</button>
            <button onclick="scrollToBottom()">⬇️ Scroll to Bottom</button>
            <button onclick="window.open('/raw', '_blank')">📄 View Raw</button>
            <button class="reboot" onclick="rebootRouter()">🔌 Reboot Router</button>
            <button class="clear" onclick="clearLog()">🗑️ Clear Log</button>
        </div>
        <div class="truncated">{truncated_msg}</div>
        <div class="log-box" id="logBox">{self.colorize_logs(log_content)}</div>
    </div>
</body>
</html>"""
        return html

    def colorize_logs(self, log_content):
        """Add color classes to log lines based on level."""
        lines = log_content.split('\n')
        colored_lines = []
        for line in lines:
            if ' - WARNING - ' in line:
                colored_lines.append(f'<span class="warning">{self.escape_html(line)}</span>')
            elif ' - ERROR - ' in line:
                colored_lines.append(f'<span class="error">{self.escape_html(line)}</span>')
            elif ' - INFO - ' in line:
                colored_lines.append(f'<span class="info">{self.escape_html(line)}</span>')
            else:
                colored_lines.append(self.escape_html(line))
        return '\n'.join(colored_lines)

    def escape_html(self, text):
        """Escape HTML special characters."""
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def generate_self_signed_cert(cert_file, key_file):
    """Generate a self-signed SSL certificate using openssl command."""
    try:
        # Check if files already exist
        if os.path.exists(cert_file) and os.path.exists(key_file):
            logger.info(f"SSL certificate already exists: {cert_file}")
            return True

        logger.info("Generating self-signed SSL certificate...")

        # Generate self-signed certificate using openssl
        result = subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-keyout', key_file,
            '-out', cert_file,
            '-days', '365',
            '-nodes',
            '-subj', '/CN=router-rebooter'
        ], capture_output=True, text=True)

        if result.returncode == 0:
            logger.info(f"SSL certificate generated: {cert_file}")
            return True
        else:
            logger.error(f"Failed to generate SSL certificate: {result.stderr}")
            return False
    except FileNotFoundError:
        logger.error("openssl command not found. Install openssl to use SSL.")
        return False
    except Exception as e:
        logger.error(f"Error generating SSL certificate: {e}")
        return False

def create_http_server():
    """Create HTTP server instance (for error checking before threading)."""
    try:
        server = HTTPServer(('0.0.0.0', config['http_port']), LogViewerHandler)

        # Enable SSL if configured
        if config.get('ssl_enabled'):
            cert_file = config['ssl_cert']
            key_file = config['ssl_key']

            # Generate certificate if it doesn't exist
            if not os.path.exists(cert_file) or not os.path.exists(key_file):
                if not generate_self_signed_cert(cert_file, key_file):
                    logger.error("Failed to generate SSL certificate. Exiting.")
                    sys.exit(1)

            # Wrap socket with SSL
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_file, key_file)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            logger.info("SSL enabled")

        return server
    except OSError as e:
        logger.error(f"Failed to start HTTP server on port {config['http_port']}: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error starting HTTP server: {e}")
        sys.exit(1)

def start_http_server(server):
    """Run HTTP server (called in background thread)."""
    protocol = "HTTPS" if config.get('ssl_enabled') else "HTTP"
    logger.info(f"{protocol} server started on port {config['http_port']}")
    server.serve_forever()

def get_local_ip():
    """Get the local IP address of the Raspberry Pi."""
    try:
        # Create a socket connection to determine local IP
        # This doesn't actually send data, just determines routing
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        # Fallback: try to get from hostname
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "localhost"

def cleanup_and_exit(signum=None, frame=None):
    """Clean up GPIO on exit."""
    logger.info("Shutting down router rebooter...")
    GPIO.cleanup()
    sys.exit(0)

# Register signal handlers for clean shutdown
signal.signal(signal.SIGINT, cleanup_and_exit)
signal.signal(signal.SIGTERM, cleanup_and_exit)

def check_internet():
    """Check if internet is available by pinging a host with retries."""
    host = config['ping_host']
    retries = config['ping_retries']
    timeout = config['ping_timeout']
    packet_size = config['ping_packet_size']
    failed_attempts = 0

    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["ping", "-c1", f"-W{timeout}", f"-s{packet_size}", host],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if result.returncode == 0:
                # Report packet loss if there were any failures before success
                if failed_attempts > 0:
                    loss_percent = (failed_attempts / (attempt + 1)) * 100
                    logger.warning(f"Packet loss detected: {failed_attempts}/{attempt + 1} packets lost ({loss_percent:.1f}%)")
                return True  # Success - internet is up
            else:
                failed_attempts += 1
        except Exception as e:
            failed_attempts += 1
            logger.error(f"Error checking internet (attempt {attempt + 1}/{retries}): {e}")

        # If failed and not last attempt, wait before retry
        if attempt < retries - 1:
            time.sleep(1)

    # All retries failed
    logger.warning(f"Internet check failed: {failed_attempts}/{retries} packets lost (100% packet loss)")
    return False

def reboot_router():
    """Power cycle the router via relay."""
    logger.warning("Rebooting router...")
    GPIO.output(config['relay_pin'], GPIO.HIGH)  # Turn router OFF
    time.sleep(5)  # Keep router off for 5 seconds
    GPIO.output(config['relay_pin'], GPIO.LOW)   # Turn router ON
    logger.info("Router reboot complete.")
    time.sleep(5)  # Take a breather before doing anything else

def main():
    """Main monitoring loop."""
    # Create HTTP server (this will exit if there's an error)
    http_server = create_http_server()

    # Start HTTP server in background thread
    http_thread = threading.Thread(target=start_http_server, args=(http_server,), daemon=True)
    http_thread.start()

    internet_was_online = True
    has_rebooted = False

    logger.info("Router rebooter started. Monitoring internet connection...")

    # Get and display the actual IP address
    local_ip = get_local_ip()
    protocol = "https" if config.get('ssl_enabled') else "http"
    logger.info(f"Web interface available at {protocol}://{local_ip}:{config['http_port']}")

    try:
        while True:
            # Check for manual reboot requests from web interface
            if not reboot_queue.empty():
                reboot_queue.get()  # Clear the queue
                reboot_router()
                # Assume internet goes offline after manual reboot
                internet_was_online = False
                has_rebooted = True
                continue

            internet_is_online = check_internet()

            if internet_is_online:
                if not internet_was_online:
                    logger.info("Internet connection restored!")
                    has_rebooted = False
                internet_was_online = True
                time.sleep(config['check_interval_online'])
            else:
                if internet_was_online:
                    logger.warning("Internet connection lost!")
                    internet_was_online = False

                if not has_rebooted:
                    reboot_router()
                    has_rebooted = True
                else:
                    logger.info(f"Internet still down (already rebooted). Checking again in {config['check_interval_offline']} seconds...")
                    time.sleep(config['check_interval_offline'])

    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        cleanup_and_exit()

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Router Rebooter - Automatic Internet Connection Monitor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a default configuration file
  python3 router-rebooter.py --create-config router-rebooter.conf

  # Run with default config file
  python3 router-rebooter.py

  # Run with custom config file
  python3 router-rebooter.py --config /path/to/custom.conf
        """
    )
    parser.add_argument('-c', '--config',
                        default=DEFAULT_CONFIG_FILE,
                        help=f'Path to configuration file (default: {DEFAULT_CONFIG_FILE})')
    parser.add_argument('--create-config',
                        metavar='PATH',
                        help='Create a default configuration file at PATH and exit')
    args = parser.parse_args()

    # Handle --create-config
    if args.create_config:
        create_default_config(args.create_config)
        # create_default_config() calls sys.exit(), so we never reach here

    # Load configuration into global config dict
    config.update(load_config(args.config))

    # Setup logging and GPIO based on config
    setup_logging(config['log_file'], config['log_level'])
    setup_gpio(config['relay_pin'])

    # Run main loop
    main()
