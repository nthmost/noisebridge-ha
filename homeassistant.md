# Home Assistant Setup — homeassistant.local

**Host:** homeassistant.local (10.21.0.43), port 8123
## Switch Groups

### Open/Close

Entities that respond to Noisebridge open/closed status (via Noisebell). All assigned to **RNA Lounge** area.

| Entity ID | Friendly Name | Notes |
|-----------|--------------|-------|
| `switch.rna_sw1_3rd_reality_zigbee` | RNA SW1 3rd Reality Zigbee | Zigbee switch |
| `switch.rna_sw2_3rd_reality_zigbee` | BEYLA RNA SW2 Zigbee | Zigbee switch |
| `light.beyla_govee_light_bars` | Beyla Govee Light Bars | Govee light |
| `light.rgbicww_floor_lamp_fa12` | Floor Tube Lamp | RGBICWW floor lamp |

## Automations

### Noisebell (`automation.noisebell`)

**Purpose:** When Noisebridge opens, turn on the Open/Close entities. When it closes, turn them off.

#### Data Flow

1. **Upstream API:** `https://noisebell.extremist.software/status` — returns `open`/`closed` status
2. **Poller:** `noisebridge_status_updater.py` polls the upstream API and updates HA entity `sensor.noisebridge_open_status`
3. **Automation:** Triggered by **state changes** on `sensor.noisebridge_open_status` (trigger IDs `opened` / `closed`). Mode `restart`. Wrapped in a repeat-while loop that retries up to 5 times with 2-minute delays until the switches reflect the target state — handles flaky Tuya/Zigbee delivery.
4. **Status server:** `noisebridge_status_server.py` runs on port 8099, exposing the HA sensor state over HTTP (no auth required)

### Hallway Deco Lights Schedule (`automation.hallway_deco_lights_schedule`)

**Purpose:** Keep hallway deco lights on during dark hours.

| Trigger | Action |
|---------|--------|
| Sunset | Turn ON `switch.mini_smart_plug_2_socket_1` (Hallway deco lights) |
| Sunrise | Turn OFF `switch.mini_smart_plug_2_socket_1` (Hallway deco lights) |

## LiteBrite LED Marquee

**Device:** LiteBrite LED sign at `http://10.21.0.80/`
**HA Service:** `rest_command.litebrite_set_text`

Sends text to the LED marquee sign on the local network.

| Parameter | Values | Default |
|-----------|--------|---------|
| `message` | Any string (max 32 chars) | *(required)* |
| `color` | `rainbow`, or hex (`#FF0000`, `#00FF00`, etc.) | `rainbow` |
| `scrolling` | `true` / `false` | `true` |

**Example service call:**
```yaml
service: rest_command.litebrite_set_text
data:
  message: "Hello Noisebridge"
  color: rainbow
  scrolling: "true"
```

## Other Devices

| Entity ID | Friendly Name | Notes |
|-----------|--------------|-------|
| `switch.mini_smart_plug_5_socket_1` | Mini Smart Plug 5 | Currently **unavailable** — not in any automation |
| `light.home_assistant_connect_zwa_2_led` | ZWave dongle LED | Not a room light |

## Known Issues / Notes

- The noisebell automation triggers on `sensor.noisebridge_open_status` state changes (the poller writes that sensor). The retry loop tolerates devices that miss the first command.
- `switch.mini_smart_plug_5_socket_1` is unavailable — may need reconnection or may control an additional light not yet in any automation.
- Open/Close group is a mix of `switch.*` (3rd Reality Zigbee) and `light.*` (Govee bars, RGBICWW floor lamp) entities; the automation calls the right service per entity type.
- `switch.flaschentaschen_socket_1` (Tuya) was **removed from the noisebell automation on 2026-05-16** — it was offline/unavailable and unused, and its stuck `unavailable` state was forcing the retry loop to run all 5 attempts (~10 min) on every open/close. Removed from the open `turn_on`, close `turn_off`, and the `while` condition. Backup: `/config/automations.yaml.bak-20260516-015040` on the HA Pi.
- SSH access to HA Pi: `ssh -p 2222 hassio@homeassistant.local` (Advanced SSH & Web Terminal addon, SFTP disabled, key auth).
