#!/usr/bin/env python3
"""
layered_ai_to_svg.py -- Split a single layered Adobe Illustrator PDF (where each
glyph/logo is its own named layer) into individual, correctly-coloured SVGs.

Illustrator stores each layer as a marked-content block in the page content stream:
    /OC /MCn BDC  … drawing ops …  EMC
and the page's Resources/Properties maps  /MCn -> an OCG (layer) with a name.

Two MuPDF quirks make this fiddly (see CLAUDE.md):
  * set_layer()/OCG toggling is NOT honoured when rendering this kind of file, and
  * rewriting the content stream to a single block renders the shape but can LOSE
    fill colours for some layers.
So we isolate each block only to recover its NAME + page bounding box, then crop the
*unmodified* (full-colour) page to that bbox for the actual export.

A layer that bundles several glyphs (e.g. a "weapons" sheet) is split spatially.

Usage:
    python3 layered_ai_to_svg.py input.ai out_dir/
Requires: pymupdf, cairosvg
"""
import sys, os, re, io, argparse
import fitz, cairosvg
from PIL import Image


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "layer"


def _tighten(svg, pad=4):
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=int(vb[2] * 3))
    bb = Image.open(io.BytesIO(png)).split()[-1].getbbox()
    if not bb:
        return svg
    x0, y0, x1, y1 = [v / 3 for v in bb]
    vx0, vy0, vw, vh = vb[0] + x0 - pad, vb[1] + y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad

    def seta(t, n, v):
        if re.search(rf'\b{n}="[^"]*"', t):
            return re.sub(rf'\b{n}="[^"]*"', f'{n}="{v}"', t, 1)
        return t[:-1] + f' {n}="{v}">'
    tag = re.search(r"<svg\b[^>]*>", svg).group(0)
    nt = seta(tag, "viewBox", f"{vx0:.2f} {vy0:.2f} {vw:.2f} {vh:.2f}")
    nt = seta(seta(nt, "width", f"{vw:.0f}"), "height", f"{vh:.0f}")
    return svg.replace(tag, nt, 1)


def _export_region(src, rect, path, pad=6):
    d = fitz.open(src)
    cb = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad) & d[0].mediabox
    d[0].set_cropbox(cb)
    open(path, "w").write(_tighten(d[0].get_svg_image()))


def _layer_bbox(src, preamble, tag, body, dpi=200):
    new = (preamble + f"/OC /{tag} BDC" + body + "EMC").encode("latin1")
    d = fitz.open(src)
    cxs = d[0].get_contents()
    d.update_stream(cxs[0], new)
    for e in cxs[1:]:
        d.update_stream(e, b" ")
    pix = d[0].get_pixmap(dpi=dpi, alpha=True)
    bb = Image.open(io.BytesIO(pix.tobytes("png"))).split()[-1].getbbox()
    if not bb:
        return None
    s = dpi / 72.0
    return fitz.Rect(bb[0] / s, bb[1] / s, bb[2] / s, bb[3] / s)


def _spatial_split(src, region, pad=10):
    d = fitz.open(src)
    boxes = [fitz.Rect(it["rect"]) for it in d[0].get_drawings()
             if it["rect"][2] > it["rect"][0] and fitz.Rect(it["rect"]).x0 >= region.x0 - 2
             and fitz.Rect(it["rect"]).y0 >= region.y0 - 2]
    n = len(boxes); parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    exp = [fitz.Rect(b.x0 - pad, b.y0 - pad, b.x1 + pad, b.y1 + pad) for b in boxes]
    for i in range(n):
        for j in range(i + 1, n):
            if exp[i].intersects(exp[j]):
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    rects = []
    for idxs in groups.values():
        r = fitz.Rect(boxes[idxs[0]])
        for k in idxs[1:]:
            r |= boxes[k]
        rects.append(r)
    rects.sort(key=lambda r: (round(r.y0 / 80), r.x0))
    return rects


def convert(src, out_dir, multi_glyph_layers=("weapons",)):
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(src)
    ocgs = doc.get_ocgs()
    props = doc.xref_get_key(doc[0].xref, "Resources/Properties")[1]
    tag2name = {m.group(1): ocgs[int(m.group(2))]["name"]
                for m in re.finditer(r"/(MC\d+)\s+(\d+)\s+0\s+R", props)}
    raw = b"".join(doc.xref_stream(c) for c in doc[0].get_contents()).decode("latin1")
    blocks = list(re.finditer(r"/OC\s*/(MC\d+)\s*BDC(.*?)EMC", raw, re.S))
    preamble = raw[:blocks[0].start()]
    out = []
    for b in blocks:
        name = tag2name[b.group(1)]
        bbox = _layer_bbox(src, preamble, b.group(1), b.group(2))
        if bbox is None:
            continue
        if name in multi_glyph_layers:
            for i, r in enumerate(_spatial_split(src, bbox)):
                p = os.path.join(out_dir, f"{slugify(name)}-{i+1}.svg")
                _export_region(src, r, p); out.append((f"{name} #{i+1}", p))
        else:
            p = os.path.join(out_dir, f"{slugify(name)}.svg")
            _export_region(src, bbox, p); out.append((name, p))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input"); ap.add_argument("out_dir")
    ap.add_argument("--multi", nargs="*", default=["weapons"],
                    help="layer names that contain multiple glyphs to split spatially")
    a = ap.parse_args()
    for name, path in convert(a.input, a.out_dir, tuple(a.multi)):
        print(f"{name}\t{path}")
