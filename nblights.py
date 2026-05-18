#!/usr/bin/env python3
"""
Noisebridge Lights Dashboard — shows which HA-controlled lights are on or off.
Served at /nblights via Apache proxy, listens on port 8098.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

PORT = int(os.environ.get("NBLIGHTS_PORT", 8098))

# Load HA config
HA_ENV = os.environ.get("HA_ENV_FILE", os.path.join(os.path.dirname(__file__), ".ha_env"))
ha_config = {}
with open(HA_ENV) as f:
    for line in f:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line and not line.startswith("#") and not line.startswith("function"):
            key, _, val = line.partition("=")
            val = val.strip('"').strip("'")
            if val:
                ha_config[key] = val

HA_URL = ha_config.get("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = ha_config.get("HA_TOKEN", "")

if not HA_TOKEN:
    print("No HA_TOKEN found in .ha_env", file=sys.stderr)
    sys.exit(1)

# Entities to display: (entity_id, display_name, group, kind)
# kind = "switch" (binary on/off) or "light" (state + brightness + color/effect).
ENTITIES = [
    # Open/Close — track with the noisebell automation
    ("switch.rna_sw1_3rd_reality_zigbee",    "RNA SW1",            "Open/Close", "switch"),
    ("switch.rna_sw2_3rd_reality_zigbee",    "RNA SW2",            "Open/Close", "switch"),
    ("light.beyla_govee_light_bars",         "Govee Light Bars",   "Open/Close", "light"),
    ("light.rgbicww_floor_lamp_fa12",        "Floor Tube Lamp",    "Open/Close", "light"),

    # Front Entrance — the hexagon panel via the Pico BLE bridge
    ("light.hexagon",                        "Hexagon",            "Front Entrance", "light"),

    # Scheduled (sunset/sunrise)
    ("switch.mini_smart_plug_2_socket_1",    "Hallway Deco Lights", "Scheduled", "switch"),

    # Other / parked
    ("switch.flaschentaschen_socket_1",      "Flaschentaschen",    "Other", "switch"),
    ("switch.mini_smart_plug_5_socket_1",    "Mini Smart Plug 5",  "Other", "switch"),
]

OPEN_CLOSE_SWITCHES = [eid for eid, _, g, k in ENTITIES if g == "Open/Close" and k == "switch"]
NB_API = "https://noisebell.extremist.software/status"
SENSOR_STALE_MINUTES = 10
TRANSITION_GRACE_MINUTES = 15


def check_ha_health():
    """Compare upstream status, HA sensor, and switch states. Return health verdict."""
    now = datetime.now(timezone.utc)
    problems = []

    # 1. Fetch upstream Noisebridge status
    try:
        req = urllib.request.Request(NB_API)
        with urllib.request.urlopen(req, timeout=10) as resp:
            upstream = json.loads(resp.read())
        upstream_status = upstream["status"]  # "open" or "closed"
    except Exception as e:
        return {"status": "critical", "color": "red",
                "message": f"Upstream API unreachable: {e}"}

    # 2. Fetch HA sensor
    try:
        req = urllib.request.Request(
            f"{HA_URL}/api/states/sensor.noisebridge_open_status",
            headers={"Authorization": f"Bearer {HA_TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            sensor = json.loads(resp.read())
        sensor_status = sensor["state"]
        sensor_updated = sensor.get("last_updated", "")
    except Exception as e:
        return {"status": "critical", "color": "red",
                "message": f"HA unreachable: {e}"}

    # 3. Check sensor freshness
    if sensor_updated:
        try:
            updated_dt = datetime.fromisoformat(sensor_updated)
            age_min = (now - updated_dt).total_seconds() / 60
            if age_min > SENSOR_STALE_MINUTES:
                problems.append(f"sensor stale ({age_min:.0f}m old)")
        except Exception:
            pass

    # 4. Check sensor matches upstream
    if sensor_status != upstream_status:
        problems.append(f"sensor={sensor_status} but upstream={upstream_status}")

    # 5. Check switch states match sensor (only if no recent transition)
    try:
        sensor_changed = sensor.get("last_changed", "")
        if sensor_changed:
            changed_dt = datetime.fromisoformat(sensor_changed)
            since_change_min = (now - changed_dt).total_seconds() / 60
        else:
            since_change_min = 999

        if since_change_min > TRANSITION_GRACE_MINUTES:
            states = get_switch_states()
            expected = "on" if sensor_status == "open" else "off"
            mismatched = []
            for eid in OPEN_CLOSE_SWITCHES:
                info = states.get(eid, {})
                if info.get("state") not in (expected, "unavailable"):
                    mismatched.append(eid.split(".")[1])
            if mismatched:
                problems.append(f"switches wrong: {', '.join(mismatched)} should be {expected}")
    except Exception as e:
        problems.append(f"switch check failed: {e}")

    # Build result
    if not problems:
        return {"status": "ok", "color": "green",
                "message": f"HA healthy — {upstream_status}",
                "upstream": upstream_status, "sensor": sensor_status}

    severity = "critical" if any(
        "unreachable" in p or "stale" in p or "sensor=" in p for p in problems
    ) else "warning"
    color = "red" if severity == "critical" else "amber"

    return {"status": severity, "color": color,
            "message": "; ".join(problems),
            "upstream": upstream_status, "sensor": sensor_status}


def get_entity_states():
    """Fetch switch + light entity states from HA, including light attributes."""
    req = urllib.request.Request(
        f"{HA_URL}/api/states",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        all_states = json.loads(resp.read())

    state_map = {}
    for entity in all_states:
        eid = entity.get("entity_id", "")
        if not (eid.startswith("switch.") or eid.startswith("light.")):
            continue
        attrs = entity.get("attributes", {})
        state_map[eid] = {
            "state": entity.get("state", "unknown"),
            "friendly_name": attrs.get("friendly_name", eid),
            "last_changed": entity.get("last_changed", ""),
            "brightness": attrs.get("brightness"),       # 0-255 or None
            "rgb_color": attrs.get("rgb_color"),         # [r,g,b] or None
            "effect": attrs.get("effect"),               # string or None
        }
    return state_map


# Back-compat alias for /api/states callers that hit the old function name.
get_switch_states = get_entity_states


def render_dashboard(state_map):
    """Build the HTML dashboard."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    rows = []
    current_group = None
    for entity_id, name, group, kind in ENTITIES:
        if group != current_group:
            current_group = group
            rows.append(f'<tr class="group-header"><td colspan="3">{group}</td></tr>')

        info = state_map.get(entity_id, {})
        state = info.get("state", "unknown")
        last_changed = info.get("last_changed", "")
        if last_changed:
            # Trim microseconds for display
            last_changed = last_changed.replace("T", " ")[:19]

        # Indicator: lit dot, or for ON lights, a swatch of their actual color.
        if state == "on":
            row_class = "state-on"
            state_text = "ON"
            if kind == "light":
                rgb = info.get("rgb_color")
                if rgb:
                    swatch_color = f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"
                    indicator = f'<span class="led on" style="background:{swatch_color};box-shadow:0 0 8px {swatch_color}"></span>'
                else:
                    indicator = '<span class="led on"></span>'
            else:
                indicator = '<span class="led on"></span>'
        elif state == "off":
            indicator = '<span class="led off"></span>'
            state_text = "OFF"
            row_class = "state-off"
        else:
            indicator = '<span class="led unavailable"></span>'
            state_text = state.upper()
            row_class = "state-unavailable"

        # Extra detail line for lights that are ON
        detail = ""
        if kind == "light" and state == "on":
            bits = []
            brightness = info.get("brightness")
            if brightness is not None:
                bits.append(f"{int(brightness * 100 / 255)}%")
            effect = info.get("effect")
            if effect:
                bits.append(effect)
            if bits:
                detail = f'<div class="detail">{" &middot; ".join(bits)}</div>'

        rows.append(
            f'<tr class="{row_class}">'
            f'<td>{indicator} {name}{detail}</td>'
            f'<td class="state-cell">{state_text}</td>'
            f'<td class="time-cell">{last_changed}</td>'
            f'</tr>'
        )

    table_rows = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Noisebridge Lights</title>
<meta http-equiv="refresh" content="15">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Courier New', monospace;
    padding: 1.5rem;
    min-height: 100vh;
  }}
  h1 {{
    color: #00ff88;
    font-size: 1.4rem;
    margin-bottom: 0.3rem;
  }}
  .subtitle {{
    color: #666;
    font-size: 0.8rem;
    margin-bottom: 1.2rem;
  }}
  table {{
    width: 100%;
    max-width: 600px;
    border-collapse: collapse;
  }}
  tr.group-header td {{
    color: #888;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 0.8rem 0.4rem 0.3rem;
    border-bottom: 1px solid #333;
  }}
  td {{
    padding: 0.5rem 0.4rem;
    vertical-align: middle;
  }}
  .state-cell {{
    text-align: center;
    font-weight: bold;
    width: 60px;
  }}
  .time-cell {{
    color: #666;
    font-size: 0.75rem;
    text-align: right;
  }}
  .state-on .state-cell {{ color: #00ff88; }}
  .state-off .state-cell {{ color: #ff6b6b; }}
  .state-unavailable .state-cell {{ color: #666; }}
  .led {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 0.5rem;
    vertical-align: middle;
  }}
  .led.on {{
    background: #00ff88;
    box-shadow: 0 0 6px #00ff88;
  }}
  .led.off {{
    background: #ff6b6b;
    box-shadow: 0 0 4px #ff6b6b44;
  }}
  .led.unavailable {{
    background: #555;
  }}
  .detail {{
    color: #888;
    font-size: 0.7rem;
    margin-top: 0.15rem;
    padding-left: 1.3rem;
  }}
  .footer {{
    margin-top: 1.5rem;
    color: #555;
    font-size: 0.7rem;
  }}
</style>
</head>
<body>
<h1>Noisebridge Lights</h1>
<div class="subtitle">Auto-refreshes every 15s</div>
<table>
{table_rows}
</table>
<div class="footer">Updated {now} &middot; Source: Home Assistant @ homeassistant.local</div>
</body>
</html>"""


class LightsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path.rstrip("/") in ("", "/index.html"):
                states = get_entity_states()
                html = render_dashboard(states)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode())
            elif self.path == "/api/states":
                states = get_entity_states()
                result = []
                for entity_id, name, group, kind in ENTITIES:
                    info = states.get(entity_id, {})
                    row = {
                        "entity_id": entity_id,
                        "name": name,
                        "group": group,
                        "kind": kind,
                        "state": info.get("state", "unknown"),
                        "last_changed": info.get("last_changed", ""),
                    }
                    if kind == "light":
                        row["brightness"] = info.get("brightness")
                        row["rgb_color"] = info.get("rgb_color")
                        row["effect"] = info.get("effect")
                    result.append(row)
                self._json_respond(200, result)
            elif self.path == "/health/ha":
                result = check_ha_health()
                self._json_respond(200, result)
            elif self.path == "/health":
                self._json_respond(200, {"status": "ok"})
            else:
                self.send_error(404)
        except Exception as e:
            self._json_respond(502, {"error": str(e)})

    def _json_respond(self, code, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), LightsHandler)
    print(f"Noisebridge Lights dashboard listening on port {PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
