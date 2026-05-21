import asyncio, json, os, sys, time
import websockets

HA_URL = os.environ["HA_URL"]
TOKEN  = os.environ["HA_TOKEN"]
WS = HA_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
COLLECT_SECS = 25

def classify(rssi):
    if rssi is None: return "?"
    if rssi >= -70: return "GOOD"
    if rssi >= -82: return "marginal"
    return "POOR"

async def main():
    seen = {}   # address -> dict(name, best_rssi, source, count)
    async with websockets.connect(WS, max_size=None, ping_interval=None) as ws:
        assert json.loads(await ws.recv())["type"] == "auth_required"
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            print("AUTH FAILED:", auth); return
        await ws.send(json.dumps({"id": 1, "type": "bluetooth/subscribe_advertisements"}))
        res = json.loads(await ws.recv())
        if not res.get("success", False):
            print("subscribe failed:", res); return

        end = time.time() + COLLECT_SECS
        while time.time() < end:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - time.time()))
            except asyncio.TimeoutError:
                break
            if msg.get("type") != "event":
                continue
            ev = msg["event"]
            items = []
            if isinstance(ev, dict):
                for k in ("add", "change"):
                    items += ev.get(k, [])
                if "address" in ev:   # some HA versions send a flat item
                    items.append(ev)
            for it in items:
                addr = it.get("address")
                if not addr: continue
                rssi = it.get("rssi")
                rec = seen.setdefault(addr, {"name": None, "best": -999, "source": it.get("source"), "n": 0})
                rec["n"] += 1
                if it.get("name"): rec["name"] = it["name"]
                if rssi is not None and rssi > rec["best"]: rec["best"] = rssi
                if it.get("source"): rec["source"] = it["source"]

    print(f"HA Bluetooth heard {len(seen)} device(s) in {COLLECT_SECS}s.\n")
    target = []
    for addr, r in seen.items():
        nm = (r["name"] or "")
        if "sp648" in nm.lower() or "banlanx" in nm.lower() or "sp6" in nm.lower():
            target.append((addr, r))
    if target:
        print("*** POSSIBLE MATCH (SP648E / BanlanX) ***")
        for addr, r in target:
            print(f"  {addr}  name={r['name']!r}  rssi={r['best']} [{classify(r['best'])}]  via={r['source']}  ads={r['n']}")
        print()
    else:
        print("No device named SP648E/BanlanX seen.\n")

    print("All devices (strongest first):")
    for addr, r in sorted(seen.items(), key=lambda kv: kv[1]["best"], reverse=True):
        print(f"  rssi={r['best']:>4} [{classify(r['best']):8}] {addr}  name={r['name']!r}  via={r['source']}")

asyncio.get_event_loop().run_until_complete(main())
