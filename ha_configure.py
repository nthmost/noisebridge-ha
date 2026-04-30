#!/usr/bin/env python3
"""Configure Home Assistant: create switch group, update noisebell, create hallway automation."""

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

if not HA_TOKEN:
    print("No HA_TOKEN found in .ha_env", file=sys.stderr)
    sys.exit(1)

# Device ID mappings (from entity registry):
# switch.flaschentaschen_socket_1       -> 87822c34b0c75a6e0bc00ac9b26ef18a
# switch.rna_sw1_3rd_reality_zigbee     -> 25f2ca03cd285dab3540f0d33c628852
# switch.rna_sw2_3rd_reality_zigbee     -> f18d7feee419c55ba6d6fb8c3626efbb
# switch.mini_smart_plug_2_socket_1     -> e00af537f194621eb3ecb69acfeffd90

OPEN_CLOSE_DEVICE_IDS = {
    "switch.flaschentaschen_socket_1": "87822c34b0c75a6e0bc00ac9b26ef18a",
    "switch.rna_sw1_3rd_reality_zigbee": "25f2ca03cd285dab3540f0d33c628852",
    "switch.rna_sw2_3rd_reality_zigbee": "f18d7feee419c55ba6d6fb8c3626efbb",
}

HALLWAY_DEVICE_ID = "e00af537f194621eb3ecb69acfeffd90"  # mini_smart_plug_2_socket_1


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


def call_service(domain, service, data=None, target=None):
    payload = {}
    if data:
        payload.update(data)
    if target:
        payload["target"] = target
    return rest_request("POST", f"/api/services/{domain}/{service}", payload if payload else {})


def main():
    # =============================================
    # STEP 1: Create "Open/Close" switch group
    # =============================================
    print("=" * 60)
    print("STEP 1: Creating 'Open/Close' switch group")
    print("=" * 60)

    open_close_entities = [
        "switch.flaschentaschen_socket_1",
        "switch.salt_lamp_1_socket_1",
        "switch.mini_smart_plug_socket_1"
    ]

    print("\nAttempt 1: POST /api/config/config_entries/flow")
    result = rest_request("POST", "/api/config/config_entries/flow", {
        "handler": "group",
        "show_advanced_options": False,
    })
    print(f"  Result: {json.dumps(result, indent=2)[:500]}")

    if result.get("ok"):
        flow_id = result["body"].get("flow_id")
        if flow_id:
            print(f"  Flow started: {flow_id}")
            body = result["body"]
            print(f"  Step type: {body.get('type')}, step_id: {body.get('step_id')}")
            print(f"  Schema: {json.dumps(body.get('data_schema', []), indent=2)[:500]}")

            result2 = rest_request("POST", f"/api/config/config_entries/flow/{flow_id}", {
                "group_type": "switch"
            })
            print(f"\n  Step 2 result: {json.dumps(result2, indent=2)[:800]}")

            if result2.get("ok"):
                body2 = result2["body"]
                flow_id2 = body2.get("flow_id", flow_id)
                step_id = body2.get("step_id")
                print(f"  Step: {step_id}")

                if body2.get("type") == "form":
                    result3 = rest_request("POST", f"/api/config/config_entries/flow/{flow_id2}", {
                        "name": "Open/Close",
                        "entities": open_close_entities,
                        "hide_members": False,
                        "all": False,
                    })
                    print(f"\n  Step 3 result: {json.dumps(result3, indent=2)[:800]}")
                    if result3.get("ok") and result3["body"].get("type") == "create_entry":
                        print("\n  SUCCESS: Switch group 'Open/Close' created!")
                    else:
                        print(f"\n  Step 3 may have failed, checking...")
                elif body2.get("type") == "create_entry":
                    print("\n  SUCCESS: Switch group created at step 2!")
    else:
        print(f"  Failed. Trying alternative...")

    # =============================================
    # STEP 2: Update noisebell automation
    # =============================================
    print("\n" + "=" * 60)
    print("STEP 2: Updating noisebell automation")
    print("=" * 60)

    open_close_entities = list(OPEN_CLOSE_DEVICE_IDS.keys())

    updated_config = {
        "id": "1774327685706",
        "alias": "noisebell",
        "description": "Sync Open/Close lights with Noisebridge open/closed status. Retries up to 5 times over ~10 min to handle Tuya cloud/WiFi flakiness.",
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
                "repeat": {
                    "while": [
                        {
                            "condition": "template",
                            "value_template": "{{ repeat.index <= 5 }}"
                        },
                        {
                            "condition": "template",
                            "value_template": (
                                "{% set target = 'on' if trigger.id == 'opened' else 'off' %}"
                                "{{ not ("
                                "states('switch.flaschentaschen_socket_1') == target and "
                                "states('switch.rna_sw1_3rd_reality_zigbee') == target and "
                                "states('switch.rna_sw2_3rd_reality_zigbee') == target"
                                ") }}"
                            )
                        }
                    ],
                    "sequence": [
                        {
                            "choose": [
                                {
                                    "conditions": [{"condition": "trigger", "id": "opened"}],
                                    "sequence": [
                                        {
                                            "action": "switch.turn_on",
                                            "target": {"entity_id": open_close_entities}
                                        }
                                    ]
                                },
                                {
                                    "conditions": [{"condition": "trigger", "id": "closed"}],
                                    "sequence": [
                                        {
                                            "action": "switch.turn_off",
                                            "target": {"entity_id": open_close_entities}
                                        }
                                    ]
                                }
                            ]
                        },
                        {"delay": {"minutes": 2}}
                    ]
                }
            }
        ],
        "mode": "restart"
    }

    print(f"\nUpdated config:\n{json.dumps(updated_config, indent=2)}")

    result = rest_request("POST", "/api/config/automation/config/1774327685706", updated_config)
    print(f"\nResult: {json.dumps(result, indent=2)[:500]}")

    if result.get("ok"):
        print("SUCCESS: Noisebell automation updated!")
        print("  - State-triggered on sensor.noisebridge_open_status")
        print("  - Retry loop: up to 5 attempts, 2 min apart")
        print("  - Mode: restart (new status change cancels pending retries)")
    else:
        print("FAILED to update noisebell automation.")

    print("\nReloading automations...")
    reload_result = call_service("automation", "reload")
    print(f"  Reload: {json.dumps(reload_result, indent=2)[:200]}")

    # =============================================
    # STEP 3: Create Hallway Deco Lights Schedule
    # =============================================
    print("\n" + "=" * 60)
    print("STEP 3: Creating 'Hallway Deco Lights Schedule' automation")
    print("=" * 60)

    new_auto_id = str(int(time.time() * 1000))

    hallway_config = {
        "id": new_auto_id,
        "alias": "Hallway Deco Lights Schedule",
        "description": "Turns hallway deco lights on at sunset and off at sunrise",
        "triggers": [
            {
                "trigger": "sun",
                "event": "sunset",
                "id": "sunset"
            },
            {
                "trigger": "sun",
                "event": "sunrise",
                "id": "sunrise"
            }
        ],
        "conditions": [],
        "actions": [
            {
                "choose": [
                    {
                        "conditions": [
                            {
                                "condition": "trigger",
                                "id": "sunset"
                            }
                        ],
                        "sequence": [
                            {
                                "action": "switch.turn_on",
                                "target": {
                                    "device_id": HALLWAY_DEVICE_ID
                                }
                            }
                        ]
                    },
                    {
                        "conditions": [
                            {
                                "condition": "trigger",
                                "id": "sunrise"
                            }
                        ],
                        "sequence": [
                            {
                                "action": "switch.turn_off",
                                "target": {
                                    "device_id": HALLWAY_DEVICE_ID
                                }
                            }
                        ]
                    }
                ]
            }
        ],
        "mode": "single"
    }

    print(f"\nNew automation config:\n{json.dumps(hallway_config, indent=2)}")

    result = rest_request("POST", f"/api/config/automation/config/{new_auto_id}", hallway_config)
    print(f"\nResult: {json.dumps(result, indent=2)[:500]}")

    if result.get("ok"):
        print("SUCCESS: 'Hallway Deco Lights Schedule' automation created!")
    else:
        print("FAILED to create hallway automation.")

    print("\nReloading automations...")
    reload_result = call_service("automation", "reload")
    print(f"  Reload: {json.dumps(reload_result, indent=2)[:200]}")

    # Verify
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    result = rest_request("GET", "/api/config/automation/config/1774327685706")
    if result.get("ok"):
        devices_in_then = []
        actions = result["body"].get("actions", [])
        if actions and "then" in actions[0]:
            devices_in_then = [a["target"]["device_id"] for a in actions[0]["then"]]
        print(f"\nNoisebell devices (open action): {devices_in_then}")
        hallway_present = HALLWAY_DEVICE_ID in devices_in_then
        flasch_present = OPEN_CLOSE_DEVICE_IDS["switch.flaschentaschen_socket_1"] in devices_in_then
        print(f"  Hallway deco (should be ABSENT): {'PRESENT - BAD' if hallway_present else 'ABSENT - GOOD'}")
        print(f"  Flaschentaschen (should be PRESENT): {'PRESENT - GOOD' if flasch_present else 'ABSENT - BAD'}")

    result = rest_request("GET", f"/api/config/automation/config/{new_auto_id}")
    if result.get("ok"):
        print(f"\nHallway Deco Lights Schedule: EXISTS (id={new_auto_id})")
        print(f"  Alias: {result['body'].get('alias')}")
    else:
        print(f"\nHallway Deco Lights Schedule: NOT FOUND")

    states = rest_request("GET", "/api/states")
    if states.get("ok"):
        autos = [s for s in states["body"] if s["entity_id"].startswith("automation.")]
        print(f"\nAll automations:")
        for a in autos:
            print(f"  {a['entity_id']}: {a['attributes'].get('friendly_name')} (state={a['state']})")

    print("\n" + "=" * 60)
    print("ALL DONE")
    print("=" * 60)


main()
