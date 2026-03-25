#!/usr/bin/env python3
"""
Lightweight HTTP server that exposes Noisebridge open/closed status from Home Assistant.
Listens on port 8099 by default. No authentication required for consumers.

Endpoints:
  GET /          - JSON response with full status
  GET /status    - Plain text "open" or "closed"
  GET /health    - Health check
"""

import json
import os
import sys
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

PORT = int(os.environ.get("NB_STATUS_PORT", 8099))

# Load HA config
HA_ENV = os.environ.get("HA_ENV_FILE", os.path.join(os.path.dirname(__file__), ".ha_env"))
ha_config = {}
with open(HA_ENV) as f:
    for line in f:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line and not line.startswith("#") and not line.startswith("function"):
            key, _, val = line.partition("=")
            val = val.strip('"').strip("'")
            if val:
                ha_config[key] = val

HA_URL = ha_config.get("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = ha_config.get("HA_TOKEN", "")
ENTITY_ID = "sensor.noisebridge_open_status"


def get_ha_state():
    """Fetch entity state from Home Assistant."""
    req = urllib.request.Request(
        f"{HA_URL}/api/states/{ENTITY_ID}",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path == "/health":
                self._respond(200, {"status": "ok"})
                return

            data = get_ha_state()
            attrs = data.get("attributes", {})

            if self.path == "/status":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data["state"].encode())
                return

            # Full JSON response
            response = {
                "status": data["state"],
                "since": attrs.get("since"),
                "since_unix": attrs.get("since_unix"),
                "last_checked": attrs.get("last_checked"),
                "human_readable": attrs.get("human_readable"),
                "source": "Home Assistant @ homeassistant.local",
                "upstream_api": attrs.get("source_url"),
            }
            self._respond(200, response)

        except Exception as e:
            self._respond(502, {"error": str(e)})

    def _respond(self, code, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), StatusHandler)
    print(f"Noisebridge status server listening on port {PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
