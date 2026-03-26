#!/usr/bin/env python3
"""Register the HA watchdog workflow on Conductor. Schedule via cron."""
import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8888"
PANEL = "http://localhost:8082"
NBLIGHTS = "http://localhost:8098"


def api(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
          headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return raw.decode().strip()
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} on {method} {path}: {e.read().decode()[:200]}")
        return None


def http_task(ref, uri, method="POST", body=None):
    t = {"name": f"http_{ref}", "taskReferenceName": ref,
         "type": "HTTP", "inputParameters": {
             "http_request": {"uri": uri, "method": method,
                              "connectionTimeOut": 5000, "readTimeOut": 10000}}}
    if body:
        t["inputParameters"]["http_request"]["body"] = body
    return t


# ─────────────────────────────────────────────
# knob-ha-watchdog — check HA health, update panel
# ─────────────────────────────────────────────
wf_ha_watchdog = {
    "name": "knob-ha-watchdog", "version": 1,
    "ownerEmail": "knob@noisebridge.net",
    "description": "Check HA health — sensor freshness, upstream sync, switch states",
    "tasks": [
        # Step 1: fetch health status
        http_task("check_ha", f"{NBLIGHTS}/health/ha", "GET"),

        # Step 2: update the panel lamp with the result
        {
            "name": "http_set_ha_lamp",
            "taskReferenceName": "set_ha_lamp",
            "type": "HTTP",
            "inputParameters": {
                "http_request": {
                    "uri": f"{PANEL}/api/lamp/ha-status",
                    "method": "POST",
                    "connectionTimeOut": 3000,
                    "readTimeOut": 3000,
                    "body": {
                        "state": "on",
                        "color": "${check_ha.output.response.body.color}",
                        "_meta": {
                            "label": "HA Status",
                            "section": "NOISEBRIDGE",
                        },
                    },
                }
            },
        },

        # Step 3: post to ticker
        {
            "name": "http_ha_ticker",
            "taskReferenceName": "ha_ticker",
            "type": "HTTP",
            "inputParameters": {
                "http_request": {
                    "uri": f"{PANEL}/api/ticker",
                    "method": "POST",
                    "connectionTimeOut": 3000,
                    "readTimeOut": 3000,
                    "body": {
                        "message": "HA: ${check_ha.output.response.body.message}",
                        "source": "HA",
                    },
                }
            },
        },
    ],
}

print("=== Registering HA watchdog workflow ===")
r = api("PUT", "/api/metadata/workflow", [wf_ha_watchdog])
status = "OK" if r is not None else "FAIL"
print(f"  [{status}] knob-ha-watchdog")

if status == "FAIL":
    print("\nAborting.")
    exit(1)

# Fire it once now to verify
print("\n=== Firing test run ===")
r = api("POST", "/api/workflow", {"name": "knob-ha-watchdog", "version": 1, "input": {}})
if r:
    wf_id = r if isinstance(r, str) else r.get("workflowId", r)
    print(f"  Workflow started: {wf_id}")
    time.sleep(3)
    # Check result
    result = api("GET", f"/api/workflow/{wf_id}")
    if result:
        print(f"  Status: {result.get('status')}")
        for task in result.get("tasks", []):
            ref = task.get("referenceTaskName", "?")
            st = task.get("status", "?")
            print(f"    {ref}: {st}")
else:
    print("  Failed to start workflow")

print("""
=== Cron setup ===
Add this to crontab (crontab -e):

*/5 * * * * curl -sf -X POST 'http://localhost:8888/api/workflow' -H 'Content-Type: application/json' -d '{"name":"knob-ha-watchdog","version":1,"input":{}}' > /dev/null 2>&1
""")
