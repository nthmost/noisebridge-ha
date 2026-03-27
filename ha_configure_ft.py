#!/usr/bin/env python3
"""
ha_configure_ft.py — Add FlaschenTaschen integration to Home Assistant

Creates:
  1. Automation: display open/close messages on FT when Noisebridge status changes
  2. Prints rest_command YAML to paste into HA configuration.yaml
  3. Prints dashboard card YAML for the image upload page

Requires ft_bridge.py running on beyla (systemd: ft-bridge.service, port 8877).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

# Load HA config from .ha_env
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

HA_TOKEN = ha_config.get("HA_TOKEN", "")
REST_URL = ha_config.get("HA_URL", "http://homeassistant.local:8123")
FT_BRIDGE_URL = "http://beyla.noise:8877"

if not HA_TOKEN:
    print("No HA_TOKEN found in .ha_env", file=sys.stderr)
    sys.exit(1)


def rest_request(method, path, data=None):
    req = urllib.request.Request(
        f"{REST_URL}{path}",
        data=json.dumps(data).encode() if data else None,
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
        method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            return {"status": resp.status, "body": json.loads(body) if body else None, "ok": True}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"status": e.code, "error": body[:1000], "ok": False}
    except Exception as e:
        return {"error": str(e), "ok": False}


def main():
    # =============================================
    # STEP 1: Create FT open/close automation
    # =============================================
    print("=" * 60)
    print("STEP 1: Creating FlaschenTaschen open/close automation")
    print("=" * 60)

    auto_id = str(int(time.time() * 1000))

    # Base64-encoded mooninites.png (45x35)
    mooninites_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAC0AAAAjCAIAAACPchS9AAABI0lEQVR4nO2WMRKCMBBFfxyPYAOF"
        "tTUeQ47jMTwOHkNqa4rYeIdY6DAhu0kWCJiCNxTJGsIz+UGBjRxRg54W31cm9tglnm8qQw/ht0y9"
        "GMTjf/AepjCmMOHKGh4AlFLRCvSYaAfhpo7S50MPuzPIOx/rs/d+0pJKtaDHpHz0yJKhqwZA2dYC"
        "j2mxF3h8JX7D/SpqioT4gNgSYZV553akRECF5JTGcwbF4wLgdb47bQo5t5XgCuIsg/0WttvuMDJN"
        "5DFAZF9828FMY23QIvmwVdr3s29XhxMrsZQHtRnczeV0QQ8AzfHmVOruyo70v9dTYG/Ej44fmcvv"
        "HPEoSZdWZLD58IUm2/VIR38uyra222t7jIJ4RM9toj/GMY90jMrpxkaIDxSxTd8AiCn2AAAAAElF"
        "TkSuQmCC"
    )

    ft_automation = {
        "id": auto_id,
        "alias": "FlaschenTaschen Open/Close Display",
        "description": "Show Mooninites on FT when Noisebridge opens (5 min), clear on close.",
        "triggers": [
            {
                "trigger": "state",
                "entity_id": "sensor.noisebridge_open_status",
                "to": "open",
                "id": "opened"
            },
            {
                "trigger": "state",
                "entity_id": "sensor.noisebridge_open_status",
                "to": "closed",
                "id": "closed"
            }
        ],
        "conditions": [],
        "actions": [
            {
                "choose": [
                    {
                        "conditions": [{"condition": "trigger", "id": "opened"}],
                        "sequence": [
                            # Wait for FT to boot after plug powers on
                            {"delay": {"seconds": 15}},
                            {
                                "action": "rest_command.ft_image",
                                "data": {
                                    "image": mooninites_b64,
                                    "layer": 0,
                                    "duration": 300
                                }
                            },
                            {
                                "action": "rest_command.litebrite_set_text",
                                "data": {
                                    "message": "HACK teh PLANET!!!!111one",
                                    "color": "rainbow",
                                    "scrolling": "true"
                                }
                            }
                        ]
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": "closed"}],
                        "sequence": [
                            {
                                "action": "rest_command.ft_clear",
                                "data": {"layer": 0}
                            }
                        ]
                    }
                ]
            }
        ],
        "mode": "single"
    }

    print(f"\nAutomation config:\n{json.dumps(ft_automation, indent=2)}")

    result = rest_request("POST", f"/api/config/automation/config/{auto_id}", ft_automation)
    print(f"\nResult: {json.dumps(result, indent=2)[:500]}")

    if result.get("ok"):
        print(f"\nSUCCESS: FlaschenTaschen automation created (id={auto_id})")
    else:
        print("\nFAILED to create automation.")

    print("\nReloading automations...")
    reload_req = urllib.request.Request(
        f"{REST_URL}/api/services/automation/reload",
        data=b'{}',
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(reload_req, timeout=15)
        print("  Reload: OK")
    except Exception as e:
        print(f"  Reload: {e}")

    # =============================================
    # STEP 2: Print rest_command YAML
    # =============================================
    print("\n" + "=" * 60)
    print("STEP 2: rest_command YAML for configuration.yaml")
    print("=" * 60)
    print("""
Add the following to your HA configuration.yaml (SSH to HA Pi, port 2222):

rest_command:
  ft_display:
    url: "{url}/display"
    method: POST
    content_type: "application/json"
    payload: >-
      {{"text": "{{{{ text }}}}", "layer": {{{{ layer|default(2) }}}},
       "r": {{{{ r|default(255) }}}}, "g": {{{{ g|default(255) }}}},
       "b": {{{{ b|default(255) }}}}, "duration": {{{{ duration|default(30) }}}}}}
  ft_image:
    url: "{url}/image"
    method: POST
    content_type: "application/json"
    payload: >-
      {{"image": "{{{{ image }}}}", "layer": {{{{ layer|default(0) }}}},
       "duration": {{{{ duration|default(0) }}}}}}
  ft_clear:
    url: "{url}/clear"
    method: POST
    content_type: "application/json"
    payload: '{{"layer": {{{{ layer|default(2) }}}}}}'
""".format(url=FT_BRIDGE_URL))

    # =============================================
    # STEP 3: Print dashboard card YAML
    # =============================================
    print("=" * 60)
    print("STEP 3: Dashboard card YAML")
    print("=" * 60)
    print(f"""
Add this card to your HA dashboard (via UI: Edit Dashboard > Add Card > Manual):

type: iframe
url: "{FT_BRIDGE_URL}/"
aspect_ratio: "16:9"
title: FlaschenTaschen
""")

    # =============================================
    # Verify
    # =============================================
    print("=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    result = rest_request("GET", f"/api/config/automation/config/{auto_id}")
    if result.get("ok"):
        print(f"\nFT automation: EXISTS (id={auto_id})")
        print(f"  Alias: {result['body'].get('alias')}")
    else:
        print(f"\nFT automation: NOT FOUND")

    states = rest_request("GET", "/api/states")
    if states.get("ok"):
        autos = [s for s in states["body"] if s["entity_id"].startswith("automation.")]
        ft_autos = [a for a in autos if 'flaschen' in a['attributes'].get('friendly_name', '').lower()]
        if ft_autos:
            for a in ft_autos:
                print(f"  {a['entity_id']}: {a['attributes'].get('friendly_name')} (state={a['state']})")
        else:
            print("  No FT automations found in states yet (may need a moment to register)")

    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print(f"""
1. SSH to HA and add rest_commands to configuration.yaml:
     ssh -p 2222 hassio@homeassistant.local
     vi /config/configuration.yaml

2. Restart HA or reload rest_commands:
     Developer Tools > YAML > REST commands > Reload

3. Add the iframe dashboard card:
     Dashboard > Edit > Add Card > Manual > paste the YAML above

4. Make sure ft_bridge.service is running on beyla:
     sudo systemctl status ft-bridge
""")

    print("ALL DONE")


main()
