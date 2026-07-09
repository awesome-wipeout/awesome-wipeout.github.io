#!/usr/bin/env python3
"""
ai_to_svg.py  --  Extract vector artwork from legacy Adobe Illustrator / CorelDRAW
                  ".ai" files whose PDF page is empty and whose real artwork lives
                  in the native Illustrator private-data stream (AI5 / PostScript).

Many WipEout fan logo packs (toolboxio's Wip3out & 2097 sets) were exported from
CorelDRAW as .ai files that render blank in every normal PDF/SVG converter, because
the visible PDF content stream is empty and the actual paths are stored in the
"AIPrivateData" object as classic Illustrator PostScript path operators.

This tool decodes that stream and rebuilds proper SVG paths.

Usage:
    python3 ai_to_svg.py input.ai output.svg [--fill "#000000"]

Requires: pymupdf  (pip install pymupdf)
"""
import sys, re, argparse
import fitz  # pymupdf


def find_ai_postscript(path):
    """Return the decoded Illustrator private-data PostScript, or None."""
    doc = fitz.open(path)
    for x in range(1, doc.xref_length()):
        if doc.xref_is_stream(x):
            try:
                raw = doc.xref_stream(x)
            except Exception:
                continue
            if raw[:2] == b"%!":
                return raw.decode("latin1")
    return None


def _fill_hex(fill, force_fill=None):
    if force_fill:
        return force_fill
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255))) for c in fill)


def cmyk_to_rgb(c, m, y, k):
    r = 255 * (1 - c) * (1 - k)
    g = 255 * (1 - m) * (1 - k)
    b = 255 * (1 - y) * (1 - k)
    return (r, g, b)


def parse_ai(ps, force_fill=None):
    """Parse AI5 path operators -> list of (fill_hex, [subpath_d,...])."""
    toks = re.findall(r"[-+]?\d*\.?\d+(?:e[-+]?\d+)?|[A-Za-z*]+", ps)
    nums = []
    cur = ""            # current subpath d-string
    subpaths = []       # accumulated subpaths since last paint
    out = []            # (fill, [d,...])
    fill = (0, 0, 0)
    in_comp = False     # inside a *u ... *U compound path
    comp = []           # subpaths accumulated across the whole compound
    comp_fill = None
    minx = miny = float("inf")
    maxx = maxy = float("-inf")

    def note(x, y):
        nonlocal minx, miny, maxx, maxy
        minx = min(minx, x); maxx = max(maxx, x)
        miny = min(miny, y); maxy = max(maxy, y)

    def close_cur():
        nonlocal cur
        if cur:
            subpaths.append(cur + "Z")
            cur = ""

    for t in toks:
        # number?
        if re.fullmatch(r"[-+]?\d*\.?\d+(?:e[-+]?\d+)?", t):
            try:
                nums.append(float(t))
            except ValueError:
                pass
            continue
        # operator
        if t == "m" and len(nums) >= 2:
            close_cur()
            x, y = nums[-2], nums[-1]; note(x, y)
            cur = f"M{x:.3f} {y:.3f} "
        elif t in ("L", "l") and len(nums) >= 2:
            x, y = nums[-2], nums[-1]; note(x, y)
            cur += f"L{x:.3f} {y:.3f} "
        elif t in ("C", "c") and len(nums) >= 6:
            x1, y1, x2, y2, x3, y3 = nums[-6:]
            note(x3, y3)
            cur += f"C{x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f} {x3:.3f} {y3:.3f} "
        elif t in ("V", "v") and len(nums) >= 4:   # ctrl1 = current point
            x2, y2, x3, y3 = nums[-4:]
            note(x3, y3)
            cur += f"S{x2:.3f} {y2:.3f} {x3:.3f} {y3:.3f} "
        elif t in ("Y", "y") and len(nums) >= 4:   # ctrl2 = endpoint
            x1, y1, x3, y3 = nums[-4:]
            note(x3, y3)
            cur += f"C{x1:.3f} {y1:.3f} {x3:.3f} {y3:.3f} {x3:.3f} {y3:.3f} "
        elif t == "Xa" and len(nums) >= 3:         # RGB fill (0..1)
            fill = tuple(nums[-3:])
        elif t == "g" and len(nums) >= 1:          # gray fill
            fill = (nums[-1], nums[-1], nums[-1])
        elif t == "k" and len(nums) >= 4:          # CMYK fill (0..1)
            r, g, b = cmyk_to_rgb(*nums[-4:])
            fill = (r / 255.0, g / 255.0, b / 255.0)
        elif t == "*u":                            # begin compound path
            close_cur()
            if subpaths and not in_comp:           # flush anything pending
                out.append((_fill_hex(fill, force_fill), subpaths[:]))
            subpaths.clear()
            in_comp = True; comp = []; comp_fill = None
        elif t == "*U":                            # end compound path
            close_cur()
            if subpaths:
                comp.extend(subpaths); subpaths.clear()
                if comp_fill is None:
                    comp_fill = fill
            if comp:
                out.append((_fill_hex(comp_fill or fill, force_fill), comp[:]))
            comp = []; comp_fill = None; in_comp = False
        elif t in ("f", "F", "b", "B"):            # fill (and close)
            close_cur()
            if in_comp:
                # inside a compound: gather subpaths, defer painting to *U
                if subpaths and comp_fill is None:
                    comp_fill = fill
                comp.extend(subpaths); subpaths.clear()
            else:
                if subpaths:
                    out.append((_fill_hex(fill, force_fill), subpaths[:]))
                subpaths.clear()
        elif t in ("s", "S", "n", "N"):            # stroke-only / no-paint
            close_cur()
            if in_comp:
                comp.extend(subpaths); subpaths.clear()   # geometry still part of compound
            else:
                subpaths.clear()                          # discard stroke-only art
        nums = []
    # trailing
    close_cur()
    if comp:
        out.append((_fill_hex(comp_fill or fill, force_fill), comp[:]))
    if subpaths:
        out.append((_fill_hex(fill, force_fill), subpaths[:]))
    return out, (minx, miny, maxx, maxy)


def build_svg(paths, bounds, force_fill=None):
    minx, miny, maxx, maxy = bounds
    W = maxx - minx
    H = maxy - miny
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.3f} {H:.3f}" '
        f'width="{W:.1f}" height="{H:.1f}">',
        # flip AI (y-up) to SVG (y-down) and translate to origin
        f'<g transform="matrix(1 0 0 -1 {-minx:.3f} {maxy:.3f})">',
    ]
    for hexc, subs in paths:
        d = "".join(subs)
        lines.append(f'<path fill="{hexc}" fill-rule="evenodd" d="{d.strip()}"/>')
    lines.append("</g></svg>")
    return "\n".join(lines)


def convert(inp, outp, force_fill=None):
    ps = find_ai_postscript(inp)
    if ps is None:
        raise SystemExit(f"No Illustrator private-data stream found in {inp}")
    paths, bounds = parse_ai(ps, force_fill)
    if not paths:
        raise SystemExit(f"No paths parsed from {inp}")
    svg = build_svg(paths, bounds, force_fill)
    with open(outp, "w") as f:
        f.write(svg)
    return len(paths)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--fill", default=None, help="force a single fill colour, e.g. #000000")
    a = ap.parse_args()
    n = convert(a.input, a.output, a.fill)
    print(f"{a.input} -> {a.output}  ({n} fills)")
