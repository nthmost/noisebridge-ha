#!/usr/bin/env python3
"""
donation_alerts.py — Mirror donate.noisebridge.net alerts to FlaschenTaschen.

Connects to the donate-portal WebSocket and scrolls donation/membership
events on the FT display via ft_bridge's /donation endpoint, which also
logs them to the recent-donations list polled by Home Assistant.

Credentials: DONATE_ALERTS_USER and DONATE_ALERTS_PASS
  Set in environment or in ~/.secrets/donate_alerts.env
"""
import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

FT_BRIDGE   = 'http://localhost:8877'
FT_LAYER    = 5
FT_DURATION = 90   # seconds to display each alert
ENV_FILE    = Path.home() / '.secrets' / 'donate_alerts.env'


def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


def alerts_ws_url():
    user = os.environ.get('DONATE_ALERTS_USER', '')
    pw   = os.environ.get('DONATE_ALERTS_PASS', '')
    return f'wss://{user}:{pw}@donate.noisebridge.net/alerts/ws'


def ft_donate(text, color='FFD700'):
    data = json.dumps({
        'text': text, 'color': color,
        'layer': FT_LAYER, 'duration': FT_DURATION,
    }).encode()
    req = urllib.request.Request(
        f'{FT_BRIDGE}/donation', data=data,
        headers={'Content-Type': 'application/json'},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        print(f'[donation_alerts] donated: {text!r}')
    except Exception as e:
        print(f'[donation_alerts] ft_donate failed: {e}', file=sys.stderr)


def format_alert(msg):
    t = msg.get('type')
    if t == 'charge_alert':
        cents = msg.get('amount', {}).get('cents', 0)
        dollars = cents / 100
        product = msg.get('productName', 'Donation')
        amt = f'${dollars:.2f}'
        return f'{amt}  {product}  {amt}', 'FFD700'   # gold
    elif t == 'member_alert':
        product = msg.get('productName', 'New Member')
        return f'New member: {product}', '00FF88'        # green
    return None, None


async def run():
    import websockets

    user = os.environ.get('DONATE_ALERTS_USER', '')
    pw   = os.environ.get('DONATE_ALERTS_PASS', '')
    if not user or not pw:
        print('[donation_alerts] ERROR: DONATE_ALERTS_USER / DONATE_ALERTS_PASS not set', file=sys.stderr)
        sys.exit(1)

    url = alerts_ws_url()

    while True:
        try:
            print(f'[donation_alerts] connecting...')
            async with websockets.connect(url) as ws:
                print('[donation_alerts] connected')
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get('type') == 'ping':
                        await ws.send(json.dumps({'type': 'pong'}))
                        continue
                    text, color = format_alert(msg)
                    if text:
                        ft_donate(text, color)
        except Exception as e:
            print(f'[donation_alerts] connection lost: {e} — reconnecting in 30s', file=sys.stderr)
            await asyncio.sleep(30)


if __name__ == '__main__':
    load_env()
    asyncio.run(run())
