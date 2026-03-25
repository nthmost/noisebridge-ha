# noisebridge-ha

Home Assistant configuration and scripts for Noisebridge hackerspace automation.

## Setup

1. Copy `.ha_env.example` to `.ha_env` and fill in your Home Assistant URL and long-lived access token.
2. Scripts look for `.ha_env` in the repo root by default. Override with the `HA_ENV_FILE` environment variable.

## Scripts

### ha_configure.py

Configures Home Assistant automations and switch groups via the REST API:
- Creates the **Open/Close** switch group (Flaschentaschen, Open sign, Beyla Lights)
- Updates the **Noisebell** automation (webhook-triggered open/close)
- Creates the **Hallway Deco Lights Schedule** automation (sunset on / sunrise off)

### noisebridge_status_updater.py

Polling daemon that fetches Noisebridge open/closed status from the upstream API (`noisebell.extremist.software`) and updates the `sensor.noisebridge_open_status` entity in Home Assistant.

Run via cron (e.g. every 5 minutes):
```
*/5 * * * * /usr/bin/python3 /path/to/noisebridge_status_updater.py >> /var/log/noisebridge_updater.log 2>&1
```

### noisebridge_status_server.py

Lightweight HTTP server (port 8099) that exposes the Noisebridge status from HA without authentication:
- `GET /` — full JSON status
- `GET /status` — plain text "open" or "closed"
- `GET /health` — health check

## Architecture

See [homeassistant.md](homeassistant.md) for full documentation of the HA instance, device mappings, automations, and data flow.
