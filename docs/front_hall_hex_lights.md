# Front Hall Hexagon Lights — Home Assistant Setup

**Panels:** Gneng RGB Hexagon Lights (Amazon B0FB9B8NFX; OEM Gonenglighting)
**Controller:** BanlanX **SP648E**, BLE MAC **`A9:09:5A:36:09:6F`** — WiFi+BLE SPI addressable controller

> **Range finding (verified):** HA's built-in Bluetooth (Pi adapter
> `D8:3A:DD:F8:55:FD`) hears the SP648E at only **RSSI -95 dBm, ~1 ad/25s** —
> noise floor, unusable for a GATT control connection. **An ESP32 Bluetooth
> proxy near the front hall is REQUIRED, not optional.** Re-verify range any
> time with `~/projects/sysadmin/ha-bt-scan.py` (sources HA env; prints every
> BLE device HA hears with RSSI + which scanner saw it). Goal after proxy:
> SP648E seen via the proxy's MAC at roughly -55..-75 dBm.
 - 5–24 V, supports WS2811/WS2812/WS2815/SK6812, up to 1200 pixels
 - Music modes: on-board mic, phone mic, audio stream
 - Stock apps/remote: "BanlanX" app, RA3 RF remote (not needed once on HA)

## Building topology & the two-proxy plan

Old car-repair-shop building, RF-hostile (steel everywhere):

- **RNA Lounge** (upstairs): HA Pi / Mary Poppins rack, SwitchBot **Neon Wire
  Rope Light A2** (`90:E5:B1:2D:BD:A2`), **Floor Lamp FA12**
  (`90:E5:B1:31:FA:12`). See `reference_switchbot_devices.md` in sysadmin memory.
- **Front Hall** (downstairs, via a long metal staircase): SP648E hex panels +
  the (unrelated) Broadlink IR blaster.

BLE cannot cross the floors, and the Pi's onboard BT is useless from inside the
metal rack. **Plan: two ESP32 ESPHome Bluetooth proxies**, one per floor:

| Proxy | Place | Serves |
|-------|-------|--------|
| Lounge proxy | RNA Lounge, out of the rack, near the rope light | Rope Light A2 (active-scan discovery + control), FA12 reliability |
| Front Hall proxy | Front hall, line-of-sight to hex panels | SP648E via UniLED |

Use external-antenna ESP32 (WROOM-32**U** + IPEX) for the metal environment;
confirm WiFi at each spot; flash the official **connectable/active** proxy
build (active scanning is what unblocks SwitchBot discovery). HA auto-selects
the best scanner per device, so the weak Pi adapter is harmlessly superseded.

The runbook below covers the **Front Hall proxy / hex panels**; the Lounge
proxy + rope light follow the standard SwitchBot config flow once that proxy
is up (Add Integration → SwitchBot → pick `90:E5:B1:2D:BD:A2` → sign into the
SwitchBot account for the key, same as FA12).

## Approach: UniLED (no hardware modification)

The SP648E is already a capable addressable + music controller. Home Assistant
controls it via the **UniLED** HACS custom integration over Bluetooth LE.
No soldering, no controller replacement, music sync is built in.

### Runbook (ordered; [you] = HA UI / physical, [me] = via API/SSH)

Prereq: ESP32 flashed with the official **connectable** ESPHome Bluetooth
Proxy (`esphome.github.io/bluetooth-proxies`), powered on USB, placed
line-of-sight to the panels in the front hall.

1. **[you]** Adopt the proxy: HA pops an ESPHome discovery notification →
   Settings → Devices & Services → Configure it.
2. **[me]** Verify range: re-run `~/projects/sysadmin/ha-bt-scan.py`.
   GATE — must see `SP648E` (`A9:09:5A:36:09:6F`) via the *proxy's* MAC at
   ~ -55..-75 dBm with many ads/scan. If weak, reposition proxy & re-scan.
   Do not proceed until green.
3. **[you]** Free the SP648E from the BanlanX app (force-close / forget
   device) — single BLE connection only.
4. **[you]** Install UniLED: HACS → ⋮ → Custom repositories →
   `https://github.com/monty68/uniled` (Integration) → Install → restart HA.
5. **[you]** Add integration: Settings → Devices & Services → Add
   Integration → **UniLED** (or confirm the auto-discovered device).
6. **[me+you]** Live test: I drive the new light entity from the API
   (on/off, brightness, color, effect); you confirm panels react, colors
   correct, all hexes lit.
7. **[me]** HA wiring: rename + Front Hall area; scenes/presets;
   automations (Noisebell open/close group, sunset/sunrise schedule like the
   hallway deco lights); optional Google/Alexa exposure.
8. **[me+you]** Music sync: trigger SP648E onboard-mic music mode via
   UniLED's effect/mode select; make it a scene/automation; test with audio.

### Caveats / notes

- **Proxy needs good WiFi too** — it bridges BLE↔WiFi; verify front-hall WiFi
  signal when placing it, or the bottleneck just moves.
- Use the **connectable/active** proxy build (installer default) — UniLED
  makes real GATT connections *through* it, not just passive scans.
- Single BLE connection: once HA owns it, the BanlanX app can't connect
  simultaneously (expected).
- The Broadlink "Front Hall IR Blaster" (RM4 mini) is unrelated and CANNOT
  control these panels — wrong signal type. See sysadmin memory
  `reference_ir_blaster.md`.
- Earlier "gut it and rebuild with WLED" idea was dropped — UniLED is strictly
  less work and keeps stock hardware + music features.
