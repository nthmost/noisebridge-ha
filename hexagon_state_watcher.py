#!/usr/bin/env python3
"""Hexagon state watcher — TEMPORARY band-aid.

Subscribes to the hexagon's MQTT state topic. The moment the Pico publishes
{"state":"OFF"} (which it does spuriously on every MQTT reconnect, due to a
bug in the deployed sp648e-controller mqtt.py), this watcher re-publishes the
correct command immediately:

    sensor.noisebridge_open_status=open    →  state=ON, effect="Rainbow Meteor"
    sensor.noisebridge_open_status=closed  →  state=ON, effect="Comet Red"

The fix is committed at https://github.com/nthmost/sp648e-controller/commit/dd7b7a7
but not yet deployed to the Pico. When it is, REMOVE THIS WATCHER:

    sudo systemctl disable --now hexagon_state_watcher.service
    sudo rm /etc/systemd/system/hexagon_state_watcher.service
    sudo systemctl daemon-reload
    # then remove MQTT_* lines from ~/projects/noisebridge-ha/.ha_env
    # then remove this script from the repo

Reads HA + MQTT credentials from ~/projects/noisebridge-ha/.ha_env.

Uses mosquitto_sub via subprocess (no extra Python deps) and mosquitto_pub
to react. Subscribes for the lifetime of the process; intended to run as a
systemd service. If mosquitto_sub dies, this script exits and systemd will
restart it.
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

STATE_TOPIC = "sp648e/wiresprite_hexagon/state"
SET_TOPIC = "sp648e/wiresprite_hexagon/set"
EFFECT_FOR = {"open": "Rainbow Meteor", "closed": "Comet Red"}


def get_sensor():
    req = urllib.request.Request(
        f"{HA_URL}/api/states/sensor.noisebridge_open_status",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["state"]


def publish(payload):
    subprocess.run(
        ["mosquitto_pub", "-h", MQTT_HOST, "-u", MQTT_USER, "-P", MQTT_PASS,
         "-t", SET_TOPIC, "-m", json.dumps(payload)],
        check=True, timeout=10,
    )


def handle_state(payload_str):
    try:
        payload = json.loads(payload_str)
    except Exception:
        print(f"unparseable state payload: {payload_str!r}", flush=True)
        return
    if payload.get("state") != "OFF":
        return  # ON state is fine, nothing to correct

    try:
        sensor = get_sensor()
    except Exception as e:
        print(f"HA sensor fetch failed: {e!r}", flush=True)
        return

    effect = EFFECT_FOR.get(sensor)
    if effect is None:
        print(f"sensor in unexpected state {sensor!r}; skipping correction", flush=True)
        return

    print(f"hexagon went OFF (sensor={sensor}); republishing state=ON effect={effect!r}",
          flush=True)
    try:
        publish({"state": "ON", "effect": effect})
    except Exception as e:
        print(f"correction publish failed: {e!r}", flush=True)


def main():
    # `-F %j` gives one JSON object per message: {"tst":..., "topic":..., "qos":..., "retain":..., "payloadlen":..., "payload":...}
    cmd = [
        "mosquitto_sub",
        "-h", MQTT_HOST,
        "-u", MQTT_USER, "-P", MQTT_PASS,
        "-t", STATE_TOPIC,
        "-F", "%j",
        "-q", "1",
    ]
    print(f"subscribing to {STATE_TOPIC} on {MQTT_HOST}", flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                print(f"unparseable line: {line!r}", flush=True)
                continue
            handle_state(msg.get("payload", ""))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    rc = proc.returncode or 1
    print(f"mosquitto_sub exited rc={rc}; surfacing for systemd to restart", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
