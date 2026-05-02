# noisebridge-ha

Home Assistant configuration and scripts for Noisebridge hackerspace automation. HA runs on a **Raspberry Pi 4** (clear plastic case, Mary Poppins server rack). The scripts in this repo run on **beyla** (RNA Lounge server) and interact with HA over the local network.

## How It Works

```
noisebell.extremist.software    (upstream open/closed API)
        |
        v  (polled every 5 min by cron)
noisebridge_status_updater.py   (updates HA sensor)
        |
        v
sensor.noisebridge_open_status  (HA entity)
        |
        v  (state-change trigger)
noisebell automation            (HA automation with retry loop)
        |
        v
Smart switches                  (Flaschentaschen, RNA SW1, RNA SW2)
```

When Noisebridge opens or closes, the automation turns the Open/Close lights on or off. It retries up to 5 times over ~10 minutes to handle Tuya cloud drops and WiFi flakiness. Manual overrides are respected — retries only happen during the post-transition window.

A separate automation controls the **Hallway Deco Lights** on a sunset/sunrise schedule.

## Setup

1. Copy `.ha_env.example` to `.ha_env` and fill in your HA URL and long-lived access token.
2. Scripts look for `.ha_env` in the repo root by default. Override with `HA_ENV_FILE` env var.

## Scripts

### ha_configure.py

Pushes automation and switch group configs to HA via the REST API. Run this to set up or reset the HA automations:

- **Open/Close switch group** — Flaschentaschen, RNA SW1, RNA SW2
- **Noisebell automation** — state-triggered with retry loop (up to 5x, 2 min apart)
- **Hallway Deco Lights Schedule** — sunset on / sunrise off

### noisebridge_status_updater.py

Polls the Noisebridge status API and updates `sensor.noisebridge_open_status` in HA. Run via cron:

```
*/5 * * * * /usr/bin/python3 /home/nthmost/projects/noisebridge-ha/noisebridge_status_updater.py >> /var/log/noisebridge_updater.log 2>&1
```

### noisebridge_status_server.py

HTTP server (port 8099) exposing Noisebridge open/closed status from HA. No auth required.

| Endpoint | Response |
|----------|----------|
| `GET /` | Full JSON status |
| `GET /status` | Plain text `open` or `closed` |
| `GET /health` | Health check |

**systemd:** `noisebridge-status.service` (if configured)

### nblights.py

Lights dashboard showing real-time on/off state of all HA-controlled switches. Dark theme, auto-refreshes every 15s.

| Endpoint | Response |
|----------|----------|
| `GET /` | HTML dashboard |
| `GET /api/states` | JSON switch states |
| `GET /health` | Health check |

**systemd:** `nblights.service`
**Local URL:** http://beyla.local/nblights
**Public URL:** https://nthmost.com/nblights/

## Services on beyla

| Service | Port | Proxied at |
|---------|------|------------|
| `nblights.service` | 8098 | `/nblights` (Apache) |
| `noisebridge_status_server.py` | 8099 | — |

Apache config: `/etc/apache2/sites-enabled/mediawiki.conf`

Public access via nthmost.com is proxied over WireGuard from zephyr (10.100.0.1) to beyla (10.100.0.2). Config on zephyr: `/etc/apache2/sites-enabled/nthmost.com-le-ssl.conf`

## HA Automations

### Noisebell (`automation.noisebell`)

Syncs Open/Close lights with Noisebridge status.

- **Trigger:** `sensor.noisebridge_open_status` state change to `open` or `closed`
- **Action:** Turn on/off all Open/Close switches
- **Retry:** Up to 5 attempts, 2 min apart, until all switches match target state
- **Mode:** `restart` — new status change cancels pending retries

### Hallway Deco Lights Schedule (`automation.hallway_deco_lights_schedule`)

- **Trigger:** Sunset / Sunrise
- **Action:** Turn on/off `switch.mini_smart_plug_2_socket_1`

## Controlled Devices

| Entity ID | Name | Group |
|-----------|------|-------|
| `switch.flaschentaschen_socket_1` | Flaschentaschen | Open/Close |
| `switch.rna_sw1_3rd_reality_zigbee` | RNA SW1 | Open/Close |
| `switch.rna_sw2_3rd_reality_zigbee` | RNA SW2 | Open/Close |
| `switch.mini_smart_plug_2_socket_1` | Hallway Deco Lights | Scheduled |
| `switch.mini_smart_plug_5_socket_1` | Mini Smart Plug 5 | Unavailable |

See [homeassistant.md](homeassistant.md) for full device mappings and additional details.

## Config Backup

The `config/` directory holds snapshots of the live HA YAML files:
- `configuration.yaml` — sensors, rest_commands, input helpers
- `scripts.yaml` — FT and KNOB control scripts
- `automations.yaml` — open/close and scheduled automations
- `lovelace.noisebridge.json` — FT/KNOB/Zikzak control dashboard
- `lovelace.rooms.json` — Rooms navigation dashboard

### Running a Backup

```bash
./backup_ha_config.sh
```

Requires SSH access to HA via beyla (port 2222). See the script header for first-time SSH key setup instructions.
