#!/usr/bin/env python3
"""Polls Noisebridge open/closed API and updates Home Assistant sensor entity."""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# Load HA config from .ha_env
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

if not HA_TOKEN:
    print("No HA_TOKEN found in .ha_env", file=sys.stderr)
    sys.exit(1)

NB_API = "https://noisebell.extremist.software/status"
ENTITY_ID = "sensor.noisebridge_open_status"

# Fetch Noisebridge status
try:
    req = urllib.request.Request(NB_API)
    with urllib.request.urlopen(req, timeout=10) as resp:
        nb_data = json.loads(resp.read())
except Exception as e:
    print(f"{datetime.now().isoformat()} Failed to fetch Noisebridge status: {e}", file=sys.stderr)
    sys.exit(1)

status = nb_data["status"]
since_unix = nb_data["since"]
last_checked_unix = nb_data["last_checked"]
human_readable = nb_data["human_readable"]

since_iso = datetime.fromtimestamp(since_unix, tz=timezone.utc).isoformat()
checked_iso = datetime.fromtimestamp(last_checked_unix, tz=timezone.utc).isoformat()

icon = "mdi:door-open" if status == "open" else "mdi:door-closed"

payload = json.dumps({
    "state": status,
    "attributes": {
        "friendly_name": "Noisebridge Open Status",
        "icon": icon,
        "since": since_iso,
        "since_unix": since_unix,
        "last_checked": checked_iso,
        "human_readable": human_readable,
        "source_url": NB_API,
    },
}).encode()

# Update HA entity
try:
    req = urllib.request.Request(
        f"{HA_URL}/api/states/{ENTITY_ID}",
        data=payload,
        headers={
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
except Exception as e:
    print(f"{datetime.now().isoformat()} Failed to update HA entity: {e}", file=sys.stderr)
    sys.exit(1)

print(f"{datetime.now().isoformat()} Updated {ENTITY_ID}: {status}")
