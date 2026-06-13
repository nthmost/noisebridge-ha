# Hexagon at the front entrance

A hexagon-shaped SPI LED panel mounted at Noisebridge's front entrance, controlled via Home Assistant. This doc captures the architecture, how it works, how to operate it, and the gotchas to avoid if you ever need to redo this on similar hardware.

Built 2026-05-17/18 as a one-night project.

## What you see

- **In HA:** an entity `light.hexagon` in the `Front Entrance` area. Standard light controls (on/off, brightness, RGB color, effect dropdown with 17 named effects).
- **In the lights dashboard** (`http://10.21.0.43:8123/nb-lights/`, or as the **Lights** entry in HA's sidebar): a Hexagon panel with color presets, effect quick-picks, and a live color swatch.
- **On the wall:** the hexagon panel runs `Rainbow Meteor` whenever Noisebridge is **open**, and switches to `Comet Red` when **closed** (via the existing `noisebell` automation).

## The hardware

- **BanlanX SP648E** — a commodity BLE LED controller driving the hexagon panel's SPI LEDs. Identifies as device byte `0x33`, manufacturer ID `20563`, manufacturer data prefix `[0x33, 0x10]`. Family: `SP6xxE`. Speaks the Nordic-classic `0xffe0`/`0xffe1` GATT service/characteristic pair (plus an undocumented custom `5833ff01-...` service we didn't reverse-engineer).
- **Raspberry Pi Pico 2 W** (RP2350 + CYW43439) acts as the BLE↔WiFi↔MQTT bridge. Running MicroPython 1.28.0.
- **Single BLE connection limit:** the SP648E only accepts one BLE peer at a time. While the Pico holds the link, the BanlanX phone app can't reach it (and vice versa).

## Architecture

```
                   Noisebridge LAN
   ┌─────────────────────────────────────────────────┐
   │                                                  │
   │   ┌─────────────┐         ┌──────────────────┐  │
   │   │  Pico 2 W   │  WiFi   │  HA Pi 4         │  │
   │   │  10.21.1.x  ├────────►│  10.21.0.43:1883 │  │
   │   │             │  MQTT   │  Mosquitto       │  │
   │   └──┬──────────┘         │                  │  │
   │      │ BLE                │  light.hexagon   │  │
   │      ▼                    │  noisebell       │  │
   │   ┌─────────────┐         │  automation      │  │
   │   │ SP648E      │         └──────────────────┘  │
   │   │ (hexagon    │                               │
   │   │  panel)     │                               │
   │   └─────────────┘                               │
   │                                                  │
   └──────────────────────────────────────────────────┘
```

### Components

| Layer | Component | Repo / Location |
|------|----------|-----------------|
| Pico firmware | `sp648e-controller` (MicroPython app) | `~/projects/sp648e-controller/` (local Mac, not yet in git) |
| BanlanX protocol intel | mined from monty68/uniled | `~/projects/git/uniled/custom_components/uniled/lib/ble/banlanx_6xx.py` |
| MQTT broker | HA's Mosquitto add-on | HA Pi 4 (10.21.0.43:1883), one shared `wiresprite` account for all IoT bridges |
| HA entity + dashboards | `nb-lights` dashboard | this repo: `dashboards/lights.yaml` |
| HA automation | `noisebell` (open/close lights) | this repo: `config/automations.yaml` |

### Topic / endpoint reference

- **MQTT:**
  - Set: `sp648e/wiresprite_hexagon/set` (HA JSON light schema: `{"state":"ON","brightness":N,"color":{"r":N,"g":N,"b":N},"effect":"..."}`)
  - State: `sp648e/wiresprite_hexagon/state`
  - Availability: `sp648e/wiresprite_hexagon/availability`
  - HA discovery: `homeassistant/light/wiresprite_hexagon/config` (retained)
- **HTTP (on the Pico, port 8080, LAN-only):**
  - `GET /status` — wifi + BLE state
  - `GET /scan` — discovered GATT services/chars
  - `GET /effects` — list of named effects
  - `POST /power/on`, `/power/off`
  - `POST /brightness/<0-255>`
  - `POST /color/<r>/<g>/<b>[/<level>]`
  - `POST /effect/<URL-encoded name>`

## The MQTT account convention

All Noisebridge IoT bridges use a single shared HA user called **`wiresprite`** for their MQTT credentials. One account to rotate, one set of creds to deploy, naturally grouped under a single mental category. Per-device naming uses `wiresprite-<thing>` (e.g., `wiresprite_hexagon`) so topics and logs make the family obvious.

Full pattern doc: [iot-device-accounts.md](iot-device-accounts.md).

Credentials live in `~/.secrets/ha-noisebridge-mqtt.env` on the master Mac (gitignored, synced to relevant hosts via the systems rsync).

## SP648E protocol (what we ported)

The BanlanX SP6xxE family uses a simple 6-byte-header packet format on the `0xffe1` characteristic:

```
[0x53, cmd, 0x00, 0x01, 0x00, len(data), *data]
```

Commands we implemented (see `~/projects/sp648e-controller/pico/sp648e.py`):

| Cmd  | Function          | Payload                                  |
|------|-------------------|------------------------------------------|
| 0x02 | state query       | `[0x01]`                                 |
| 0x50 | power on/off      | `[0x01]` or `[0x00]`                     |
| 0x51 | brightness        | `[which, level]` — which=0x00 for color  |
| 0x52 | RGB (static mode) | `[r, g, b, level]`                       |
| 0x53 | mode + effect     | `[mode_byte, effect_byte]`               |
| 0x57 | RGB (dynamic mode)| `[r, g, b]` — no level                   |

The full uniled file lists ~224 effects across static / dynamic / sound / custom modes. We hand-picked 17 for the HA dropdown — rainbows, fire, comet/meteor variants, and the sound-reactive effects. Catalog lives in `pico/sp648e.py` as `EFFECTS = {...}`.

What we **didn't** port (all additive one-liners): effect speed (0x54), length (0x55), direction (0x56), audio sensitivity (0x5A), chip color order (0x6B), and the ~210 effects we left out of the curated list.

## Integrations

### Open/Close automation

The existing `noisebell` automation triggers on `sensor.noisebridge_open_status` transitioning between `open` and `closed`. We added the hexagon to both branches:

- **opened →** `light.turn_on light.hexagon effect: "Rainbow Meteor"`
- **closed →** `light.turn_on light.hexagon effect: "Comet Red"` (still ON — the hexagon is the first thing people see, so it stays visibly lit even when the space is closed)

The hexagon is idempotent under the existing retry-while loop (the loop re-fires all commands every 2 min until switches confirm their target state — the hexagon just re-receives the same effect).

## How to operate it

### Toggle / change color / change effect from the LAN

Via HA UI: `Lights` dashboard → Front Entrance tab. Color preset tiles set Solid Color; effect tiles set a dynamic mode.

Via MQTT one-liner:
```bash
source ~/.secrets/ha-noisebridge-mqtt.env
mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" \
  -t 'sp648e/wiresprite_hexagon/set' \
  -m '{"state":"ON","effect":"Rainbow"}'
```

Via HTTP (LAN-only, for ad-hoc curl):
```bash
curl -X POST http://<pico-ip>:8080/effect/Rainbow%20Meteor
curl -X POST http://<pico-ip>:8080/color/255/0/128
```

### Sub-conventions / standing rules

- **The hexagon should always be left ON** at the end of a working session. It's the first thing visitors see — visibly working/welcoming. (Captured as a memory rule on the Mac.)

### Iterate on the Pico code

Workflow that survives the USB-CDC pitfalls described below:

```bash
# 1. Edit local files
vim ~/projects/sp648e-controller/pico/sp648e.py

# 2. Stage on zikzak (Linux box with picotool + reliable USB)
scp ~/projects/sp648e-controller/pico/*.py zikzak:/tmp/sp648e-pico/

# 3. From zikzak, drop the Pico into REPL-only mode for safe pushing
ssh zikzak '~/.local/bin/mpremote touch :skip-main && \
            ~/.local/bin/mpremote exec "import machine; machine.soft_reset()"'

# 4. Push files
ssh zikzak 'cd /tmp/sp648e-pico && \
            for f in sp648e.py mqtt.py server.py main.py; do \
              ~/.local/bin/mpremote cp $f :$f; \
            done'

# 5. Re-enable autorun and reboot
ssh zikzak '~/.local/bin/mpremote rm :skip-main && \
            ~/.local/bin/mpremote exec "import machine; machine.soft_reset()"'
```

If something gets stuck (USB CDC dies, `mpremote` reports `no device found` even after replug): `sudo picotool erase -a` on zikzak with the Pico in BOOTSEL mode, then re-flash MicroPython UF2 via `sudo picotool load /tmp/RPI_PICO2_W-*.uf2 -f -x`, then re-push files. Takes ~5 minutes.

### Restart / power-cycle

- Hexagon BLE controller has no UI — power-cycle the strip itself by pulling its USB-C power.
- Pico autostarts the app on power-up (boot.py runs main.run() after a 1-second skip window).
- HA's last-will mechanism marks the Pico offline within 60s of disappearing; new connection re-publishes online + state.

## Architecture decisions worth remembering

- **MQTT > custom HA integration.** Writing a custom HA component would mean Python in HA's container, version-pinned to HA's lifecycle. MQTT discovery gives us HA-native UX with the protocol decoupled — the Pico can be re-flashed, replaced, or rewritten in Rust someday without touching HA.
- **Curated effect list, not all 224.** A dropdown with 224 entries is unusable; 17 covers the visual range and gives a useful HA dropdown.
- **Static-mode RGB (cmd 0x52) instead of dynamic-mode (cmd 0x57).** 0x52 includes the brightness byte in the same packet, so a "set color and brightness" operation is atomic. 0x57 would require a separate brightness call.
- **Single shared `wiresprite` MQTT account, not one-per-device.** Maintenance scales linearly with devices the wrong way otherwise.
- **The hexagon stays ON when closed, just turns red.** Visible signal that the space is closed without going dark in the front entrance.

## Gotchas (the painful ones)

- **`mpremote reset` (hard reset) kills USB CDC** on this firmware + our app pattern, every time. Once main.run() takes over after a hard reset, the host stops seeing `/dev/ttyACM*` until a full `picotool erase -a` + re-flash. Always use soft-reset (`mpremote exec "import machine; machine.soft_reset()"`) or the `skip-main` rescue file.
- **Don't drag UF2s via Finder on macOS for a flash-nuke + re-flash sequence.** macOS holds stale FAT mount handles between the two writes; the nuke disappears+reappears between writes but Finder/the kernel writes to the cached mount, not the new device. The second UF2 also goes to the stale cache and never reaches the Pico. Use `picotool` on a Linux host instead.
- **MicroPython's `bluetooth.UUID(0xffe0)` is NOT equal to `bluetooth.UUID("0000ffe0-0000-1000-8000-00805f9b34fb")`** even though they encode the same UUID on the wire. Always use the 16-bit integer form for short UUIDs.
- **aioble doesn't allow nested discovery iterators.** Collect services into a list first, then iterate characteristics on each service.
- **HA's MQTT discovery may not process a retained message published before the integration subscribed.** Reload the MQTT integration via REST API (`POST /api/config/config_entries/entry/<id>/reload`) to force a re-scan of all retained discovery topics.
- **HA preserves entity_id ↔ unique_id mapping forever** once it sees a unique_id. Renaming the device via discovery does NOT rename the entity_id. To get a fresh entity_id, change the `unique_id` AND clear the old retained discovery topic.
- **One Pico in this batch had a chip-level USB CDC fault** — BOOTSEL worked but MicroPython USB CDC never enumerated post-flash. Hardware lottery. Have a spare.
- **picotool isn't packaged for Ubuntu** — built from source on zikzak. Binary at `/usr/local/bin/picotool` (symlinked from `~/.local/picotool/picotool`); needs `sudo` (we didn't install the udev rules).

## Bug history — Pico used to publish spurious OFF on every MQTT reconnect

(Resolved 2026-05-18 with three commits in the Pico repo.)

The original `mqtt.py` published `{"state":"OFF"}` to the state topic on every MQTT (re)connect as a "known starting state," but actually flipped HA's view to OFF on every keepalive bounce. Observed firing every 45-90 seconds — matching the 60s default MQTT keepalive interval (the asyncio event loop was being starved past the timeout). 677 firings in ~18 hours during the affected period.

Resolved by three commits in [nthmost/sp648e-controller](https://github.com/nthmost/sp648e-controller):

- [dd7b7a7](https://github.com/nthmost/sp648e-controller/commit/dd7b7a7) — drop the baseline-OFF publish; if a `last_state` is known, republish that on reconnect, otherwise leave the topic alone (HA shows "unknown" briefly, which is honest)
- [8c59222](https://github.com/nthmost/sp648e-controller/commit/8c59222) — set `optimistic: True` in the HA discovery payload so HA treats its own commands as the source of truth and only weakly observes state-topic echoes
- [bfba1ad](https://github.com/nthmost/sp648e-controller/commit/bfba1ad) — bump MQTT keepalive 60s → 300s for margin against event-loop blips

A temporary `hexagon_state_watcher.service` on beyla bridged the gap between bug-discovery and Pico-redeploy by catching each spurious OFF and republishing the correct state directly to the state topic. Removed in [94debc6](https://github.com/nthmost/noisebridge-ha/commit/94debc6) once the Pico redeploy was validated.

## What's not done

- **OTA firmware updates** for the Pico (would let us iterate without USB)
- **Speed / length / direction** controls for effects (one-liners each, see uniled source)
- **Audio sensitivity** for sound-reactive effects
- **The other ~210 effects** we didn't include in the curated 17
- **Effect speed isn't exposed in HA's MQTT discovery** even though HA's MQTT JSON light schema would accept it

## References

- BanlanX SPxxxE protocol source: [monty68/uniled](https://github.com/monty68/uniled), specifically `custom_components/uniled/lib/ble/banlanx_6xx.py`
- HA MQTT JSON light schema: https://www.home-assistant.io/integrations/light.mqtt/#json-schema
- Pico erase tool: built from https://github.com/raspberrypi/picotool
- MicroPython UF2 for Pico 2 W: https://micropython.org/download/RPI_PICO2_W/
