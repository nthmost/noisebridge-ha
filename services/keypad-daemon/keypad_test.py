#!/usr/bin/env python3
"""
Keypad test — shows a live grid of all numpad keys, donut button, and dial.
Keys light up when pressed; the dial shows direction and cumulative position.
Run with: sudo ./keypad-venv/bin/python keypad_test.py
"""

import sys
import signal
import evdev
import select

DEVICE_NAME = "2.4G Wireless Keyboard"

# Layout matching a physical numpad (top to bottom, left to right)
# Top row: donut button + backspace
GRID = [
    ["KEY_BACKSPACE",  "DONUT",          None,             None],
    ["KEY_NUMLOCK",    "KEY_KPSLASH",    "KEY_KPASTERISK", "KEY_KPMINUS"],
    ["KEY_KP7",        "KEY_KP8",        "KEY_KP9",        "KEY_KPPLUS"],
    ["KEY_KP4",        "KEY_KP5",        "KEY_KP6",        None],
    ["KEY_KP1",        "KEY_KP2",        "KEY_KP3",        "KEY_KPENTER"],
    ["KEY_KP0",        None,             "KEY_KPDOT",      None],
]

LABELS = {
    "DONUT": "( )", "KEY_BACKSPACE": "Bksp",
    "KEY_NUMLOCK": "Num", "KEY_KPSLASH": "/", "KEY_KPASTERISK": "*", "KEY_KPMINUS": "-",
    "KEY_KP7": "7", "KEY_KP8": "8", "KEY_KP9": "9", "KEY_KPPLUS": "+",
    "KEY_KP4": "4", "KEY_KP5": "5", "KEY_KP6": "6",
    "KEY_KP1": "1", "KEY_KP2": "2", "KEY_KP3": "3", "KEY_KPENTER": "Ent",
    "KEY_KP0": "0", "KEY_KPDOT": ".",
}

ALL_KEYS = {k for row in GRID for k in row if k}

# Dial keys (on the Consumer Control device, event4)
DIAL_CW = "KEY_VOLUMEUP"
DIAL_CCW = "KEY_VOLUMEDOWN"

# Track state
pressed = {k: False for k in ALL_KEYS}
held = set()

dial_position = 0
dial_cw_seen = False
dial_ccw_seen = False
dial_last_dir = None  # "CW" or "CCW"
DIAL_BAR_WIDTH = 20


def find_devices():
    """Return (key_device, dial_device, donut_device) for the keypad.

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
        if DEVICE_NAME.lower() not in dev.name.lower():
            continue
        caps = dev.capabilities()

        # Consumer Control → dial device
        if "Consumer Control" in dev.name:
            dial_dev = dev
            continue

        # Skip non-keyboard devices (mouse, system control, etc.)
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


def render():
    """Draw the keypad grid and dial indicator to the terminal."""
    sys.stdout.write("\033[H\033[J")  # clear screen

    total = len(ALL_KEYS)
    done = sum(1 for v in pressed.values() if v)

    sys.stdout.write(f"  KEYPAD TEST — press every key ({done}/{total})\n")
    sys.stdout.write(f"  Ctrl+C to quit\n\n")

    for row in GRID:
        line = "  "
        for key in row:
            if key is None:
                line += "       "
                continue
            label = LABELS.get(key, key)
            if key in held:
                cell = f"\033[97;44m {label:^5} \033[0m"
            elif pressed[key]:
                cell = f"\033[30;42m {label:^5} \033[0m"
            else:
                cell = f"\033[90m [{label:^3}] \033[0m"
            line += cell
        sys.stdout.write(line + "\n")

    # Dial section
    sys.stdout.write(f"\n  {'─' * 30}\n")
    sys.stdout.write(f"  DIAL\n\n")

    # Direction indicator
    if dial_last_dir == "CW":
        arrow = f"\033[96;1m  ──▶ CW  (position: {dial_position})\033[0m"
    elif dial_last_dir == "CCW":
        arrow = f"\033[95;1m  ◀──  CCW (position: {dial_position})\033[0m"
    else:
        arrow = f"\033[90m  ···  waiting (position: {dial_position})\033[0m"
    sys.stdout.write(f"{arrow}\n\n")

    # Visual bar: center is middle, position moves the marker
    center = DIAL_BAR_WIDTH // 2
    clamped = max(-center, min(center, dial_position))
    bar = list("─" * DIAL_BAR_WIDTH)
    marker_pos = center + clamped
    marker_pos = max(0, min(DIAL_BAR_WIDTH - 1, marker_pos))
    bar[center] = "│"
    bar[marker_pos] = "●"
    bar_str = "".join(bar)
    sys.stdout.write(f"  CCW [{bar_str}] CW\n")

    # Status of dial directions
    cw_status = "\033[30;42m  CW  \033[0m" if dial_cw_seen else "\033[90m [ CW] \033[0m"
    ccw_status = "\033[30;42m CCW  \033[0m" if dial_ccw_seen else "\033[90m [CCW] \033[0m"
    sys.stdout.write(f"\n  {ccw_status} {cw_status}\n")

    # All-done check
    all_keys_done = all(pressed.values())
    dial_done = dial_cw_seen and dial_ccw_seen
    if all_keys_done and dial_done:
        sys.stdout.write(f"\n  \033[32;1m*** ALL INPUTS CONFIRMED ***\033[0m\n")
    else:
        missing = []
        if not all_keys_done:
            missing.append(f"{total - done} keys")
        if not dial_done:
            dirs = []
            if not dial_cw_seen: dirs.append("CW")
            if not dial_ccw_seen: dirs.append("CCW")
            missing.append(f"dial ({', '.join(dirs)})")
        sys.stdout.write(f"\n  \033[33mRemaining: {', '.join(missing)}\033[0m\n")

    sys.stdout.flush()


def main():
    global dial_position, dial_cw_seen, dial_ccw_seen, dial_last_dir

    key_dev, dial_dev, donut_dev = find_devices()

    if not key_dev:
        print(f"Could not find keyboard device matching '{DEVICE_NAME}'")
        sys.exit(1)

    print(f"Keyboard: {key_dev.name} ({key_dev.path})")
    if dial_dev:
        print(f"Dial:     {dial_dev.name} ({dial_dev.path})")
    else:
        print("WARNING: Could not find dial device (Consumer Control)")
    if donut_dev:
        print(f"Donut:    {donut_dev.name} ({donut_dev.path})")
    else:
        print("WARNING: Could not find donut button device")

    grabbed = []
    for dev in [key_dev, dial_dev, donut_dev]:
        if dev and dev.path not in [d.path for d in grabbed]:
            dev.grab()
            grabbed.append(dev)

    def cleanup(signum=None, frame=None):
        for dev in grabbed:
            dev.ungrab()
        sys.stdout.write("\033[?25h")  # show cursor
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Build fd -> device map for select
    watch_fds = {}
    for dev in grabbed:
        watch_fds[dev.fd] = dev

    # Track which fd is the donut device
    donut_fd = donut_dev.fd if donut_dev else None

    sys.stdout.write("\033[?25l")  # hide cursor
    render()

    while True:
        r, _, _ = select.select(list(watch_fds.keys()), [], [], 0.1)
        if not r:
            continue

        for fd in r:
            dev = watch_fds[fd]
            for event in dev.read():
                if event.type != evdev.ecodes.EV_KEY:
                    continue

                ke = evdev.categorize(event)
                key_name = ke.keycode
                if isinstance(key_name, list):
                    key_name = key_name[0]

                # Dial events
                if key_name == DIAL_CW and ke.keystate == evdev.KeyEvent.key_down:
                    dial_position += 1
                    dial_cw_seen = True
                    dial_last_dir = "CW"
                    render()
                    continue
                if key_name == DIAL_CCW and ke.keystate == evdev.KeyEvent.key_down:
                    dial_position -= 1
                    dial_ccw_seen = True
                    dial_last_dir = "CCW"
                    render()
                    continue

                # Donut button: KEY_BACKSPACE on the donut device (event8)
                if fd == donut_fd and key_name == "KEY_BACKSPACE":
                    if ke.keystate == evdev.KeyEvent.key_down:
                        pressed["DONUT"] = True
                        held.add("DONUT")
                        render()
                    elif ke.keystate == evdev.KeyEvent.key_up:
                        held.discard("DONUT")
                        render()
                    continue

                # Regular key events
                if key_name not in ALL_KEYS:
                    continue

                if ke.keystate == evdev.KeyEvent.key_down:
                    pressed[key_name] = True
                    held.add(key_name)
                    render()
                elif ke.keystate == evdev.KeyEvent.key_up:
                    held.discard(key_name)
                    render()


if __name__ == "__main__":
    main()
