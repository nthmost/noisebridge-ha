#!/usr/bin/env python3
"""
ft_nowplaying.py — KNOB now-playing display on FlaschenTaschen

On track change:
  - Layer 0: album art (center-cropped to 45x35, persistent background)
  - Layer 1: scrolling artist / title / show text (transparent overlay)

Album art sources (tried in order):
  1. Embedded APIC tag in the audio file (mutagen)
  2. MusicBrainz Cover Art Archive (free, no key)
  3. iTunes Search API (free, no key)
  4. Solid color fallback (genre-based)

Runs on beyla as systemd service ft-nowplaying.
"""

import io
import json
import socket
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

import mutagen.mp3
import mutagen.flac
import mutagen.ogg
from PIL import Image, ImageDraw, ImageFont, ImageOps

FT_HOST  = '10.21.1.201'
FT_PORT  = 1337
FT_W     = 45
FT_H     = 35

LS_HOST  = 'localhost'
LS_PORT  = 1234

FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
FONT_SIZE = 8
CHAR_W    = 5

ROW_ARTIST = 1
ROW_TITLE  = 13
ROW_SHOW   = 25

COLOR_ARTIST = (0, 220, 220)
COLOR_TITLE  = (255, 255, 255)
COLOR_SHOW   = (180, 100, 255)

SCROLL_SPEED  = 1
FRAME_DELAY   = 0.08
POLL_INTERVAL = 5

USER_AGENT = 'KNOB-FT/1.0 (noisebridge.net radio display)'


# ── Liquidsoap ────────────────────────────────────────────────────────────────

def ls_query(cmd):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((LS_HOST, LS_PORT))
        s.sendall((cmd + '\n').encode())
        resp = b''
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b'END\r\n' in resp or b'END\n' in resp:
                break
        s.close()
        lines = resp.decode('utf-8', errors='replace').strip().splitlines()
        return [l for l in lines if l.strip() and l.strip() != 'END']
    except Exception as e:
        print(f'[ls] {e}', file=sys.stderr)
        return []


def get_now_playing():
    rid_lines = ls_query('request.on_air')
    if not rid_lines:
        return None
    rid = rid_lines[0].strip()
    if not rid:
        return None
    meta_lines = ls_query(f'request.metadata {rid}')
    meta = {}
    for line in meta_lines:
        if '=' in line:
            k, _, v = line.partition('=')
            meta[k.strip()] = v.strip().strip('"')
    artist = meta.get('artist', '').strip()
    title  = meta.get('title', '').strip()
    if not artist and not title:
        return None
    return {
        'artist':   artist,
        'title':    title,
        'album':    meta.get('album', '').strip(),
        'genre':    meta.get('genre', '').strip(),
        'filename': meta.get('filename', '').strip(),
        'rid':      rid,
    }


# ── Album art fetching ────────────────────────────────────────────────────────

def fetch_url(url, timeout=5):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def art_from_file(filename):
    """Extract embedded cover art from audio file tags."""
    if not filename:
        return None
    try:
        ext = filename.lower().rsplit('.', 1)[-1]
        if ext == 'mp3':
            f = mutagen.mp3.MP3(filename)
            apic = f.tags.get('APIC:') if f.tags else None
            if apic:
                return Image.open(io.BytesIO(apic.data)).convert('RGB')
        elif ext == 'flac':
            f = mutagen.flac.FLAC(filename)
            if f.pictures:
                return Image.open(io.BytesIO(f.pictures[0].data)).convert('RGB')
        elif ext in ('ogg', 'oga'):
            # Vorbis comment covers are base64-encoded
            import base64
            f = mutagen.ogg.OggVorbis(filename)
            covers = f.get('metadata_block_picture', [])
            if covers:
                from mutagen.flac import Picture
                p = Picture(base64.b64decode(covers[0]))
                return Image.open(io.BytesIO(p.data)).convert('RGB')
    except Exception as e:
        print(f'[art/file] {e}', file=sys.stderr)
    return None


def art_from_musicbrainz(artist, album):
    """Look up cover via MusicBrainz + Cover Art Archive."""
    if not artist or not album:
        return None
    try:
        query = urllib.parse.quote(f'artist:"{artist}" AND release:"{album}"')
        url = f'https://musicbrainz.org/ws/2/release/?query={query}&limit=1&fmt=json'
        data = json.loads(fetch_url(url))
        releases = data.get('releases', [])
        if not releases:
            return None
        mbid = releases[0]['id']
        img_data = fetch_url(f'https://coverartarchive.org/release/{mbid}/front-250')
        return Image.open(io.BytesIO(img_data)).convert('RGB')
    except Exception as e:
        print(f'[art/musicbrainz] {e}', file=sys.stderr)
    return None


def art_from_itunes(artist, title):
    """Look up cover via iTunes Search API."""
    if not artist or not title:
        return None
    try:
        term = urllib.parse.quote(f'{artist} {title}')
        url  = f'https://itunes.apple.com/search?term={term}&entity=song&limit=3'
        data = json.loads(fetch_url(url))
        results = data.get('results', [])
        if not results:
            return None
        art_url = results[0].get('artworkUrl100', '')
        if not art_url:
            return None
        # Request 600px version for better downsampling
        art_url = art_url.replace('100x100bb', '600x600bb')
        img_data = fetch_url(art_url)
        return Image.open(io.BytesIO(img_data)).convert('RGB')
    except Exception as e:
        print(f'[art/itunes] {e}', file=sys.stderr)
    return None


def genre_color(genre):
    """Fallback: solid color based on genre."""
    g = genre.lower()
    if 'dubstep' in g or 'bass' in g:  return (10, 0, 30)
    if 'jazz' in g:                     return (20, 10, 0)
    if 'classical' in g:                return (0, 10, 20)
    if 'electronic' in g:               return (0, 20, 10)
    return (10, 10, 10)


def get_album_art(info):
    """Try all art sources, return a 45x35 PIL image."""
    img = None

    # 1. Embedded
    img = art_from_file(info['filename'])
    if img:
        print(f'[art] embedded cover from file')

    # 2. MusicBrainz
    if img is None:
        img = art_from_musicbrainz(info['artist'], info['album'])
        if img:
            print(f'[art] cover from MusicBrainz')

    # 3. iTunes
    if img is None:
        img = art_from_itunes(info['artist'], info['title'])
        if img:
            print(f'[art] cover from iTunes')

    # 4. Solid color fallback
    if img is None:
        print(f'[art] no cover found, using genre color fallback')
        img = Image.new('RGB', (FT_W, FT_H), genre_color(info.get('genre', '')))
        return img

    # Center-crop to 45x35 (fill, don't letterbox)
    return ImageOps.fit(img, (FT_W, FT_H), Image.LANCZOS)


# ── FT rendering & sending ────────────────────────────────────────────────────

def send_ppm(img, layer):
    header = f'P6\n{FT_W} {FT_H}\n#FT: 0 0 {layer}\n255\n'.encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(header + img.tobytes(), (FT_HOST, FT_PORT))
    s.close()


def render_text_overlay(artist, title, show, scroll_x):
    """Layer 1: scrolling text on transparent (black) background."""
    img  = Image.new('RGB', (FT_W, FT_H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

    def draw_row(text, y, color):
        if not text:
            return
        text_w = len(text) * CHAR_W
        if text_w <= FT_W:
            x = (FT_W - text_w) // 2
            draw.text((x, y), text, fill=color, font=font)
        else:
            gap    = 8
            period = text_w + gap
            x0     = -(scroll_x % period)
            draw.text((x0,          y), text, fill=color, font=font)
            draw.text((x0 + period, y), text, fill=color, font=font)

    draw_row(artist, ROW_ARTIST, COLOR_ARTIST)
    draw_row(title,  ROW_TITLE,  COLOR_TITLE)
    draw_row(show,   ROW_SHOW,   COLOR_SHOW)
    return img


def main():
    print(f'ft_nowplaying: FT={FT_HOST}:{FT_PORT}  LS={LS_HOST}:{LS_PORT}')

    current_info = None
    scroll_x     = 0
    last_poll    = 0
    art_layer0   = None  # current background art image

    while True:
        now = time.time()

        if now - last_poll >= POLL_INTERVAL:
            info      = get_now_playing()
            last_poll = now
            if info and info['rid'] != (current_info or {}).get('rid'):
                current_info = info
                print(f"Now playing: {info['artist']} — {info['title']} [{info['genre']}]")
                art = get_album_art(info)
                send_ppm(art, layer=0)
                print(f'[art] pushed to layer 0')

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nExiting.')
