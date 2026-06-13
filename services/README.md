# services/

Long-running services that talk to Home Assistant, FlaschenTaschen, or the
Noisebridge installation. Each subdir is one service: script + systemd
unit + any companion config or docs, all co-located.

Currently deployed on `beyla.local` (at NB), but these are not
beyla-specific — anything in here can be redeployed on another host if
beyla is rebuilt or moved.

## Layout

| Service | What it does | Talks to |
|---|---|---|
| [ft-bridge/](ft-bridge/) | HTTP API for the FlaschenTaschen LED wall (text, images, animations, donation scrolls) | FT (`ft.noise`), HA |
| [ft-nowplaying/](ft-nowplaying/) | Renders KNOB now-playing info onto the FT wall | KNOB radio API, FT |
| [donation-alerts/](donation-alerts/) | Polls the donations source and triggers an FT scroll when one lands | ft-bridge HTTP, requires `DONATE_ALERTS_*` env |
| [keypad-daemon/](keypad-daemon/) | Reads a USB HID keypad and fires HA webhooks per key | HA, /dev/input — needs root |
| [nbha-proxy/](nbha-proxy/) | One-liner `socat` TCP forwarder bridging local 8124 → HA on the Pi (10.21.0.43:8123) | HA |

## Deployment expectations

The systemd unit files in each subdir reflect the paths they currently
run from on beyla — typically `/home/nthmost/projects/<service>/`. **If you redeploy
on another host (or move things on beyla), update the `ExecStart` paths
in the .service unit and copy the updated unit to `/etc/systemd/system/`,
then `systemctl daemon-reload && systemctl enable --now <service>`.**

Secrets are never in this repo:

- `donation-alerts` reads `~/.secrets/donate_alerts.env`. See
  [donation-alerts/.env.example](donation-alerts/.env.example) for the
  expected keys.

