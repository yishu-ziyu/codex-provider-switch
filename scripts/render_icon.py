#!/usr/bin/env python3
"""Render the "Codex 模型切换" app icon: dark squircle with a two-tone switch."""
import os
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 4096  # supersampled master
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

TOP = (0x2C, 0x32, 0x3B)
BOTTOM = (0x16, 0x19, 0x1E)
GREEN = (0x3F, 0xA6, 0x78)
BLUE = (0x4F, 0x82, 0xF0)
KNOB = (0xF8, 0xFA, 0xFC)


def axes(size):
    coords = (np.arange(size, dtype=np.float32) + 0.5) / size * 2.0 - 1.0
    return np.meshgrid(coords, coords)


def squircle_mask(size, exponent=5.0, scale=1.0):
    xs, ys = axes(size)
    values = (np.abs(xs / scale) ** exponent) + (np.abs(ys / scale) ** exponent)
    return np.clip((1.0 - values) * 512.0, 0.0, 1.0)


def background(size):
    t = (np.arange(size, dtype=np.float32) / (size - 1)).reshape(-1, 1)
    top = np.array(TOP, dtype=np.float32).reshape(1, 1, 3)
    bottom = np.array(BOTTOM, dtype=np.float32).reshape(1, 1, 3)
    gradient = top * (1.0 - t[..., None]) + bottom * t[..., None]

    xs, ys = axes(size)
    radial = np.exp(-(((xs / 0.85) ** 2) + ((ys / 0.85 + 0.25) ** 2)) * 1.6)
    glow = (radial * 26.0)[..., None]
    return np.clip(gradient + glow, 0, 255).astype(np.uint8)


def build_master():
    color = background(S)
    mask = squircle_mask(S)
    inner = squircle_mask(S, scale=0.982)

    alpha = (mask * 255.0).astype(np.uint8)
    rgba = np.concatenate([color, alpha[..., None]], axis=2)
    image = Image.fromarray(rgba, "RGBA")

    ring = np.clip(mask - inner, 0.0, 1.0)
    ring_layer = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    ring_layer.putalpha(Image.fromarray((ring * 46.0).astype(np.uint8), "L"))
    image = Image.alpha_composite(image, ring_layer)

    pill_w, pill_h = 0.66 * S, 0.34 * S
    x0 = (S - pill_w) / 2.0
    y0 = (S - pill_h) / 2.0
    x1, y1 = x0 + pill_w, y0 + pill_h
    radius = pill_h / 2.0

    pill_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(pill_mask).rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=255)
    left_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(left_mask).rectangle([0, 0, x0 + pill_w / 2.0, S], fill=255)

    pill = Image.new("RGBA", (S, S), BLUE + (255,))
    pill.putalpha(pill_mask)
    green_layer = Image.new("RGBA", (S, S), GREEN + (255,))
    green_layer.putalpha(ImageChops.multiply(pill_mask, left_mask))
    pill = Image.alpha_composite(pill, green_layer)

    pill_draw = ImageDraw.Draw(pill)
    pill_draw.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=radius,
        outline=(255, 255, 255, 36),
        width=max(2, int(S * 0.0045)),
    )

    knob_r = pill_h / 2.0 - S * 0.030
    knob_cx = x0 + pill_w * 0.695
    knob_cy = (y0 + y1) / 2.0
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        [knob_cx - knob_r, knob_cy - knob_r + S * 0.014, knob_cx + knob_r, knob_cy + knob_r + S * 0.014],
        fill=(0, 0, 0, 110),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.012))
    pill = Image.alpha_composite(pill, shadow)
    ImageDraw.Draw(pill).ellipse(
        [knob_cx - knob_r, knob_cy - knob_r, knob_cx + knob_r, knob_cy + knob_r],
        fill=KNOB + (255,),
    )

    image = Image.alpha_composite(image, pill)
    return image


def main():
    master = build_master()
    master_path = os.path.join(OUT_DIR, "icon-master-4096.png")
    master.save(master_path)

    preview = master.resize((1024, 1024), Image.LANCZOS)
    preview_path = os.path.join(OUT_DIR, "icon-1024.png")
    preview.save(preview_path)

    iconset = os.path.join(OUT_DIR, "AppIcon.iconset")
    os.makedirs(iconset, exist_ok=True)
    for size in (16, 32, 64, 128, 256, 512, 1024):
        resized = master.resize((size, size), Image.LANCZOS)
        resized.save(os.path.join(iconset, f"icon_{size}x{size}.png"))
    for size in (16, 32, 128, 256, 512):
        resized = master.resize((size * 2, size * 2), Image.LANCZOS)
        resized.save(os.path.join(iconset, f"icon_{size}x{size}@2x.png"))

    print(master_path)
    print(preview_path)
    print(iconset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
