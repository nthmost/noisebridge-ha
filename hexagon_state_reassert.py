#!/usr/bin/env python3
"""Hexagon state reassertion — TEMPORARY band-aid.

Every cron tick, compares light.hexagon's HA state against the expected
state based on sensor.noisebridge_open_status:

    sensor=open    →  hexagon should be ON with effect "Rainbow Meteor"
    sensor=closed  →  hexagon should be ON with effect "Comet Red"

If they don't match, publishes the correct command to MQTT to bring the
hexagon back in line.

=== Why this exists ===

The deployed sp648e-controller mqtt.py (running on the Pico) publishes
{"state":"OFF"} on every MQTT (re)connect. Any WiFi blip or broker
restart causes HA's view of the hexagon to flip to OFF even though the
LED panel itself is still lit. The fix is committed to the public repo
at https://github.com/nthmost/sp648e-controller/commit/dd7b7a7 but has
not been deployed to the Pico yet.

=== When to remove ===

Once the Pico is reflashed with the fixed mqtt.py:

  1. Remove the cron entry on beyla:
     crontab -e   # then delete the */5 hexagon_state_reassert line
  2. Remove this script from the noisebridge-ha repo

Reads HA REST and MQTT credentials from ~/projects/noisebridge-ha/.ha_env.
"""

import json
import os
import subprocess
import sys
import urllib.request

HA_ENV = os.environ.get("HA_ENV_FILE", os.path.join(os.path.dirname(__file__), ".ha_env"))

ha_config = {}
with open(HA_ENV) as f:
    for line in f:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line and not line.startswith("#") and not line.startswith("function"):
            k, _, v = line.partition("=")
            v = v.strip('"').strip("'")
            if v:
                ha_config[k] = v

HA_URL = ha_config["HA_URL"]
HA_TOKEN = ha_config["HA_TOKEN"]
MQTT_HOST = ha_config["MQTT_HOST"]
MQTT_USER = ha_config["MQTT_USER"]
MQTT_PASS = ha_config["MQTT_PASS"]

EFFECT_FOR = {"open": "Rainbow Meteor", "closed": "Comet Red"}
MQTT_SET_TOPIC = "sp648e/wiresprite_hexagon/set"


def ha_state(entity_id):
    req = urllib.request.Request(
        f"{HA_URL}/api/states/{entity_id}",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def publish(payload):
    subprocess.run(
        ["mosquitto_pub", "-h", MQTT_HOST, "-u", MQTT_USER, "-P", MQTT_PASS,
         "-t", MQTT_SET_TOPIC, "-m", json.dumps(payload)],
        check=True, timeout=10,
    )


def main():
    sensor = ha_state("sensor.noisebridge_open_status")["state"]
    if sensor not in EFFECT_FOR:
        # sensor might say "unknown" / "unavailable" — don't touch the hexagon
        print(f"sensor in unexpected state {sensor!r}; skipping")
        return 0

    expected_effect = EFFECT_FOR[sensor]
    hexagon = ha_state("light.hexagon")
    current_state = hexagon["state"]
    current_effect = hexagon.get("attributes", {}).get("effect")

    if current_state == "on" and current_effect == expected_effect:
        # Already correct, no need to nudge
        return 0

    print(f"reassert: sensor={sensor} hexagon=({current_state}, effect={current_effect!r}) "
          f"→ publishing state=ON effect={expected_effect!r}")
    publish({"state": "ON", "effect": expected_effect})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"hexagon_state_reassert: error: {e!r}", file=sys.stderr)
        sys.exit(1)
