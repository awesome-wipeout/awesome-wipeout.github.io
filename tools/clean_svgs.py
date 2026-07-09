#!/usr/bin/env python3
"""
clean_svgs.py -- normalise committed logo SVGs in place.

Some source SVGs (extracted from combined/layered art) still carry geometry that
sits OUTSIDE the cropped viewBox — neighbouring logos or stray sub-paths that are
only hidden because the viewBox clips them. They bloat the file and leak into any
tool that shows overflow. This script removes them *safely*:

  1. Render the SVG at its native viewBox -> reference alpha mask (the visible logo).
  2. For every drawable element, remove it and re-render. If the visible mask is
     byte-for-byte identical, the element contributed nothing inside the frame, so
     the removal is kept; otherwise it is restored. (This self-protects: anything
     that touches the visible artwork — including clip/def dependencies — is kept.)
  3. Vacuum now-empty <g>/<defs>, editor cruft (inkscape:* attrs/namespaces,
     sodipodi, metadata, comments).
  4. Verify: the native-viewBox render after cleaning must equal the reference.

Nothing here regenerates PNG/PDF — run tools/build.py afterwards for that.

Usage:
    python3 tools/clean_svgs.py logos/weapons/shield.svg [more.svg ...]
    python3 tools/clean_svgs.py --all           # every logos/**/*.svg
    python3 tools/clean_svgs.py --vacuum-only ... # skip the render-cull, cruft only
"""
import sys, io, os, glob, re
from lxml import etree
import cairosvg
from PIL import Image, ImageChops

DRAW = {"path", "polygon", "polyline", "rect", "circle", "ellipse",
        "use", "line", "text", "image"}
CRUFT_NS = ("inkscape", "sodipodi")
W = 512  # render width for the visible-mask comparison


def ln(tag):
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def render(root):
    png = cairosvg.svg2png(bytestring=etree.tostring(root), output_width=W)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _flat(img, bg):
    b = Image.new("RGB", img.size, bg)
    b.paste(img, mask=img.split()[-1])
    return b


def same(a, b):
    # Composite over BOTH black and white before diffing. Comparing RGBA directly is a
    # trap: the difference image's alpha is ~0 everywhere, and Image.getbbox() treats
    # alpha-0 pixels as empty, so pure colour changes (opaque detail on an opaque
    # silhouette) would wrongly read as "identical". Flattening exposes colour AND
    # coverage changes on an alpha-free RGB image.
    if a.size != b.size:
        return False
    for bg in ((0, 0, 0), (255, 255, 255)):
        if ImageChops.difference(_flat(a, bg), _flat(b, bg)).getbbox() is not None:
            return False
    return True


def cull_outside(root, ref):
    removed = 0
    for e in list(root.iter()):
        if ln(e.tag) not in DRAW:
            continue
        p = e.getparent()
        if p is None:
            continue
        i = p.index(e)
        p.remove(e)
        try:
            if same(ref, render(root)):
                removed += 1
                continue
        except Exception:
            pass
        p.insert(i, e)  # restore
    return removed


def vacuum(root):
    # drop editor-only attributes / namespaces
    for e in root.iter():
        for a in list(e.attrib):
            q = etree.QName(a)
            if q.namespace and any(n in (q.namespace or "") for n in CRUFT_NS):
                del e.attrib[a]
            if q.localname in ("groupmode", "label") or "inkscape" in a or "sodipodi" in a:
                e.attrib.pop(a, None)
    # remove metadata / comments / empty groups+defs (repeat until stable)
    changed = True
    while changed:
        changed = False
        for e in list(root.iter()):
            l = ln(e.tag)
            p = e.getparent()
            if p is None:
                continue
            if l in ("metadata",):
                p.remove(e); changed = True
            elif l in ("g", "defs") and len(e) == 0 and not (e.text and e.text.strip()):
                p.remove(e); changed = True
    for c in root.xpath("//comment()"):
        c.getparent().remove(c)


def clean(path, vacuum_only=False):
    tree = etree.parse(path)
    root = tree.getroot()
    ref = render(root)
    removed = 0 if vacuum_only else cull_outside(root, ref)
    vacuum(root)
    if not same(ref, render(root)):
        return None  # refuse to write — visible artwork changed
    before = os.path.getsize(path)
    tree.write(path, xml_declaration=False, encoding="utf-8")
    return removed, before, os.path.getsize(path)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    files = sorted(glob.glob("logos/**/*.svg", recursive=True)) if "--all" in flags else args
    tot_rm = tot_saved = 0
    for f in files:
        r = clean(f, vacuum_only="--vacuum-only" in flags)
        if r is None:
            print(f"!! SKIPPED (render changed): {f}")
            continue
        rm, b, a = r
        tot_rm += rm; tot_saved += (b - a)
        tag = f"-{rm} elems, " if rm else ""
        print(f"  {tag}{b:>7} -> {a:>7}  {f}")
    print(f"== removed {tot_rm} stray elements, saved {tot_saved} bytes across {len(files)} files ==")
