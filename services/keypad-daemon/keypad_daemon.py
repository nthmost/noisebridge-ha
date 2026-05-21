#!/usr/bin/env python3
"""
Keypad Daemon — hijacks a USB numpad and fires Home Assistant webhooks.

Captures keys from event3, dial from event4 (Consumer Control),
and donut button from event8.

Usage:
    sudo ./keypad-venv/bin/python keypad_daemon.py [--dry-run]

The devices are auto-detected by name ("2.4G Wireless Keyboard").
"""

import argparse
import json
import signal
import select
import sys
from pathlib import Path

import evdev
import requests

from led_control import LedController

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "keypad_config.json"

DEFAULT_CONFIG = {
    "ha_base_url": "http://homeassistant.local:8123",
    "device_name": "2.4G Wireless Keyboard",
    # Map evdev key names -> webhook IDs.
    # Each value is either a webhook_id string or a dict with more options.
    "key_map": {
        "KEY_KP0": {"webhook": "keypad_0", "label": "Numpad 0"},
        "KEY_KP1": {"webhook": "keypad_1", "label": "Numpad 1"},
        "KEY_KP2": {"webhook": "keypad_2", "label": "Numpad 2"},
        "KEY_KP3": {"webhook": "keypad_3", "label": "Numpad 3"},
        "KEY_KP4": {"webhook": "keypad_4", "label": "Numpad 4"},
        "KEY_KP5": {"webhook": "keypad_5", "label": "Numpad 5"},
        "KEY_KP6": {"webhook": "keypad_6", "label": "Numpad 6"},
        "KEY_KP7": {"webhook": "keypad_7", "label": "Numpad 7"},
        "KEY_KP8": {"webhook": "keypad_8", "label": "Numpad 8"},
        "KEY_KP9": {"webhook": "keypad_9", "label": "Numpad 9"},
        "KEY_KPENTER": {"webhook": "keypad_enter", "label": "Numpad Enter"},
        "KEY_KPPLUS": {"webhook": "keypad_plus", "label": "Numpad +"},
        "KEY_KPMINUS": {"webhook": "keypad_minus", "label": "Numpad -"},
        "KEY_KPASTERISK": {"webhook": "keypad_star", "label": "Numpad *"},
        "KEY_KPSLASH": {"webhook": "keypad_slash", "label": "Numpad /"},
        "KEY_KPDOT": {"webhook": "keypad_dot", "label": "Numpad ."},
        "KEY_NUMLOCK": {"webhook": "keypad_numlock", "label": "Num Lock"},
        "KEY_BACKSPACE": {"webhook": "keypad_backspace", "label": "Backspace"},
        "DONUT": {"webhook": "keypad_donut", "label": "Donut"},
        "DIAL_CW": {"webhook": "keypad_dial_cw", "label": "Dial CW"},
        "DIAL_CCW": {"webhook": "keypad_dial_ccw", "label": "Dial CCW"},
    },
}


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    # Write default config for the user to customise
    with open(CONFIG_PATH, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    print(f"Wrote default config to {CONFIG_PATH} — edit it to set your webhook IDs.")
    return DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

def find_devices(name_substring: str):
    """Return (key_dev, dial_dev, donut_dev) for the keypad.

    Detection is based on stable capabilities, not event numbers:
      - Primary keyboard: has EV_LED (for NumLock LED)
      - Consumer Control: "Consumer Control" in name (dial sends VOLUMEUP/DOWN)
      - Donut button: secondary keyboard with EV_KEY but no EV_LED
    """
    key_dev = None
    dial_dev = None
    donut_dev = None

    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if name_substring.lower() not in dev.name.lower():
            continue
        caps = dev.capabilities()

        # Consumer Control → dial device
        if "Consumer Control" in dev.name:
            dial_dev = dev
            continue

        # Skip non-keyboard devices
        if "Mouse" in dev.name or "System Control" in dev.name:
            continue
        if evdev.ecodes.EV_KEY not in caps:
            continue

        # Primary keyboard has EV_LED (NumLock indicator)
        if evdev.ecodes.EV_LED in caps:
            key_dev = dev
        else:
            # Secondary keyboard without LED = donut button device
            donut_dev = dev

    return key_dev, dial_dev, donut_dev


# ---------------------------------------------------------------------------
# Webhook caller
# ---------------------------------------------------------------------------

def fire_webhook(base_url: str, webhook_id: str, payload: dict | None = None):
    url = f"{base_url}/api/webhook/{webhook_id}"
    try:
        resp = requests.post(url, json=payload or {}, timeout=5)
        return resp.status_code
    except requests.RequestException as exc:
        print(f"  [!] Webhook error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(key_dev, dial_dev, donut_dev, config: dict, dry_run: bool = False,
        led: LedController | None = None):
    key_map = config["key_map"]
    base_url = config["ha_base_url"].rstrip("/")

    # Grab all devices exclusively
    grabbed = []
    for dev in [key_dev, dial_dev, donut_dev]:
        if dev and dev.path not in [d.path for d in grabbed]:
            print(f"Grabbing: {dev.name} ({dev.path})")
            dev.grab()
            grabbed.append(dev)

    def release(signum, frame):
        print("\nReleasing devices...")
        for dev in grabbed:
            dev.ungrab()
        if led:
            led.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, release)
    signal.signal(signal.SIGTERM, release)

    # Build fd -> device map
    watch_fds = {}
    for dev in grabbed:
        watch_fds[dev.fd] = dev
    donut_fd = donut_dev.fd if donut_dev else None

    print("Listening for keypad events (Ctrl+C to quit)...\n")

    def handle_action(action_key: str):
        mapping = key_map.get(action_key)
        if not mapping:
            print(f"  [{action_key}] — unmapped, ignoring")
            return

        if isinstance(mapping, str):
            webhook_id = mapping
            label = action_key
        else:
            webhook_id = mapping["webhook"]
            label = mapping.get("label", action_key)

        print(f"  [{label}] -> webhook: {webhook_id}", end="", flush=True)

        if dry_run:
            print(" (dry run)")
        else:
            status = fire_webhook(base_url, webhook_id)
            print(f" [{status}]" if status else " [FAILED]")

    while True:
        r, _, _ = select.select(list(watch_fds.keys()), [], [], 1)
        for fd in r:
            dev = watch_fds[fd]
            for event in dev.read():
                if event.type != evdev.ecodes.EV_KEY:
                    continue

                ke = evdev.categorize(event)
                if ke.keystate != evdev.KeyEvent.key_down:
                    continue

                key_name = ke.keycode
                if isinstance(key_name, list):
                    key_name = key_name[0]

                # Dial: volume keys on the Consumer Control device
                if key_name == "KEY_VOLUMEUP":
                    handle_action("DIAL_CW")
                    if led and led.is_available:
                        m = led.next_mode()
                        print(f"  [LED] mode -> {m}/{17}")
                    continue
                if key_name == "KEY_VOLUMEDOWN":
                    handle_action("DIAL_CCW")
                    if led and led.is_available:
                        m = led.prev_mode()
                        print(f"  [LED] mode -> {m}/{17}")
                    continue

                # Donut: KEY_BACKSPACE on the donut device (event8)
                if fd == donut_fd and key_name == "KEY_BACKSPACE":
                    handle_action("DONUT")
                    continue

                # Regular keys
                handle_action(key_name)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Keypad -> Home Assistant webhook daemon")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without calling webhooks")
    args = parser.parse_args()

    config = load_config()
    key_dev, dial_dev, donut_dev = find_devices(config["device_name"])

    if not key_dev:
        print(f"ERROR: Could not find device matching '{config['device_name']}'")
        print("Available devices:")
        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            print(f"  {path}: {dev.name}")
        sys.exit(1)

    print(f"Keyboard: {key_dev.name} ({key_dev.path})")
    if dial_dev:
        print(f"Dial:     {dial_dev.name} ({dial_dev.path})")
    else:
        print("WARNING: dial device not found")
    if donut_dev:
        print(f"Donut:    {donut_dev.name} ({donut_dev.path})")
    else:
        print("WARNING: donut button device not found")

    # LED backlight control (via vendor HID interface)
    led = LedController()
    if led.open():
        print(f"LED:      {led.path} (mode={led.mode})")
    else:
        print("WARNING: LED control not available (device may be in wireless mode)")

    run(key_dev, dial_dev, donut_dev, config, dry_run=args.dry_run, led=led)


if __name__ == "__main__":
    main()
