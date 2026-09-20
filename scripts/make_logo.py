"""Generate the Verity mark.

Design: a deep-field gradient with a verification seal (ring) and a bold
checkmark. Built for a circular avatar crop — full-bleed background, centred
mark, generous padding, and strokes thick enough to survive ~32px.

Rendered at 4x and downsampled with LANCZOS so edges are properly antialiased.

Usage:  python scripts/make_logo.py
Output: assets/logo.png (1024), assets/logo-512.png, assets/logo-256.png,
        assets/logo.svg
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 4  # supersample factor
OUT = 1024
C = OUT * S

# Palette
BG_TOP = (10, 19, 34)
BG_BOTTOM = (23, 43, 78)
RING = (44, 74, 124)
ACCENT = (43, 227, 164)
ACCENT_DIM = (28, 150, 110)

D = S  # shorthand: multiply a 1024-space coordinate by this


def _gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(
                int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
            ),
        )
    return img


def build() -> Image.Image:
    img = _gradient(C)

    # Soft mint glow behind the mark, to lift it off the field.
    glow = Image.new("L", (C, C), 0)
    gd = ImageDraw.Draw(glow)
    cx, cy = C // 2, C // 2
    rad = int(300 * D)
    gd.ellipse([cx - rad, cy - rad + 30 * D, cx + rad, cy + rad + 30 * D], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(int(110 * D)))
    img = Image.composite(Image.new("RGB", (C, C), ACCENT_DIM), img, glow.point(lambda v: v))

    draw = ImageDraw.Draw(img)

    # Verification seal ring.
    ring_r = int(352 * D)
    ring_w = int(28 * D)
    draw.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=RING,
        width=ring_w,
    )

    # Bold checkmark. Rounded joins via joint="curve", rounded caps via the
    # endpoint ellipses.
    pts = [(int(300 * D), int(536 * D)), (int(444 * D), int(692 * D)), (int(742 * D), int(344 * D))]
    stroke = int(104 * D)
    draw.line(pts, fill=ACCENT, width=stroke, joint="curve")
    cap = stroke // 2
    for px, py in (pts[0], pts[-1]):
        draw.ellipse([px - cap, py - cap, px + cap, py + cap], fill=ACCENT)

    return img.resize((OUT, OUT), Image.LANCZOS)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" aria-label="Verity">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#0A1322"/>
      <stop offset="1" stop-color="#172B4E"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="54%" r="46%">
      <stop offset="0" stop-color="#2BE3A4" stop-opacity="0.22"/>
      <stop offset="1" stop-color="#2BE3A4" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1024" height="1024" fill="url(#bg)"/>
  <rect width="1024" height="1024" fill="url(#glow)"/>
  <circle cx="512" cy="512" r="352" fill="none" stroke="#2C4A7C" stroke-width="28"/>
  <path d="M300 536 L444 692 L742 344" fill="none" stroke="#2BE3A4"
        stroke-width="104" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def main() -> int:
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    logo = build()
    logo.save(assets / "logo.png")
    logo.resize((512, 512), Image.LANCZOS).save(assets / "logo-512.png")
    logo.resize((256, 256), Image.LANCZOS).save(assets / "logo-256.png")
    (assets / "logo.svg").write_text(SVG, encoding="utf-8")

    for name in ("logo.png", "logo-512.png", "logo-256.png", "logo.svg"):
        p = assets / name
        print(f"  {p}  ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
