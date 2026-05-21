#!/usr/bin/env python3
"""Generate 45x35 Mooninite pixel art PNGs for FlaschenTaschen."""

from PIL import Image

FT_W, FT_H = 45, 35

# Colors
BLACK   = (0, 0, 0)
GREEN   = (0, 230, 0)       # Ignignokt
DGREEN  = (0, 180, 0)       # Ignignokt shadow/detail
PINK    = (230, 50, 180)    # Err
DPINK   = (180, 30, 140)    # Err shadow/detail
WHITE   = (255, 255, 255)
EYE     = (255, 255, 255)
PUPIL   = (0, 0, 0)

def draw_sprite(img, sprite, ox, oy):
    """Draw a sprite (list of (x, y, color) tuples) offset by ox, oy."""
    for x, y, color in sprite:
        px, py = ox + x, oy + y
        if 0 <= px < FT_W and 0 <= py < FT_H:
            img.putpixel((px, py), color)

def rect(x, y, w, h, color):
    """Generate pixel list for a filled rectangle."""
    return [(x + dx, y + dy, color) for dy in range(h) for dx in range(w)]


def make_ignignokt():
    """Ignignokt — the tall square one."""
    pixels = []
    G = GREEN
    D = DGREEN

    # Head/body is one big rectangle — 12 wide, 22 tall
    # He's very blocky, head blends into body
    pixels += rect(0, 0, 12, 22, G)

    # Flat-top "cap" extends 1px each side
    pixels += rect(-1, 0, 14, 2, G)

    # Eyes — 2x2 white with 1x1 dark pupil, row 4
    pixels += rect(2, 4, 2, 2, EYE)
    pixels += rect(8, 4, 2, 2, EYE)
    pixels += [(3, 5, PUPIL)]   # left pupil (looking right)
    pixels += [(9, 5, PUPIL)]   # right pupil

    # Mouth — horizontal line, row 8
    pixels += rect(3, 9, 6, 1, D)

    # Belt/waist detail — row 14
    pixels += rect(0, 14, 12, 1, D)

    # Legs — split at bottom, rows 22-25
    pixels += rect(1, 22, 4, 4, G)
    pixels += rect(7, 22, 4, 4, G)

    # Feet — wider, row 26-27
    pixels += rect(0, 26, 5, 2, G)
    pixels += rect(7, 26, 5, 2, G)

    # Arm left — extending out, rows 11-13
    pixels += rect(-3, 11, 3, 2, G)
    pixels += rect(-4, 12, 1, 1, G)

    # Arm right — raised middle finger pose (iconic)
    pixels += rect(12, 10, 3, 2, G)
    pixels += rect(15, 8, 2, 2, G)
    # The finger
    pixels += rect(15, 5, 2, 3, G)

    return pixels


def make_err():
    """Err — the small angular one."""
    pixels = []
    P = PINK
    D = DPINK

    # Err is diamond/angular shaped — build him row by row
    # Head — pointed top
    pixels += rect(3, 0, 2, 1, P)
    pixels += rect(2, 1, 4, 1, P)
    pixels += rect(1, 2, 6, 1, P)
    pixels += rect(0, 3, 8, 1, P)

    # Face area — rows 4-7
    pixels += rect(0, 4, 8, 4, P)

    # Eyes — row 4-5
    pixels += rect(1, 4, 2, 2, EYE)
    pixels += rect(5, 4, 2, 2, EYE)
    pixels += [(2, 5, PUPIL)]
    pixels += [(6, 5, PUPIL)]

    # Mouth — row 7
    pixels += rect(2, 7, 4, 1, D)

    # Body narrows — rows 8-11
    pixels += rect(0, 8, 8, 1, P)
    pixels += rect(1, 9, 6, 1, P)
    pixels += rect(1, 10, 6, 1, P)
    pixels += rect(1, 11, 6, 1, P)

    # Belt detail
    pixels += rect(1, 9, 6, 1, D)

    # Body widens again
    pixels += rect(0, 12, 8, 2, P)

    # Legs — rows 14-17
    pixels += rect(1, 14, 2, 3, P)
    pixels += rect(5, 14, 2, 3, P)

    # Feet
    pixels += rect(0, 17, 3, 1, P)
    pixels += rect(5, 17, 3, 1, P)

    # Arms — pointing out angular
    pixels += rect(-2, 6, 2, 2, P)
    pixels += rect(-3, 5, 1, 2, P)
    pixels += rect(8, 6, 2, 2, P)
    pixels += rect(10, 5, 1, 2, P)

    return pixels


def generate():
    img = Image.new('RGB', (FT_W, FT_H), BLACK)

    ignignokt = make_ignignokt()
    err = make_err()

    # Position: Ignignokt on left, Err on right (shorter, so lower)
    draw_sprite(img, ignignokt, ox=5, oy=3)
    draw_sprite(img, err, ox=30, oy=13)

    img.save('mooninites.png')
    print('Saved mooninites.png (45x35)')

    # Also save a 10x upscale for preview
    preview = img.resize((FT_W * 10, FT_H * 10), Image.NEAREST)
    preview.save('mooninites_preview.png')
    print('Saved mooninites_preview.png (450x350 preview)')


if __name__ == '__main__':
    generate()
