"""Generate the Verity wordmark lockup (mark + name), for banners/social use.

Separate from the avatar: the avatar must work at ~32px, so it carries no text.
This lockup is the wide version used in README headers, social previews, and
docs.

Usage:  python scripts/make_banner.py
Output: assets/banner.png (1600x400), assets/banner-800.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 400
BG_TOP = (10, 19, 34)
BG_BOTTOM = (23, 43, 78)
ACCENT = (43, 227, 164)
TEXT = (233, 240, 250)
MUTED = (130, 152, 184)

# Candidate system fonts, in preference order.
FONT_BOLD = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_REG = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def load(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    print("WARNING: no TrueType font found; falling back to the bitmap default", file=sys.stderr)
    return ImageFont.load_default()


def gradient(size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    w, h = size
    for y in range(h):
        t = y / (h - 1)
        d.line(
            [(0, y), (w, y)],
            fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)),
        )
    return img


def draw_mark(img: Image.Image, cx: int, cy: int, scale: float) -> None:
    """The avatar mark, drawn at an arbitrary scale and position."""
    d = ImageDraw.Draw(img)
    ring_r = int(118 * scale)
    ring_w = max(2, int(9 * scale))
    d.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=(44, 74, 124),
        width=ring_w,
    )
    pts = [
        (cx + int(-71 * scale), cy + int(8 * scale)),
        (cx + int(-23 * scale), cy + int(60 * scale)),
        (cx + int(77 * scale), cy + int(-56 * scale)),
    ]
    stroke = max(3, int(35 * scale))
    d.line(pts, fill=ACCENT, width=stroke, joint="curve")
    cap = stroke // 2
    for px, py in (pts[0], pts[-1]):
        d.ellipse([px - cap, py - cap, px + cap, py + cap], fill=ACCENT)


def main() -> int:
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    img = gradient((W, H))
    d = ImageDraw.Draw(img)

    name_font = load(FONT_BOLD, 128)
    tag_font = load(FONT_REG, 32)

    name, tag = "Verity", "Cited ground truth for AI agents"

    # Measure rather than guess: the descender in "Verity" previously collided
    # with the tagline because positions were hard-coded.
    nb = d.textbbox((0, 0), name, font=name_font)
    tb = d.textbbox((0, 0), tag, font=tag_font)
    name_w, name_h = nb[2] - nb[0], nb[3] - nb[1]
    tag_w, tag_h = tb[2] - tb[0], tb[3] - tb[1]

    gap = 26                      # vertical gap between wordmark and tagline
    text_w = max(name_w, tag_w)
    mark_scale = 1.05
    mark_d = int(236 * mark_scale)  # mark footprint (2 x ring radius)
    spacing = 56

    total_w = mark_d + spacing + text_w
    left = (W - total_w) // 2
    mark_cx = left + mark_d // 2
    mark_cy = H // 2
    draw_mark(img, mark_cx, mark_cy, mark_scale)

    block_h = name_h + gap + tag_h
    top = (H - block_h) // 2
    text_x = left + mark_d + spacing

    # Subtract the bbox top so the glyphs land where we intend, not the padding.
    d.text((text_x, top - nb[1]), name, font=name_font, fill=TEXT)
    d.text((text_x + 3, top + name_h + gap - tb[1]), tag, font=tag_font, fill=MUTED)

    img.save(assets / "banner.png")
    img.resize((800, 200), Image.LANCZOS).save(assets / "banner-800.png")

    for n in ("banner.png", "banner-800.png"):
        p = assets / n
        print(f"  {p}  ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
