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
    1. Make the script executable:
       chmod +x router-rebooter.py

    2. Run the script:
       ./router-rebooter.py

       Or with Python directly:
       python3 router-rebooter.py

    3. Access the web interface:
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
       ExecStart=/home/pi/router-rebooter/venv/bin/python3 /home/pi/router-rebooter/router-rebooter.py
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
    Edit the constants at the top of the script to customize:
    - RELAY_PIN: GPIO pin number (default: 17)
    - LOG_FILE: Log file path (default: 'router-rebooter.log')
    - HTTP_PORT: Web interface port (default: 8080)

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
from http.server import HTTPServer, BaseHTTPRequestHandler
from queue import Queue
import RPi.GPIO as GPIO

# Configuration
RELAY_PIN = 17
LOG_FILE = 'router-rebooter.log'
HTTP_PORT = 8080

# Global event queue for communication between web server and main loop
reboot_queue = Queue()

# Configure logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# GPIO setup
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)

class LogViewerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for viewing logs."""

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass

    def do_GET(self):
        """Handle GET requests."""
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
                with open(LOG_FILE, 'r') as f:
                    self.wfile.write(f.read().encode())
            except FileNotFoundError:
                self.wfile.write(b"Log file not found.")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 - Not Found")

    def do_POST(self):
        """Handle POST requests."""
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
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 - Not Found")

    def generate_log_page(self):
        """Generate HTML page with log content."""
        try:
            with open(LOG_FILE, 'r') as f:
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
        window.onload = function() {{
            scrollToBottom();
        }};
    </script>
</head>
<body>
    <div class="container">
        <h1>🔌 Router Rebooter Logs</h1>
        <div class="controls">
            <button onclick="refreshPage()">🔄 Refresh</button>
            <button onclick="scrollToBottom()">⬇️ Scroll to Bottom</button>
            <button onclick="window.open('/raw', '_blank')">📄 View Raw</button>
            <button class="reboot" onclick="rebootRouter()">🔌 Reboot Router</button>
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

def start_http_server():
    """Start HTTP server in a separate thread."""
    server = HTTPServer(('0.0.0.0', HTTP_PORT), LogViewerHandler)
    logger.info(f"HTTP server started on port {HTTP_PORT}")
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
    time.sleep(5)  # Keep router off for 5 seconds
    GPIO.output(RELAY_PIN, GPIO.LOW)   # Turn router ON
    logger.info("Router reboot complete.")
    time.sleep(5)  # Take a breather before doing anything else

def main():
    """Main monitoring loop."""
    # Start HTTP server in background thread
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    internet_was_online = True
    has_rebooted = False

    logger.info("Router rebooter started. Monitoring internet connection...")

    # Get and display the actual IP address
    local_ip = get_local_ip()
    logger.info(f"Web interface available at http://{local_ip}:{HTTP_PORT}")

    try:
        while True:
            # Check for manual reboot requests from web interface
            if not reboot_queue.empty():
                reboot_queue.get()  # Clear the queue
                reboot_router()
                has_rebooted = True
                continue

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
                else:
                    logger.info("Internet still down (already rebooted). Checking again in 30 seconds...")
                    time.sleep(30)

    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        cleanup_and_exit()

if __name__ == "__main__":
    main()
