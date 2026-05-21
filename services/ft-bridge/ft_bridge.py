#!/usr/bin/env python3
"""
ft_bridge.py — HTTP→FT bridge for Home Assistant / web UI

Endpoints:
  GET  /                 Web UI (image gallery, animations, scroll text)
  GET  /status           Current display state (JSON)
  GET  /layers           Per-layer status (JSON)
  GET  /animations       Available named animations (JSON)
  GET  /art/list         Art image filenames (JSON)
  GET  /art/presets      Preset definitions (JSON)
  GET  /art/<file>       Serve art image
  GET  /frame            Last sent frame as base64 PNG (JSON)
  GET  /donations        Recent donation log (JSON)
  POST /display          Show static text on FT
  POST /scroll           Show scrolling text on FT (uses send-text on ft.noise)
  POST /donation         Record + scroll a donation alert
  POST /image            Send image to FT (base64 PNG/JPEG in JSON)
  POST /image_url        Send image to FT by URL (fetched server-side)
  POST /animation        Run a named animation on ft.noise
  POST /clear            Clear a layer
  POST /ft/qr            Generate QR code and send to FT

POST /display body:
  {"text": "Hello!", "layer": 5, "r": 255, "g": 128, "b": 0, "duration": 30}

POST /scroll body:
  {"text": "Hello Noisebridge!", "layer": 5, "color": "FF00FF", "bg": "000000", "duration": 30}

POST /image body:
  {"image": "<base64>", "layer": 5, "duration": 300}

POST /animation body:
  {"name": "matrix", "layer": 5, "duration": 60}

POST /clear body:
  {"layer": 5}
"""

import base64
import datetime
import io
import json
import os
import shlex
import socket
import subprocess
import threading
import time
import argparse
import urllib.parse
import urllib.request
import qrcode as qrlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
from PIL import Image, ImageDraw, ImageFont, ImageOps

FT_HOST      = '10.21.1.201'
FT_PORT      = 1337
FT_W         = 45
FT_H         = 35
FT_SSH_USER  = 'noisebridge'
FT_SSH_HOST  = 'ft.noise'
FT_DEMOS_DIR = '/home/noisebridge/code/ft-demos'

FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
FONT_SIZE = 8
CHAR_W    = 5

DEFAULT_LAYER    = 5
DEFAULT_DURATION = 30

ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ft_art')

# Named animations: {name: (command_template, description)}
# {g}=geometry, {l}=layer, {t}=duration in seconds
ANIMATIONS = {
    'plasma':       ('{d}/plasma -g{w}x{h} -l{l} -t{t}',          'Plasma waves'),
    'matrix':       ('{d}/matrix -g{w}x{h} -l{l} -b0 -t{t}',      'Matrix rain'),
    'fractal':      ('{d}/fractal -g{w}x{h} -l{l} -t{t}',         'Fractal zoom'),
    'maze':         ('{d}/maze -g{w}x{h} -l{l} -v0 -b0 -t{t}',    'Maze solver'),
    'life':         ('{d}/life -g{w}x{h} -l{l} -c0 -b0 -r30 -t{t}', "Conway's Life"),
    'sierpinski':   ('{d}/sierpinski -g{w}x{h} -l{l} -c0 -r30 -t{t}', 'Sierpinski'),
    'blur-bolt':    ('{d}/blur -g{w}x{h} -l{l} -t{t} bolt',       'Blur: bolt'),
    'blur-boxes':   ('{d}/blur -g{w}x{h} -l{l} -t{t} boxes',      'Blur: boxes'),
    'blur-circles': ('{d}/blur -g{w}x{h} -l{l} -t{t} circles',    'Blur: circles'),
    'lines':        ('{d}/lines -g{w}x{h} -l{l} -t{t} two',       'Lines'),
    'quilt':        ('{d}/quilt -g{w}x{h} -l{l} -t{t}',           'Quilt'),
    'words':        ('{d}/words -g{w}x{h} -l{l} -t{t}',           'Words'),
    'hack':         ('{d}/hack -g{w}x{h} -l{l} -t{t}',            'Hack'),
    'nb-logo':      ('{d}/nb-logo -g{w}x{h} -l{l} -t{t}',         'NB Logo'),
    'random-dots':  ('{d}/random-dots -g{w}x{h} -l{l} -t{t}',     'Random dots'),
}

# Per-layer state tracking
_layers_lock = threading.Lock()
_layer_status = {}   # {layer: {type, text/name, color, expires, active}}

_last_frame = None
_frame_lock = threading.Lock()

_recent_donations  = []
_donations_lock    = threading.Lock()
MAX_RECENT_DONATIONS = 10


# ── SSH helpers ────────────────────────────────────────────────────────────────

def ssh_run_bg(cmd):
    """Fire-and-forget SSH command on ft.noise. Returns immediately."""
    full = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=no',
            f'{FT_SSH_USER}@{FT_SSH_HOST}', cmd]
    subprocess.Popen(full, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ssh_run(cmd, timeout=10):
    """Run SSH command on ft.noise, wait for completion. Returns (rc, stdout, stderr)."""
    full = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=no',
            f'{FT_SSH_USER}@{FT_SSH_HOST}', cmd]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, '', 'timeout'


# ── UDP frame sender ───────────────────────────────────────────────────────────

def send_ppm_frame(img, layer):
    """Send a PIL image to ft-server via UDP and cache the frame."""
    global _last_frame
    header = f'P6\n{FT_W} {FT_H}\n#FT: 0 0 {layer}\n255\n'.encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(header + img.tobytes(), (FT_HOST, FT_PORT))
    s.close()
    with _frame_lock:
        _last_frame = img.copy()


def _set_layer(layer, info):
    with _layers_lock:
        _layer_status[layer] = info


def record_donation(text, color):
    entry = {
        'text':  text,
        'color': color,
        'time':  datetime.datetime.now().strftime('%m/%d %H:%M'),
    }
    with _donations_lock:
        _recent_donations.insert(0, entry)
        del _recent_donations[MAX_RECENT_DONATIONS:]


def _schedule_clear(layer, text_or_name, duration):
    """Auto-clear a layer after duration seconds."""
    def _clear():
        time.sleep(duration)
        with _layers_lock:
            entry = _layer_status.get(layer, {})
            if entry.get('active') and entry.get('label') == text_or_name:
                entry['active'] = False
        clear_layer(layer)
    threading.Thread(target=_clear, daemon=True).start()


# ── Display functions ──────────────────────────────────────────────────────────

def render_text_frame(text, color=(255, 255, 255)):
    img  = Image.new('RGB', (FT_W, FT_H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()
    max_chars = FT_W // CHAR_W
    words = text.split()
    lines, current = [], ''
    for word in words:
        candidate = (current + ' ' + word).strip() if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word[:max_chars]
    if current:
        lines.append(current)
    lines = lines[:4]
    total_h = len(lines) * 10
    start_y = max(0, (FT_H - total_h) // 2)
    for i, line in enumerate(lines):
        text_w = len(line) * CHAR_W
        x = max(0, (FT_W - text_w) // 2)
        draw.text((x, start_y + i * 10), line, fill=color, font=font)
    return img


def clear_layer(layer):
    img = Image.new('RGB', (FT_W, FT_H), (0, 0, 0))
    send_ppm_frame(img, layer)


def display_text(text, layer=DEFAULT_LAYER, color=(255, 255, 255), duration=DEFAULT_DURATION):
    img = render_text_frame(text, color)
    send_ppm_frame(img, layer)
    expires = time.time() + duration if duration > 0 else 0
    _set_layer(layer, {
        'type': 'text', 'label': text, 'color': list(color),
        'expires': expires, 'active': True,
    })
    if duration > 0:
        _schedule_clear(layer, text, duration)
    print(f'[ft_bridge] text layer={layer} dur={duration}s: {text!r}')


def scroll_text(text, layer=DEFAULT_LAYER, color='FFFFFF', bg='000000', duration=DEFAULT_DURATION):
    """Send scrolling text to FT using the send-text binary on ft.noise."""
    safe = shlex.quote(text[:256])
    # FT server treats pure black (000000) as transparent. Use 010101 so the
    # background is opaque and blanks lower layers (demo loop etc).
    opaque_bg = '010101' if bg.upper() == '000000' else bg
    cmd = (
        f'FT_DISPLAY=127.0.0.1 {FT_DEMOS_DIR}/send-text -O '
        f'-g {FT_W}x{FT_H} -l {layer} '
        f'-f {FT_DEMOS_DIR}/ft/client/fonts/5x5.bdf '
        f'-c{color} -b{opaque_bg} {safe}'
    )
    ssh_run_bg(cmd)
    expires = time.time() + duration if duration > 0 else 0
    _set_layer(layer, {
        'type': 'scroll', 'label': text, 'color': color,
        'expires': expires, 'active': True,
    })
    if duration > 0:
        _schedule_clear(layer, text, duration)
    try:
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        preview = render_text_frame(text, color=(r, g, b))
        global _last_frame
        with _frame_lock:
            _last_frame = preview
    except Exception:
        pass
    print(f'[ft_bridge] scroll layer={layer} dur={duration}s: {text!r}')


def display_image(image_data, layer=DEFAULT_LAYER, duration=0):
    img = Image.open(io.BytesIO(image_data)).convert('RGB')
    img = ImageOps.fit(img, (FT_W, FT_H), Image.LANCZOS)
    send_ppm_frame(img, layer)
    expires = time.time() + duration if duration > 0 else 0
    _set_layer(layer, {
        'type': 'image', 'label': f'image {FT_W}x{FT_H}', 'color': [],
        'expires': expires, 'active': True,
    })
    if duration > 0:
        _schedule_clear(layer, f'image {FT_W}x{FT_H}', duration)
    print(f'[ft_bridge] image layer={layer} dur={duration}s')


def display_qr(url='https://donate.noisebridge.net', layer=DEFAULT_LAYER, duration=0):
    qr = qrlib.QRCode(error_correction=qrlib.constants.ERROR_CORRECT_L, box_size=1, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color='#cccccc', back_color='#111111').convert('RGB')
    qw, qh = qr_img.size
    scale = max(1, min(FT_W // qw, FT_H // qh))
    if scale > 1:
        qr_img = qr_img.resize((qw * scale, qh * scale), Image.NEAREST)
        qw, qh = qr_img.size
    canvas = Image.new('RGB', (FT_W, FT_H), (17, 17, 17))
    canvas.paste(qr_img, ((FT_W - qw) // 2, (FT_H - qh) // 2))
    draw = ImageDraw.Draw(canvas)
    blue = (0, 80, 255)
    draw.rectangle([0, 0, 4, FT_H - 1], fill=blue)   # crate-column 1
    draw.rectangle([40, 0, 44, FT_H - 1], fill=blue)  # crate-column 9
    send_ppm_frame(canvas, layer)
    expires = time.time() + duration if duration > 0 else 0
    _set_layer(layer, {'type': 'qr', 'label': url, 'color': [], 'expires': expires, 'active': True})
    if duration > 0:
        _schedule_clear(layer, url, duration)
    print(f'[ft_bridge] qr layer={layer} url={url}')


def run_animation(name, layer=DEFAULT_LAYER, duration=DEFAULT_DURATION):
    """SSH to ft.noise and launch a named animation binary."""
    if name not in ANIMATIONS:
        raise ValueError(f'Unknown animation: {name}')
    tmpl, _ = ANIMATIONS[name]
    cmd = tmpl.format(d=FT_DEMOS_DIR, w=FT_W, h=FT_H, l=layer, t=duration)
    ssh_run_bg(cmd)
    expires = time.time() + duration if duration > 0 else 0
    _set_layer(layer, {
        'type': 'animation', 'label': name, 'color': [],
        'expires': expires, 'active': True,
    })
    global _last_frame
    with _frame_lock:
        _last_frame = render_text_frame(name, color=(127, 219, 202))
    print(f'[ft_bridge] animation={name} layer={layer} dur={duration}s')


# ── Web UI ─────────────────────────────────────────────────────────────────────

def _build_main_page(animations):
    anim_buttons = '\n'.join(
        f'<button class="anim-btn" data-name="{name}" title="{desc}">{name}</button>'
        for name, (_, desc) in animations.items()
    )
    return f'''<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FlaschenTaschen</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, sans-serif; background: #111; color: #eee;
       display: flex; flex-direction: column; align-items: center; padding: 16px; gap: 16px; }}
h1 {{ font-size: 1.2em; color: #7fdbca; }}
h2 {{ font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.1em; color: #7fdbca;
     margin-bottom: 8px; }}
.card {{ background: #1a1a2e; border-radius: 8px; padding: 14px; width: 100%; max-width: 600px; }}
.ft-frame {{ background: #1a1a1a; border-radius: 8px; padding: 12px; display: inline-block; }}
canvas {{ display: block; }}
.mode-btns, .btns {{ display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }}
button {{ padding: 6px 14px; border: none; border-radius: 5px; cursor: pointer;
          font-size: 0.85em; font-weight: 600; }}
.mode-btn {{ background: #333; color: #aaa; }}
.mode-btn.active {{ background: #7fdbca; color: #1a1a2e; }}
.send-btn {{ background: #7fdbca; color: #1a1a2e; }}
.send-btn:disabled {{ opacity: 0.4; cursor: default; }}
.clear-btn {{ background: #444; color: #ccc; }}
select, input[type=text], input[type=number] {{
  background: #222; color: #eee; border: 1px solid #444; border-radius: 4px;
  padding: 5px 8px; font-size: 0.85em; }}
.gallery {{ display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 8px; }}
.thumb {{ width: 68px; height: 53px; border: 2px solid #333; border-radius: 4px;
          cursor: pointer; image-rendering: pixelated; object-fit: contain;
          background: #000; transition: border-color 0.15s; }}
.thumb:hover, .thumb.active {{ border-color: #7fdbca; }}
.info {{ font-size: 0.8em; color: #888; min-height: 1.2em; margin-bottom: 6px; }}
.msg {{ font-size: 0.8em; min-height: 1.2em; }}
.ok {{ color: #7fdbca; }} .err {{ color: #ff6b6b; }}
.anim-grid {{ display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px; }}
.anim-btn {{ background: #1a2a3a; color: #7fdbca; border: 1px solid #2a4a5a;
             border-radius: 4px; padding: 5px 10px; font-size: 0.8em; cursor: pointer;
             transition: background 0.15s; }}
.anim-btn:hover {{ background: #2a3a4a; border-color: #7fdbca; }}
.anim-btn.active {{ background: #7fdbca; color: #1a1a2e; border-color: #7fdbca; }}
.row {{ display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }}
label {{ font-size: 0.8em; color: #888; }}
.layers-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }}
.layer-cell {{ background: #222; border-radius: 4px; padding: 6px; font-size: 0.72em;
               text-align: center; border: 1px solid #333; }}
.layer-cell.active {{ border-color: #7fdbca; color: #7fdbca; }}
.layer-cell .lnum {{ font-size: 1.1em; font-weight: bold; margin-bottom: 2px; }}
.layer-cell .linfo {{ color: #888; font-size: 0.9em; word-break: break-all; }}
.layer-cell.active .linfo {{ color: #aaa; }}
</style>
</head><body>
<h1>FlaschenTaschen</h1>

<!-- Preview -->
<div class="card" style="text-align:center">
  <div class="mode-btns" style="justify-content:center">
    <button class="mode-btn active" onclick="setMode('bottles')">Bottles</button>
    <button class="mode-btn" onclick="setMode('pixels')">Pixels</button>
    <button class="mode-btn" onclick="setMode('smooth')">Smooth</button>
  </div>
  <div class="ft-frame"><canvas id="ft" width="540" height="420"></canvas></div>
</div>

<!-- Image upload -->
<div class="card">
  <h2>Image</h2>
  <div class="gallery" id="gallery"></div>
  <div class="info" id="imgInfo">Select or upload an image</div>
  <div class="row">
    <input type="file" id="upload" accept="image/*" style="font-size:0.8em">
  </div>
  <div class="row">
    <label>Layer</label>
    <input type="number" id="imgLayer" value="5" min="0" max="15" style="width:55px">
    <label>Duration</label>
    <select id="imgDur">
      <option value="0">Permanent</option>
      <option value="60">1 min</option>
      <option value="300" selected>5 min</option>
      <option value="600">10 min</option>
      <option value="1800">30 min</option>
    </select>
    <button class="send-btn" id="sendImgBtn" disabled onclick="sendImage()">Send</button>
    <button class="clear-btn" onclick="clearLayer(+document.getElementById('imgLayer').value)">Clear layer</button>
  </div>
  <div class="row">
    <input type="text" id="imgUrl" placeholder="Image URL…" style="flex:1">
    <button class="send-btn" onclick="sendImageURL()">Send from URL</button>
  </div>
  <div class="msg" id="imgMsg"></div>
</div>

<!-- Scroll text -->
<div class="card">
  <h2>Scrolling Text</h2>
  <div class="row">
    <input type="text" id="scrollText" placeholder="Text to scroll…" style="flex:1">
  </div>
  <div class="row">
    <label>Color</label>
    <input type="color" id="scrollColor" value="#ffffff" style="width:40px;height:28px;padding:1px;background:#222;border:1px solid #444;border-radius:4px">
    <label>BG</label>
    <input type="color" id="scrollBg" value="#000000" style="width:40px;height:28px;padding:1px;background:#222;border:1px solid #444;border-radius:4px">
    <label>Layer</label>
    <input type="number" id="scrollLayer" value="5" min="0" max="15" style="width:55px">
    <label>Duration</label>
    <select id="scrollDur">
      <option value="30" selected>30s</option>
      <option value="60">1 min</option>
      <option value="120">2 min</option>
      <option value="300">5 min</option>
      <option value="0">Permanent</option>
    </select>
    <button class="send-btn" onclick="sendScroll()">Send</button>
  </div>
  <div class="msg" id="scrollMsg"></div>
</div>

<!-- Animations -->
<div class="card">
  <h2>Animations</h2>
  <div class="anim-grid" id="animGrid">
    {anim_buttons}
  </div>
  <div class="row">
    <label>Layer</label>
    <input type="number" id="animLayer" value="5" min="0" max="15" style="width:55px">
    <label>Duration</label>
    <select id="animDur">
      <option value="30">30s</option>
      <option value="60" selected>1 min</option>
      <option value="120">2 min</option>
      <option value="300">5 min</option>
      <option value="600">10 min</option>
    </select>
    <button class="send-btn" id="sendAnimBtn" disabled onclick="sendAnimation()">Run</button>
    <button class="clear-btn" onclick="clearLayer(+document.getElementById('animLayer').value)">Clear layer</button>
  </div>
  <div class="msg" id="animMsg"></div>
</div>

<!-- Donate QR -->
<div class="card">
  <h2>Donate QR Code</h2>
  <div class="row">
    <input type="text" id="qrUrl" value="https://donate.noisebridge.net" style="flex:1">
    <label>Layer</label>
    <input type="number" id="qrLayer" value="5" min="0" max="15" style="width:55px">
    <button class="send-btn" onclick="sendQR()">Send to FT</button>
    <button class="clear-btn" onclick="clearLayer(+document.getElementById('qrLayer').value)">Clear</button>
  </div>
  <div class="msg" id="qrMsg"></div>
</div>

<!-- Layer status -->
<div class="card">
  <h2>Layer Status <button class="clear-btn" style="font-size:0.75em;padding:3px 8px" onclick="refreshLayers()">Refresh</button></h2>
  <div class="layers-grid" id="layersGrid"></div>
</div>

<script>
const W=45, H=35, SCALE=12;
const cv=document.getElementById('ft'), ctx=cv.getContext('2d');
const ftCanvas=document.createElement('canvas'); ftCanvas.width=W; ftCanvas.height=H;
const ftCtx=ftCanvas.getContext('2d');
let mode='bottles', currentB64=null, selectedAnim=null;

function setMode(m) {{
  mode=m;
  document.querySelectorAll('.mode-btn').forEach(b=>b.classList.toggle('active', b.textContent.toLowerCase()===m));
  redraw();
}}

function redraw() {{
  ctx.fillStyle='#1a1a1a'; ctx.fillRect(0,0,cv.width,cv.height);
  const d=ftCtx.getImageData(0,0,W,H).data;
  for(let y=0;y<H;y++) for(let x=0;x<W;x++) {{
    const i=(y*W+x)*4, r=d[i], g=d[i+1], b=d[i+2];
    const cx=x*SCALE+SCALE/2, cy=y*SCALE+SCALE/2;
    if(mode==='bottles') {{
      const bright=Math.max(r,g,b)/255;
      if(bright>0.05) {{
        const grad=ctx.createRadialGradient(cx,cy,SCALE*0.5*0.5,cx,cy,SCALE*1.8);
        grad.addColorStop(0,`rgba(${{r}},${{g}},${{b}},${{bright*0.3}})`);
        grad.addColorStop(1,'rgba(0,0,0,0)');
        ctx.fillStyle=grad; ctx.fillRect(cx-SCALE,cy-SCALE,SCALE*2,SCALE*2);
      }}
      ctx.beginPath(); ctx.arc(cx,cy,SCALE*0.4,0,Math.PI*2);
      ctx.fillStyle=`rgb(${{r}},${{g}},${{b}})`; ctx.fill();
      if(bright>0.1) {{
        ctx.beginPath(); ctx.arc(cx-SCALE*0.08,cy-SCALE*0.1,SCALE*0.1,0,Math.PI*2);
        ctx.fillStyle=`rgba(255,255,255,${{bright*0.25}})`; ctx.fill();
      }}
    }} else if(mode==='pixels') {{
      ctx.fillStyle=`rgb(${{r}},${{g}},${{b}})`;
      ctx.fillRect(x*SCALE+0.5,y*SCALE+0.5,SCALE-1,SCALE-1);
    }} else {{
      ctx.fillStyle=`rgb(${{r}},${{g}},${{b}})`;
      ctx.fillRect(x*SCALE,y*SCALE,SCALE,SCALE);
    }}
  }}
}}

function loadImageToFT(img) {{
  const scale=Math.max(W/img.width, H/img.height);
  const sw=W/scale, sh=H/scale, sx=(img.width-sw)/2, sy=(img.height-sh)/2;
  ftCtx.clearRect(0,0,W,H); ftCtx.drawImage(img,sx,sy,sw,sh,0,0,W,H);
  currentB64=ftCanvas.toDataURL('image/png').split(',')[1];
  document.getElementById('sendImgBtn').disabled=false;
  redraw();
}}

function loadFromURL(url, name) {{
  const img=new Image(); img.crossOrigin='anonymous';
  img.onload=()=>{{ loadImageToFT(img); document.getElementById('imgInfo').textContent=name||url;
    document.querySelectorAll('.thumb').forEach(t=>t.classList.toggle('active',t.dataset.name===name)); }};
  img.src=url;
}}

// Gallery
fetch('/art/list').then(r=>r.json()).then(files=>{{
  const g=document.getElementById('gallery');
  files.forEach(f=>{{
    const img=document.createElement('img');
    img.className='thumb'; img.dataset.name=f; img.src='/art/'+encodeURIComponent(f); img.title=f;
    img.onclick=()=>loadFromURL('/art/'+encodeURIComponent(f),f);
    g.appendChild(img);
  }});
}}).catch(()=>{{}});

// File upload
document.getElementById('upload').addEventListener('change',function(e){{
  const file=e.target.files[0]; if(!file) return;
  const reader=new FileReader();
  reader.onload=ev=>{{ const img=new Image(); img.onload=()=>{{ loadImageToFT(img);
    document.getElementById('imgInfo').textContent=file.name+' (uploaded)'; }}; img.src=ev.target.result; }};
  reader.readAsDataURL(file);
}});

async function sendImage() {{
  if(!currentB64) return;
  const msg=document.getElementById('imgMsg');
  msg.className='msg'; msg.textContent='Sending…';
  const layer=+document.getElementById('imgLayer').value;
  const dur=+document.getElementById('imgDur').value;
  try {{
    const r=await fetch('/image',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{image:currentB64,layer,duration:dur}})}});
    const j=await r.json();
    msg.className=j.ok?'msg ok':'msg err';
    msg.textContent=j.ok?'Sent!':j.error||'Failed';
    if(j.ok) refreshLayers();
  }} catch(e) {{ msg.className='msg err'; msg.textContent=e.message; }}
}}

async function sendImageURL() {{
  const url=document.getElementById('imgUrl').value.trim();
  if(!url) return;
  const msg=document.getElementById('imgMsg');
  msg.className='msg'; msg.textContent='Fetching…';
  const layer=+document.getElementById('imgLayer').value;
  const dur=+document.getElementById('imgDur').value;
  try {{
    const r=await fetch('/image_url',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{url,layer,duration:dur}})}});
    const j=await r.json();
    msg.className=j.ok?'msg ok':'msg err';
    msg.textContent=j.ok?'Sent!':j.error||'Failed';
    if(j.ok) refreshLayers();
  }} catch(e) {{ msg.className='msg err'; msg.textContent=e.message; }}
}}

async function sendScroll() {{
  const text=document.getElementById('scrollText').value.trim();
  if(!text) return;
  const msg=document.getElementById('scrollMsg');
  msg.className='msg'; msg.textContent='Sending…';
  const color=document.getElementById('scrollColor').value.replace('#','');
  const bg=document.getElementById('scrollBg').value.replace('#','');
  const layer=+document.getElementById('scrollLayer').value;
  const duration=+document.getElementById('scrollDur').value;
  try {{
    const r=await fetch('/scroll',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{text,layer,color,bg,duration}})}});
    const j=await r.json();
    msg.className=j.ok?'msg ok':'msg err';
    msg.textContent=j.ok?`Scrolling on layer ${{layer}}`:j.error||'Failed';
    if(j.ok) refreshLayers();
  }} catch(e) {{ msg.className='msg err'; msg.textContent=e.message; }}
}}

// Animations
document.querySelectorAll('.anim-btn').forEach(btn=>{{
  btn.addEventListener('click',()=>{{
    document.querySelectorAll('.anim-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    selectedAnim=btn.dataset.name;
    document.getElementById('sendAnimBtn').disabled=false;
    document.getElementById('animMsg').textContent='';
  }});
}});

async function sendAnimation() {{
  if(!selectedAnim) return;
  const msg=document.getElementById('animMsg');
  msg.className='msg'; msg.textContent=`Running ${{selectedAnim}}…`;
  const layer=+document.getElementById('animLayer').value;
  const duration=+document.getElementById('animDur').value;
  try {{
    const r=await fetch('/animation',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{name:selectedAnim,layer,duration}})}});
    const j=await r.json();
    msg.className=j.ok?'msg ok':'msg err';
    msg.textContent=j.ok?`${{selectedAnim}} running for ${{duration}}s on layer ${{layer}}`:j.error||'Failed';
    if(j.ok) refreshLayers();
  }} catch(e) {{ msg.className='msg err'; msg.textContent=e.message; }}
}}

async function sendQR() {{
  const url=document.getElementById('qrUrl').value.trim();
  const layer=+document.getElementById('qrLayer').value;
  const msg=document.getElementById('qrMsg');
  msg.className='msg'; msg.textContent='Generating…';
  try {{
    const r=await fetch('/ft/qr',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{url,layer,duration:0}})}});
    const j=await r.json();
    msg.className=j.ok?'msg ok':'msg err';
    msg.textContent=j.ok?'QR on display!':j.error||'Failed';
    if(j.ok) refreshLayers();
  }} catch(e) {{ msg.className='msg err'; msg.textContent=e.message; }}
}}

async function clearLayer(layer) {{
  await fetch('/clear',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{layer}})}});
  refreshLayers();
}}

// Layer status
async function refreshLayers() {{
  try {{
    const r=await fetch('/layers'); const j=await r.json();
    const grid=document.getElementById('layersGrid');
    grid.innerHTML='';
    for(let l=0;l<=15;l++) {{
      const info=j[l];
      const cell=document.createElement('div');
      cell.className='layer-cell'+(info&&info.active?' active':'');
      const ttl=info&&info.expires>0?Math.max(0,Math.round(info.expires-Date.now()/1000)):null;
      cell.innerHTML=`<div class="lnum">L${{l}}</div>`+
        (info&&info.active?`<div class="linfo">${{info.type}}<br>${{info.label?.substring(0,12)||''}}`+
        (ttl!==null?`<br>${{ttl}}s`:'')+'</div>':'<div class="linfo">—</div>');
      grid.appendChild(cell);
    }}
  }} catch(e) {{}}
}}

ftCtx.fillStyle='#000'; ftCtx.fillRect(0,0,W,H); redraw();
refreshLayers();
setInterval(refreshLayers, 5000);
</script>
</body></html>'''


# ── HTTP handler ───────────────────────────────────────────────────────────────

class FTBridgeHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f'[ft_bridge] {self.address_string()} {fmt % args}')

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, code, html):
        body = html.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, filepath, content_type):
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_json(404, {'error': 'not found'})

    def read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path in ('/', '/index.html'):
            self.send_html(200, _build_main_page(ANIMATIONS))

        elif path == '/status':
            with _layers_lock:
                active = {k: v for k, v in _layer_status.items() if v.get('active')}
            self.send_json(200, {'layers': active})

        elif path == '/layers':
            now = time.time()
            with _layers_lock:
                out = {}
                for l, info in _layer_status.items():
                    out[l] = dict(info)
                    out[l]['expires'] = info.get('expires', 0)
            self.send_json(200, out)

        elif path == '/animations':
            self.send_json(200, {
                name: {'command': tmpl, 'description': desc}
                for name, (tmpl, desc) in ANIMATIONS.items()
            })

        elif path == '/frame':
            with _frame_lock:
                frame = _last_frame
            if frame is None:
                self.send_json(200, {'frame': None})
            else:
                buf = io.BytesIO()
                frame.save(buf, format='PNG')
                self.send_json(200, {
                    'frame': base64.b64encode(buf.getvalue()).decode(),
                    'width': FT_W, 'height': FT_H,
                })

        elif path == '/donations':
            with _donations_lock:
                recent = list(_recent_donations)
            self.send_json(200, {'count': len(recent), 'list': recent})

        elif path == '/qr.png':
            url = params.get('url', ['https://donate.noisebridge.net'])[0]
            qr = qrlib.QRCode(error_correction=qrlib.constants.ERROR_CORRECT_L, box_size=1, border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color='#cccccc', back_color='#111111').convert('RGB')
            qw, qh = qr_img.size
            scale = max(1, min(FT_W // qw, FT_H // qh))
            if scale > 1:
                qr_img = qr_img.resize((qw * scale, qh * scale), Image.NEAREST)
                qw, qh = qr_img.size
            canvas = Image.new('RGB', (FT_W, FT_H), (17, 17, 17))
            canvas.paste(qr_img, ((FT_W - qw) // 2, (FT_H - qh) // 2))
            draw = ImageDraw.Draw(canvas)
            blue = (0, 80, 255)
            draw.rectangle([0, 0, 4, FT_H - 1], fill=blue)
            draw.rectangle([40, 0, 44, FT_H - 1], fill=blue)
            buf = io.BytesIO()
            canvas.save(buf, format='PNG')
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.end_headers()
            self.wfile.write(buf.getvalue())
            return

        elif path == '/art/presets':
            presets_file = os.path.join(ART_DIR, 'presets.json')
            try:
                with open(presets_file) as f:
                    self.send_json(200, json.load(f))
            except FileNotFoundError:
                self.send_json(200, [])

        elif path == '/art/list':
            exts = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
            files = []
            if os.path.isdir(ART_DIR):
                files = sorted(f for f in os.listdir(ART_DIR)
                               if f.lower().endswith(exts) and not f.startswith('.'))
            self.send_json(200, files)

        elif path.startswith('/art/'):
            name = os.path.basename(urllib.parse.unquote(path[5:]))
            filepath = os.path.join(ART_DIR, name)
            ext = name.lower().rsplit('.', 1)[-1] if '.' in name else ''
            ct = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                  'gif': 'image/gif', 'bmp': 'image/bmp', 'webp': 'image/webp'
                  }.get(ext, 'application/octet-stream')
            self.send_file(filepath, ct)

        else:
            self.send_json(404, {'error': 'not found'})

    def do_POST(self):
        body = self.read_json()
        if body is None:
            self.send_json(400, {'error': 'invalid JSON'})
            return

        path = self.path.split('?')[0]

        if path in ('/display', '/ft/display'):
            text = body.get('text', '').strip()
            if not text:
                self.send_json(400, {'error': 'text required'})
                return
            layer    = int(body.get('layer', DEFAULT_LAYER))
            color    = (int(body.get('r', 255)), int(body.get('g', 255)), int(body.get('b', 255)))
            duration = int(body.get('duration', DEFAULT_DURATION))
            display_text(text, layer=layer, color=color, duration=duration)
            self.send_json(200, {'ok': True, 'text': text})

        elif path in ('/scroll', '/ft/scroll'):
            text = body.get('text', '').strip()
            if not text:
                self.send_json(400, {'error': 'text required'})
                return
            layer    = int(body.get('layer', DEFAULT_LAYER))
            color    = body.get('color', 'FFFFFF').lstrip('#').upper()
            bg       = body.get('bg', '000000').lstrip('#').upper()
            duration = int(body.get('duration', DEFAULT_DURATION))
            scroll_text(text, layer=layer, color=color, bg=bg, duration=duration)
            self.send_json(200, {'ok': True, 'text': text, 'layer': layer})

        elif path in ('/image', '/ft/image'):
            image_b64 = body.get('image', '')
            if not image_b64:
                self.send_json(400, {'error': 'image required (base64)'})
                return
            try:
                image_data = base64.b64decode(image_b64)
            except Exception:
                self.send_json(400, {'error': 'invalid base64'})
                return
            layer    = int(body.get('layer', DEFAULT_LAYER))
            duration = int(body.get('duration', 0))
            try:
                display_image(image_data, layer=layer, duration=duration)
                self.send_json(200, {'ok': True, 'layer': layer})
            except Exception as e:
                self.send_json(500, {'error': str(e)})

        elif path in ('/image_url', '/ft/image_url'):
            url = body.get('url', '').strip()
            if not url:
                self.send_json(400, {'error': 'url required'})
                return
            layer    = int(body.get('layer', DEFAULT_LAYER))
            duration = int(body.get('duration', 30))
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'ft-bridge/1.0'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    image_data = resp.read()
                display_image(image_data, layer=layer, duration=duration)
                self.send_json(200, {'ok': True, 'layer': layer, 'duration': duration})
            except Exception as e:
                self.send_json(500, {'error': str(e)})

        elif path in ('/animation', '/ft/animation'):
            name = body.get('name', '').strip()
            if not name:
                self.send_json(400, {'error': 'name required'})
                return
            if name not in ANIMATIONS:
                self.send_json(400, {'error': f'unknown animation: {name}', 'available': list(ANIMATIONS)})
                return
            layer    = int(body.get('layer', DEFAULT_LAYER))
            duration = int(body.get('duration', DEFAULT_DURATION))
            run_animation(name, layer=layer, duration=duration)
            self.send_json(200, {'ok': True, 'name': name, 'layer': layer, 'duration': duration})

        elif path in ('/clear', '/ft/clear'):
            layer = int(body.get('layer', DEFAULT_LAYER))
            clear_layer(layer)
            with _layers_lock:
                if layer in _layer_status:
                    _layer_status[layer]['active'] = False
            print(f'[ft_bridge] cleared layer {layer}')
            self.send_json(200, {'ok': True, 'layer': layer})

        elif path in ('/donation', '/ft/donation'):
            text = body.get('text', '').strip()
            if not text:
                self.send_json(400, {'error': 'text required'})
                return
            color    = body.get('color', 'FFD700').lstrip('#').upper()
            layer    = int(body.get('layer', DEFAULT_LAYER))
            duration = int(body.get('duration', DEFAULT_DURATION))
            record_donation(text, color)
            scroll_text(text, layer=layer, color=color, duration=duration)
            self.send_json(200, {'ok': True, 'text': text})

        elif path in ('/ft/qr', '/qr'):
            url      = body.get('url', 'https://donate.noisebridge.net')
            layer    = int(body.get('layer', DEFAULT_LAYER))
            duration = int(body.get('duration', 0))
            try:
                display_qr(url=url, layer=layer, duration=duration)
                self.send_json(200, {'ok': True, 'layer': layer, 'url': url})
            except Exception as e:
                self.send_json(500, {'error': str(e)})

        else:
            self.send_json(404, {'error': 'not found'})


def main():
    global ART_DIR, FT_SSH_HOST
    parser = argparse.ArgumentParser(description='HTTP→FT bridge')
    parser.add_argument('--port', type=int, default=8877)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--ft-host', default=FT_HOST)
    parser.add_argument('--ft-ssh', default=FT_SSH_HOST)
    parser.add_argument('--art-dir', default=ART_DIR)
    args = parser.parse_args()

    ART_DIR = args.art_dir
    FT_SSH_HOST = args.ft_ssh

    server = ThreadedHTTPServer((args.host, args.port), FTBridgeHandler)
    print(f'ft_bridge listening on {args.host}:{args.port}')
    print(f'FT UDP → {FT_HOST}:{FT_PORT}  |  FT SSH → {FT_SSH_USER}@{FT_SSH_HOST}')
    print(f'Art dir: {ART_DIR}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == '__main__':
    main()
