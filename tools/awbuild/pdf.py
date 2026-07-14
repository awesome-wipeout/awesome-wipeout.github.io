from awbuild.core import *


# ---------------------------------------------------------------------------
# Vector PDF tear sheet
# ---------------------------------------------------------------------------
# Composes each page as an SVG that *nests* the real logo SVGs (with per-asset
# namespaced ids so internal clip/use references don't collide), renders each
# page to PDF with cairosvg (keeping everything vector), and stitches the pages
# with PyMuPDF. Designers can open tearsheet.pdf and copy/paste logos as vectors.
PAGE_W, PAGE_H, MARGIN = 1240, 1754, 48
PDF_COLS, GUTTER = 5, 16
THUMB_H, LABEL_H = 150, 24


# The tear-sheet labels/headings are outlined to curves (no font is embedded in the PDF).
# The font is BUNDLED in the repo (tools/fonts/) so the whole build — PDF included — is
# self-contained and deterministic on macOS/Windows/Linux, with no system-font dependency
# and no CI. System paths are kept only as a fallback. First existing candidate wins.
_BUNDLED_FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")  # root/tools/fonts
_FONT_CANDIDATES = {
    False: [  # regular
        os.path.join(_BUNDLED_FONTS, "DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
    True: [   # bold
        os.path.join(_BUNDLED_FONTS, "DejaVuSans-Bold.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
}
_FONTS = {}


def _pdf_font_file(bold):
    for p in _FONT_CANDIDATES[bold]:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        "no tear-sheet font found — the bundled tools/fonts/DejaVuSans"
        + ("-Bold" if bold else "") + ".ttf is missing")


def _load_font(bold=False):
    if bold not in _FONTS:
        from fontTools.ttLib import TTFont
        path, _, num = _pdf_font_file(bold).partition("::")
        f = TTFont(path, fontNumber=int(num)) if num else TTFont(path)
        _FONTS[bold] = (f.getGlyphSet(), f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
    return _FONTS[bold]


def _text_width(text, size, bold=False):
    _, cmap, hmtx, upm = _load_font(bold)
    sc = size / upm
    return sum(hmtx[cmap.get(ord(c)) or cmap.get(ord("?"))][0] * sc for c in text)


def _text_svg(text, x, baseline, size, fill, bold=False, anchor="start"):
    """Return an SVG <path> of `text` outlined to vector curves (no font)."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    gs, cmap, hmtx, upm = _load_font(bold)
    sc = size / upm
    if anchor == "middle":
        x -= _text_width(text, size, bold) / 2
    spen = SVGPathPen(gs)
    penx = x
    for ch in text:
        g = cmap.get(ord(ch)) or cmap.get(ord("?"))
        rec = DecomposingRecordingPen(gs)
        gs[g].draw(rec)
        rec.replay(TransformPen(spen, (sc, 0, 0, -sc, penx, baseline)))
        penx += hmtx[g][0] * sc
    return f'<path d="{spen.getCommands()}" fill="{fill}"/>'


def _clean_svg(text):
    """Remove clip-paths and any off-canvas (clipped-away) geometry so the asset
    is just its own visible paths — no clip groups, no hidden bloat."""
    m = re.search(r'viewBox="([^"]+)"', text)
    if not m:
        return text
    vx0, vy0, vw, vh = [float(v) for v in m.group(1).split()]
    vx1, vy1 = vx0 + vw, vy0 + vh
    mg = max(vw, vh) * 0.04
    text = re.sub(r"<clipPath[^>]*>.*?</clipPath>", "", text, flags=re.S)
    text = re.sub(r'\sclip-path="[^"]*"', "", text)

    def keep(mm):
        el = mm.group(0)
        dm = re.search(r'\b(?:d|points)="([^"]*)"', el)
        if not dm:
            return el
        n = [float(v) for v in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", dm.group(1))]
        xs, ys = n[0::2], n[1::2]
        if not xs:
            return el
        tm = re.search(r'transform="matrix\(([^)]+)\)"', el)
        if tm:
            a, b, c, d, e, f = [float(v) for v in re.split(r"[ ,]+", tm.group(1).strip())]
            X = [a * px + c * py + e for px, py in zip(xs, ys)]
            Y = [b * px + d * py + f for px, py in zip(xs, ys)]
        else:
            X, Y = xs, ys
        if max(X) < vx0 - mg or min(X) > vx1 + mg or max(Y) < vy0 - mg or min(Y) > vy1 + mg:
            return ""
        return el
    text = re.sub(r"<path\b[^>]*/>", keep, text)
    text = re.sub(r"<polygon\b[^>]*/>", keep, text)
    return text


def _inline_asset(svg_text, x, y, w, h, pfx):
    """Namespace an asset SVG, strip any clip (safe — source SVGs are already
    de-bloated) and wrap it in a positioned <g> (aspect-fit, no clip) so it
    becomes one directly-selectable group on the page."""
    t = re.sub(r"<clipPath[^>]*>.*?</clipPath>", "", svg_text, flags=re.S)
    t = re.sub(r'\sclip-path="[^"]*"', "", t)
    t = re.sub(r"<\?xml.*?\?>", "", t, flags=re.S)
    t = re.sub(r"<!DOCTYPE.*?>", "", t, flags=re.S)
    ids = set(re.findall(r'id="([^"]+)"', t))
    if ids:
        t = re.sub(r'id="([^"]+)"', lambda m: f'id="{pfx}{m.group(1)}"', t)
        t = re.sub(r"#([A-Za-z0-9_.:\-]+)",
                   lambda m: f"#{pfx}{m.group(1)}" if m.group(1) in ids else m.group(0), t)
    m = re.search(r"<svg\b[^>]*>", t)
    if not m:
        return ""
    vb = re.search(r'viewBox="([^"]+)"', m.group(0))
    vx0, vy0, vw, vh = ([float(v) for v in vb.group(1).split()] if vb else [0, 0, 100, 100])
    inner = t[m.end():t.rfind("</svg>")]
    # drop editor-only namespaced attrs (inkscape:, sodipodi:, …) whose xmlns we dropped
    inner = re.sub(r'\s(?!xlink:)[A-Za-z][\w-]*:[\w-]+="[^"]*"', "", inner)
    # nested <svg> sized to the *fitted* logo (no letterbox) so its viewport clips
    # exactly to the artwork — no neighbour bleed — and reads back as one
    # directly-selectable group.
    s = min(w / vw, h / vh)
    dw, dh = vw * s, vh * s
    nx, ny = x + (w - dw) / 2, y + (h - dh) / 2
    return (f'<svg x="{nx:.2f}" y="{ny:.2f}" width="{dw:.2f}" height="{dh:.2f}" '
            f'viewBox="{vx0} {vy0} {vw} {vh}" preserveAspectRatio="none">{inner}</svg>')


def build_pdf_tearsheet(manifest):
    """Compose a multi-page vector tear sheet from the (clip-free) asset SVGs.

    Each logo is inlined as one positioned <g> group — no clip paths, no Form
    XObjects — so in Illustrator you can click a glyph and select it directly.
    Card backgrounds and outlined labels/headings are drawn first (at the back);
    the logos are drawn last (on top). All text is outlined to curves, so the PDF
    embeds/references no fonts and never triggers a missing-font prompt.
    """
    import fitz
    import cairosvg
    import hashlib

    INK, MUTED, LINE, CARD = "#12151a", "#6b7280", "#e5e7eb", "#f7f8fa"
    col_w = (PAGE_W - 2 * MARGIN - (PDF_COLS - 1) * GUTTER) / PDF_COLS
    row_h = THUMB_H + LABEL_H + GUTTER
    header_h = 46
    bottom = PAGE_H - MARGIN

    pages = []                 # each: {"back": [...], "front": [...]}
    st = {"back": None, "front": None, "y": MARGIN}
    idx = 0

    def new_page():
        st["back"], st["front"] = [], []
        pages.append({"back": st["back"], "front": st["front"]})
        st["y"] = MARGIN

    new_page()
    st["back"].append(_text_svg("awesome-wipeout — WipEout vector marks", MARGIN, st["y"] + 30, 30, INK, bold=True))
    st["back"].append(_text_svg(
        f"Tear sheet — {manifest['total']} assets, {len(manifest['sections'])} categories, "
        f"updated {manifest['generated']}.  Every logo is vector — copy and paste into your design.",
        MARGIN, st["y"] + 54, 12.5, MUTED))
    st["y"] += 78

    def header(title, cont=False):
        y = st["y"]
        st["back"].append(_text_svg(title + (" (continued)" if cont else ""), MARGIN, y + 24, 18, INK, bold=True))
        st["back"].append(f'<line x1="{MARGIN}" y1="{y+34}" x2="{PAGE_W-MARGIN}" y2="{y+34}" '
                          f'stroke="{LINE}" stroke-width="1"/>')
        st["y"] += header_h

    for s in manifest["sections"]:
        if st["y"] + header_h + row_h > bottom:
            new_page()
        header(s["title"])
        col = 0
        for a in s["assets"]:
            if a.get("svg") is None:
                continue  # reference-only: no hosted vector to place on the tear sheet
            if col == 0 and st["y"] + row_h > bottom:
                new_page(); header(s["title"], cont=True)
            y = st["y"]
            x = MARGIN + col * (col_w + GUTTER)
            st["back"].append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{col_w:.2f}" height="{THUMB_H}" '
                              f'rx="8" fill="{CARD}" stroke="{LINE}" stroke-width="1"/>')
            name = a["name"]
            if len(name) > 32:
                name = name[:31] + "…"
            st["back"].append(_text_svg(name, x + col_w / 2, y + THUMB_H + 16, 10.5, INK, anchor="middle"))
            try:
                svg_text = open(os.path.join(ROOT, a["svg"])).read()
                st["front"].append(_inline_asset(svg_text, x + 14, y + 14,
                                                 col_w - 28, THUMB_H - 28, f"a{idx}_"))
            except Exception as e:
                print(f"  !! tearsheet skip {a['svg']}: {e}")
            idx += 1
            col += 1
            if col == PDF_COLS:
                col = 0; st["y"] += row_h
        if col:
            st["y"] += row_h

    master = fitz.open()
    page_svgs = []
    for p in pages:
        page_svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
                    f'xmlns:xlink="http://www.w3.org/1999/xlink" '
                    f'width="{PAGE_W}" height="{PAGE_H}" viewBox="0 0 {PAGE_W} {PAGE_H}">'
                    f'<rect width="{PAGE_W}" height="{PAGE_H}" fill="#ffffff"/>'
                    f'{"".join(p["back"])}{"".join(p["front"])}</svg>')
        page_svgs.append(page_svg)
        sub = fitz.open("pdf", cairosvg.svg2pdf(bytestring=page_svg.encode()))
        master.insert_pdf(sub)
        sub.close()
    n = master.page_count
    # Deterministic document identity. MuPDF otherwise stamps a fresh random /ID into the
    # trailer on every save, so an unchanged tear sheet would still show as modified in git
    # each build. Derive the /ID from the page content and suppress the auto-generated one,
    # so identical content ⇒ byte-identical PDF (and a real content change ⇒ a new /ID).
    doc_id = hashlib.md5("".join(page_svgs).encode()).hexdigest().upper()
    master.xref_set_key(-1, "ID", f"[ <{doc_id}> <{doc_id}> ]")
    pdf_bytes = master.tobytes(garbage=4, deflate=True, no_new_id=True)
    master.close()
    with open(os.path.join(ROOT, "tearsheet.pdf"), "wb") as f:
        f.write(pdf_bytes)
    return n


