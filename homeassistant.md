# Home Assistant Setup — homeassistant.local

**Host:** homeassistant.local (10.21.0.43), port 8123
**API Token:** stored in `.ha_env` (see `.ha_env.example`)

## Switch Groups

### Open/Close (`switch.open_close`)

Switches that respond to Noisebridge open/closed status (via Noisebell).

| Entity ID | Friendly Name | Notes |
|-----------|--------------|-------|
| `switch.flaschentaschen_socket_1` | Flaschentaschen | Tuya smart plug |
| `switch.salt_lamp_1_socket_1` | Open sign | Tuya smart plug |
| `switch.mini_smart_plug_socket_1` | Beyla Lights | Tuya smart plug |

All assigned to **RNA Lounge** area.

## Automations

### Noisebell (`automation.noisebell`)

**Purpose:** When Noisebridge opens, turn on the Open/Close group. When it closes, turn them off.

#### Data Flow

1. **Upstream API:** `https://noisebell.extremist.software/status` — returns `open`/`closed` status
2. **Poller:** `noisebridge_status_updater.py` polls the upstream API and updates HA entity `sensor.noisebridge_open_status`
3. **Automation:** Triggered by a **webhook** (POST to webhook ID `-roWWM0JVCWSispwyHXlcKtjI`), not by the sensor state change
   - When `trigger.json.status == 'open'` → turns ON the Open/Close switches
   - When `trigger.json.status == 'closed'` → turns OFF the Open/Close switches
4. **Status server:** `noisebridge_status_server.py` runs on port 8099, exposing the HA sensor state over HTTP (no auth required)

### Hallway Deco Lights Schedule (`automation.hallway_deco_lights_schedule`)

**Purpose:** Keep hallway deco lights on during dark hours.

| Trigger | Action |
|---------|--------|
| Sunset | Turn ON `switch.mini_smart_plug_2_socket_1` (Hallway deco lights) |
| Sunrise | Turn OFF `switch.mini_smart_plug_2_socket_1` (Hallway deco lights) |

## Other Devices

| Entity ID | Friendly Name | Notes |
|-----------|--------------|-------|
| `switch.mini_smart_plug_5_socket_1` | Mini Smart Plug 5 | Currently **unavailable** — not in any automation |
| `light.home_assistant_connect_zwa_2_led` | ZWave dongle LED | Not a room light |

## Known Issues / Notes

- The noisebell automation uses webhook triggers, not sensor state triggers. The poller or an external caller must POST to the webhook for the automation to fire.
- `switch.mini_smart_plug_5_socket_1` is unavailable — may need reconnection or may control an additional light not yet in any automation.
- All "lights" are actually switch entities (Tuya smart plugs powering physical lights), not HA `light.*` entities.
