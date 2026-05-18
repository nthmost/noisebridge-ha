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
from datetime import datetime


def log(msg):
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


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
AVAILABILITY_TOPIC = "sp648e/wiresprite_hexagon/availability"
EFFECT_FOR = {"open": "Rainbow Meteor", "closed": "Comet Red"}


def get_sensor():
    req = urllib.request.Request(
        f"{HA_URL}/api/states/sensor.noisebridge_open_status",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["state"]


def publish_state_correction(payload):
    """Publish DIRECTLY to the state topic (retained) — corrects HA's view of the
    light without sending any command to the Pico, so the LED is never touched."""
    subprocess.run(
        ["mosquitto_pub", "-h", MQTT_HOST, "-u", MQTT_USER, "-P", MQTT_PASS,
         "-t", STATE_TOPIC, "-m", json.dumps(payload), "-r"],
        check=True, timeout=10,
    )


def handle_state(payload_str):
    try:
        payload = json.loads(payload_str)
    except Exception:
        log(f"unparseable state payload: {payload_str!r}")
        return
    if payload.get("state") != "OFF":
        return  # ON state is fine, nothing to correct

    try:
        sensor = get_sensor()
    except Exception as e:
        log(f"HA sensor fetch failed: {e!r}")
        return

    effect = EFFECT_FOR.get(sensor)
    if effect is None:
        log(f"sensor in unexpected state {sensor!r}; skipping correction")
        return

    # CRUCIAL: publish to STATE topic (not SET) — corrects HA's view without
    # triggering any BLE command to the Pico. The physical LED stays in whatever
    # last-commanded state (which the noisebell automation ensures matches the
    # sensor). Going through SET would cause the Pico to re-issue a BLE write
    # that might restart the effect animation — visible as a flicker/reset.
    log(f"spurious OFF on state topic; republishing ON+{effect!r} to state (no BLE write)")
    try:
        publish_state_correction({"state": "ON", "effect": effect})
    except Exception as e:
        log(f"correction publish failed: {e!r}")


def main():
    # `-F %j` gives one JSON object per message: {"tst":..., "topic":..., "qos":..., "retain":..., "payloadlen":..., "payload":...}
    # Subscribe to BOTH state and availability topics so we can characterize the
    # underlying reconnect rate (availability transitions) alongside the
    # state-OFF firings that we actually act on.
    cmd = [
        "mosquitto_sub",
        "-h", MQTT_HOST,
        "-u", MQTT_USER, "-P", MQTT_PASS,
        "-t", STATE_TOPIC,
        "-t", AVAILABILITY_TOPIC,
        "-F", "%j",
        "-q", "1",
    ]
    log(f"subscribing to {STATE_TOPIC} + {AVAILABILITY_TOPIC} on {MQTT_HOST}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                log(f"unparseable line: {line!r}")
                continue

            topic = msg.get("topic", "")
            payload = msg.get("payload", "")
            retain = msg.get("retain", 0)

            if topic == AVAILABILITY_TOPIC:
                # Just log; don't act. Each transition = one Pico MQTT bounce.
                log(f"availability: {payload!r} (retain={retain})")
            elif topic == STATE_TOPIC:
                log(f"state: {payload!r} (retain={retain})")
                handle_state(payload)
            else:
                log(f"unexpected topic {topic!r}: {payload!r}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    rc = proc.returncode or 1
    log(f"mosquitto_sub exited rc={rc}; surfacing for systemd to restart")
    return rc


if __name__ == "__main__":
    sys.exit(main())
