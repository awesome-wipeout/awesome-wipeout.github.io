#!/usr/bin/env python3
"""
title_ai_to_svg.py -- Convert ollite20's Adobe Illustrator title logos to tight,
transparent SVGs.

These .ai files are normal PDF-backed Illustrator art. Some carry a solid full-bleed
background panel behind the wordmark, and some use live text (fonts) for subtitles.

We therefore export with MuPDF's get_svg_image() (which preserves BOTH outlined art
and live text as glyphs), then:
  * detect any near-full-span opaque background rectangle via get_drawings()
    (colour + dimensions) and delete the matching <path> from the SVG, and
  * crop tightly to the rendered artwork by re-measuring the alpha bounds
    (no clip-path trimming, no wasted margins).

Usage: python3 title_ai_to_svg.py input.ai output.svg [--keep-bg]
Requires: pymupdf, cairosvg
"""
import sys, io, re, argparse
import fitz, cairosvg
from PIL import Image


def hexc(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in c)


def color_close(h1, h2, tol=8):
    try:
        a = tuple(int(h1[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(h2[i:i + 2], 16) for i in (1, 3, 5))
    except Exception:
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def detect_background(pg, union):
    """Return (hex_colour, width, height) of a full-span opaque bg rect, or None."""
    ua = max(1.0, union.width * union.height)
    best = None; best_frac = 0
    for it in pg.get_drawings():
        if it["fill"] is None:
            continue
        r = fitz.Rect(it["rect"])
        frac = (r.width * r.height) / ua
        spans = r.width >= 0.9 * union.width and r.height >= 0.9 * union.height
        if spans and frac >= 0.85 and frac > best_frac:
            best_frac = frac
            best = (hexc(it["fill"]), r.width, r.height)
    return best


def path_fill(p):
    m = re.search(r'fill:\s*(#[0-9a-fA-F]{3,6}|none)', p) or re.search(r'fill="([^"]+)"', p)
    return m.group(1) if m else None


def path_local_size(p):
    dm = re.search(r'\sd="([^"]*)"', p)
    if not dm:
        return 0, 0
    nums = [float(x) for x in re.findall(r'-?\d+\.?\d*', dm.group(1))]
    xs, ys = nums[0::2], nums[1::2]
    if not xs:
        return 0, 0
    return max(xs) - min(xs), max(ys) - min(ys)


def convert(inp, outp, keep_bg=False, pad=6):
    doc = fitz.open(inp)
    pg = doc[0]
    pg.set_cropbox(pg.mediabox)
    W, H = pg.rect.width, pg.rect.height

    union = None
    for it in pg.get_drawings():
        r = fitz.Rect(it["rect"])
        union = r if union is None else union | r
    if union is None:
        union = pg.rect

    bg = None if keep_bg else detect_background(pg, union)

    svg = pg.get_svg_image()

    removed = False
    if bg:
        bhex, bw, bh = bg

        def drop(m):
            nonlocal removed
            p = m.group(0)
            f = path_fill(p)
            w, h = path_local_size(p)
            if f and color_close(f, bhex) and abs(w - bw) <= 3 and abs(h - bh) <= 3:
                removed = True
                return ""
            return p
        svg = re.sub(r'<path\b[^>]*?/>', drop, svg, flags=re.S)

    # tight crop via alpha bounds of the (modified) svg
    scale = 3
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=int(W * scale))
    im = Image.open(io.BytesIO(png))
    bb = im.split()[-1].getbbox()
    x0, y0, x1, y1 = [v / scale for v in bb]
    x0 -= pad; y0 -= pad; x1 += pad; y1 += pad
    vw, vh = x1 - x0, y1 - y0

    # edit the root <svg ...> width/height/viewBox in place, preserving all
    # namespace declarations (some exports carry xmlns:inkscape / xlink prefixes)
    m = re.search(r'<svg\b[^>]*>', svg)
    tag = m.group(0)

    def setattr_(t, name, val):
        if re.search(rf'\b{name}="[^"]*"', t):
            return re.sub(rf'\b{name}="[^"]*"', f'{name}="{val}"', t, count=1)
        return t[:-1] + f' {name}="{val}">'
    new_tag = setattr_(tag, "width", f"{vw:.0f}")
    new_tag = setattr_(new_tag, "height", f"{vh:.0f}")
    new_tag = setattr_(new_tag, "viewBox", f"{x0:.2f} {y0:.2f} {vw:.2f} {vh:.2f}")
    svg = svg.replace(tag, new_tag, 1)
    with open(outp, "w") as f:
        f.write(svg)
    return removed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--keep-bg", action="store_true")
    a = ap.parse_args()
    r = convert(a.input, a.output, a.keep_bg)
    print(f"{a.output}: background {'removed' if r else 'none'}")
