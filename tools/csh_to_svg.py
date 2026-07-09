#!/usr/bin/env python3
"""
csh_to_svg.py  --  Extract vector shapes from Adobe Photoshop Custom Shape files
                   (.csh, magic "cush") into individual SVG files.

The WipEout HD Fury "Shapes Mega Pack" by Liger-Inuzuka ships its sponsor, track
and racing/mode emblem artwork as Photoshop custom shapes. No mainstream tool on
Linux reads .csh, so this parser decodes the binary format directly:

  Header:   "cush"  uint32 version(=2)  uint32 shapeCount
  Per shape:
      uint32 nameLen (UTF-16 code units)
      UTF-16BE name (NUL-terminated inside the count)
      10-byte gap    (flags + record-block length)
      '$' + 36-char ASCII UUID
      int32 x4        bounding box  (top, left, bottom, right)
      path records    26 bytes each, Photoshop vector-path record format:
          uint16 selector  (0/3 subpath-length, 1/2/4/5 bezier knot, 6 fill, 8 initfill)
          knot = 3 points (preceding-ctrl, anchor, leaving-ctrl), each a
                 (vertical, horizontal) pair of 8.24 signed fixed-point numbers,
                 normalised 0..1 within the bounding box.

Custom shapes are single-colour by definition, so output is a solid-fill SVG.

Usage:
    python3 csh_to_svg.py input.csh out_dir/ [--fill "#000000"] [--prefix ""]

Writes one <slug>.svg per shape and prints "slug<TAB>original name" lines
so the caller can map / categorise them.
"""
import sys, os, struct, re, argparse


def f824(b):
    return struct.unpack(">i", b)[0] / (1 << 24)


UUID_RE = re.compile(rb"\$[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     rb"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def recover_name(data, uuid_start):
    """Walk backward from the '$' to recover [uint32 len][UTF-16BE name][gap]."""
    for L in range(1, 60):
        for gap in (8, 10, 12):
            s = uuid_start - gap - 2 * L
            lf = s - 4
            if lf < 0:
                continue
            if struct.unpack(">I", data[lf:lf + 4])[0] == L:
                try:
                    nm = data[s:s + 2 * L].decode("utf-16-be")
                except UnicodeDecodeError:
                    continue
                clean = nm.rstrip("\x00")
                if clean and all(c.isprintable() and ord(c) < 128 for c in clean):
                    return clean
    return None


def parse(data):
    assert data[:4] == b"cush", "not a Photoshop custom-shape file"
    shapes = []
    matches = list(UUID_RE.finditer(data))
    for i, m in enumerate(matches):
        name = recover_name(data, m.start()) or f"shape_{i}"
        off = m.start() + 37                      # past '$' + 36 uuid chars
        bounds = struct.unpack(">4i", data[off:off + 16]); off += 16
        top, left, bottom, right = bounds
        w = max(1, right - left)
        h = max(1, bottom - top)
        region_end = matches[i + 1].start() - 60 if i + 1 < len(matches) else len(data)
        subpaths = []
        cur = []
        p = off
        while p + 26 <= len(data) and p < region_end + 26:
            sel = struct.unpack(">H", data[p:p + 2])[0]
            if sel > 8:
                break
            if sel in (0, 3):                     # new subpath length record
                if cur:
                    subpaths.append(cur); cur = []
            elif sel in (1, 2, 4, 5):             # bezier knot
                v = [f824(data[p + 2 + k:p + 6 + k]) for k in range(0, 24, 4)]
                # stored vertical,horizontal -> (x,y) pairs
                pre = (v[1], v[0]); anc = (v[3], v[2]); leav = (v[5], v[4])
                cur.append((pre, anc, leav))
            p += 26
        if cur:
            subpaths.append(cur)
        shapes.append({"name": name, "w": w, "h": h, "subpaths": subpaths})
    return shapes


def shape_to_svg(sh, fill="#000000"):
    w, h = sh["w"], sh["h"]
    parts = []
    for sp in sh["subpaths"]:
        if not sp:
            continue
        anc0 = sp[0][1]
        parts.append(f"M{anc0[0] * w:.2f} {anc0[1] * h:.2f}")
        for i in range(len(sp)):
            c1 = sp[i][2]                         # leaving ctrl of current
            nxt = sp[(i + 1) % len(sp)]
            c2 = nxt[0]                            # preceding ctrl of next
            a = nxt[1]
            parts.append(
                f"C{c1[0] * w:.2f} {c1[1] * h:.2f} "
                f"{c2[0] * w:.2f} {c2[1] * h:.2f} "
                f"{a[0] * w:.2f} {a[1] * h:.2f}"
            )
        parts.append("Z")
    d = " ".join(parts)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}">'
            f'<path fill="{fill}" fill-rule="evenodd" d="{d}"/></svg>')


def slugify(name):
    s = name.strip().lower()
    s = s.replace("+", "plus ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "shape"


def convert(inp, out_dir, fill="#000000", prefix=""):
    data = open(inp, "rb").read()
    shapes = parse(data)
    os.makedirs(out_dir, exist_ok=True)
    used = {}
    rows = []
    for sh in shapes:
        slug = prefix + slugify(sh["name"])
        used[slug] = used.get(slug, 0) + 1
        if used[slug] > 1:
            slug = f"{slug}-{used[slug]}"
        with open(os.path.join(out_dir, slug + ".svg"), "w") as f:
            f.write(shape_to_svg(sh, fill))
        rows.append((slug, sh["name"]))
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("out_dir")
    ap.add_argument("--fill", default="#000000")
    ap.add_argument("--prefix", default="")
    a = ap.parse_args()
    for slug, name in convert(a.input, a.out_dir, a.fill, a.prefix):
        print(f"{slug}\t{name}")
