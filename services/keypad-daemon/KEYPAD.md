# TISHLED Gasket Creamy Mechanical Numpad

Product: https://www.amazon.com/TISHLED-Mechanical-Programmable-Bluetooth-Rechargeable/dp/B0D7QG2X6F/

## Connection

- 2.4GHz wireless via USB dongle
- USB ID: `3151:5026`
- Device name: `2.4G Wireless Keyboard`
- Also supports Bluetooth (donut buttons switch devices)
- Power switch on bottom of unit

## Physical Layout

```
┌───────┬───────┬───────┬───────┐
│ Bksp  │  Fn   │       │ DIAL  │
│       │(hw)   │       │(knob) │
├───────┼───────┼───────┼───────┤
│ Num   │   /   │   *   │   -   │
├───────┼───────┼───────┼───────┤
│   7   │   8   │   9   │       │
├───────┼───────┼───────┤   +   │
│   4   │   5   │   6   │       │
├───────┼───────┼───────┼───────┤
│   1   │   2   │   3   │       │
├───────┤       ├───────┤ Enter │
│   0   │       │   .   │       │
└───────┴───────┴───────┴───────┘
```

## Linux Input Devices

The keypad creates 6 event devices. Event numbers are NOT stable across
reconnections — use the detection method below.

| Device              | Detection                        | Inputs                        |
|---------------------|----------------------------------|-------------------------------|
| Primary keyboard    | Has `EV_LED` capability          | KP0-KP9, operators, NumLock, Backspace |
| Consumer Control    | "Consumer Control" in name       | Dial CW (`KEY_VOLUMEUP`), Dial CCW (`KEY_VOLUMEDOWN`) |
| Secondary keyboard  | `EV_KEY` without `EV_LED`, not Mouse/SysCtrl/Consumer | Backspace (from donut/Bksp button — same scancode, different device) |
| Mouse               | "Mouse" in name                  | Has `REL_WHEEL` but unused by keypad |
| System Control      | "System Control" in name         | Unused |
| Misc                | No `EV_KEY`, only `EV_ABS`       | Unused |

## Capturable Inputs (19 keys + dial)

| Input        | Event Device       | Key Code          |
|--------------|--------------------|--------------------|
| 0-9          | Primary keyboard   | `KEY_KP0` - `KEY_KP9` |
| Num Lock     | Primary keyboard   | `KEY_NUMLOCK`      |
| /            | Primary keyboard   | `KEY_KPSLASH`      |
| *            | Primary keyboard   | `KEY_KPASTERISK`   |
| -            | Primary keyboard   | `KEY_KPMINUS`      |
| +            | Primary keyboard   | `KEY_KPPLUS`       |
| .            | Primary keyboard   | `KEY_KPDOT`        |
| Enter        | Primary keyboard   | `KEY_KPENTER`      |
| Backspace    | Primary keyboard   | `KEY_BACKSPACE`    |
| Bksp/Donut   | Secondary keyboard | `KEY_BACKSPACE`    |
| Dial CW      | Consumer Control   | `KEY_VOLUMEUP`     |
| Dial CCW     | Consumer Control   | `KEY_VOLUMEDOWN`   |

## Non-capturable Inputs

| Input        | Reason                                           |
|--------------|--------------------------------------------------|
| Fn (top-right donut) | Hardware-only modifier, handled by keypad firmware. Produces no USB/HID output. |
| Dial click   | When combined with Fn, controls backlight mode. May or may not produce events on its own (untested without Fn held). |

## Backlight

- RGB with 18 built-in modes
- Auto-off after 2 minutes idle; any keypress wakes it
- **Fn + click knob**: enter brightness mode, then turn knob to adjust
- Fn + key combos cycle through backlight modes (see manual)
- Also configurable via TISHLED driver software (Windows)

## Files

- `keypad_test.py` — interactive test UI, shows all keys + dial on a grid
- `keypad_daemon.py` — maps keys/dial to Home Assistant webhooks
- `keypad_config.json` — webhook mappings (auto-generated on first run)
- `keypad-daemon.service` — systemd unit file

## Running

```bash
# Test all inputs
sudo ./keypad-venv/bin/python keypad_test.py

# Run daemon (dry run)
sudo ./keypad-venv/bin/python keypad_daemon.py --dry-run

# Run daemon (live)
sudo ./keypad-venv/bin/python keypad_daemon.py

# Install and enable systemd service
sudo cp keypad-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now keypad-daemon
```

## Permissions

User must be in the `input` group to access `/dev/input/event*` without sudo:

```bash
sudo usermod -aG input $USER
# Log out and back in for it to take effect
```
