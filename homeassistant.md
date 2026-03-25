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
2. **Poller:** `noisebridge_status_updater.py` polls the upstream API every 5 min (via cron) and updates HA entity `sensor.noisebridge_open_status`
3. **Automation:** Triggered by **state change** on `sensor.noisebridge_open_status`
   - When sensor changes to `open` → turns ON the Open/Close switches
   - When sensor changes to `closed` → turns OFF the Open/Close switches
   - **Retry logic:** Repeats up to 5 times (2 min apart) until all switches match the target state. Handles Tuya cloud / WiFi flakiness.
   - **Mode: restart** — if status changes again mid-retry, the loop restarts with the new target
   - Manual overrides are respected: retries only happen during the ~10 min window after a transition
4. **Status server:** `noisebridge_status_server.py` runs on port 8099, exposing the HA sensor state over HTTP (no auth required)
5. **Lights dashboard:** `nblights.py` runs on port 8098, showing switch states at `/nblights`

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
