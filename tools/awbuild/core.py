#!/usr/bin/env python3
"""
build.py  --  Build awesome-wipeout (the WipEout Vector Asset Library).

For every SVG under marks/ this:
  1. renders a transparent high-res PNG (longest edge = PNG_SIZE) next to it,
  2. builds an in-memory index of every asset (marks, fonts, reference),
  3. regenerates index.html (the tear sheet) from that index,
  4. regenerates tearsheet.pdf — a multi-page, fully-vector tear sheet a designer
     can open and copy/paste logos straight into their artwork.

The indexes are held in memory and handed to the page generators; they are not
written to disk.

SVG is the source of truth. Contributors only add/replace .svg files; running
this script (or the GitHub Action) regenerates every derivative and the tear
sheet automatically.

Usage:  python3 tools/build.py
        # arm64 macOS: libcairo is in /opt/homebrew/lib but off the default loader
        # path, so prefix the command (Linux needs no prefix). This builds EVERYTHING
        # including tearsheet.pdf; without it, PNG + tearsheet are skipped.
        DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python3 tools/build.py
Requires: cairosvg, pymupdf, fonttools, lxml, pillow
        (pip install cairosvg pymupdf fonttools lxml pillow)
"""
import os, re, json, html, datetime
# NB: cairosvg (which needs a matching-architecture libcairo) is imported lazily
# inside the functions that need it, so font specimens + HTML still build on a
# machine where cairosvg can't load (e.g. an arm64 Mac with only x86_64 cairo).

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (this file is root/tools/awbuild/core.py)
MARKS = os.path.join(ROOT, "marks")
PNG_SIZE = 1024

# ---- Authored metadata lives in data/*.toml (build = code, data = data). ----
# A "collection" = a folder + a matching data/<name>.toml. `marks` is the vector-mark
# collection (marks/ + data/marks.toml); `fonts` is another. Contributors are shared.
import tomllib
DATA = os.path.join(ROOT, "data")


def _load_toml(name):
    with open(os.path.join(DATA, name), "rb") as f:
        return tomllib.load(f)


# The marks collection: [[section]] display groupings (order preserved) + one [[asset]]
# entry PER FILE (1:1). Each entry's `file` is its path under marks/ (folder = section,
# extension = hosted .svg / reference-only .png). Credit + name are per-asset — no folder
# defaults, no fallbacks. build_manifest() warns on any file↔entry drift.
_MARKS = _load_toml("marks.toml")
SECTIONS = [(s["folder"], (s["title"], s["blurb"])) for s in _MARKS["section"]]
ASSETS_META = {a["file"]: a for a in _MARKS.get("asset", [])}   # "folder/slug.ext" -> entry
ROMAN = {"i", "ii", "iii", "iv", "v", "vi"}

# The in-game reference collection (reference/<game>/<team>/<slug>.jpg) — photographic,
# NOT vector marks. See data/reference.toml. Discovered by scanning; the TOML supplies
# game/team display names, ordering, per-team emblem (a mark reused as the header) and the
# shared credit. A <slug>.thumb.jpg is generated next to each JPG for the gallery grid.
REFERENCE = os.path.join(ROOT, "reference")
REF_THUMB_W = 640
try:
    _REF = _load_toml("reference.toml")
except Exception:
    _REF = {}
REF_CREDIT = _REF.get("credit", {})
REF_GAMES = _REF.get("game", [])
REF_TEAMS = {t["slug"]: t for t in _REF.get("team", [])}   # slug -> {name, logo?}


def _is_thumb(fn):
    return fn.lower().endswith(".thumb.jpg")


def title_case(slug):
    """Fallback display name when an asset entry sets no explicit `name`."""
    words = []
    for w in slug.split("-"):
        if w in ROMAN:
            words.append(w.upper())
        elif w.isdigit():
            words.append(w)
        else:
            words.append(w.capitalize())
    return " ".join(words)


def render_derivatives(force=False):
    """(Re)render the PNG next to each SVG — but only when it's stale.

    The PNG is rebuilt only if it's missing or older than its SVG (mtime), so a
    rebuild only touches the SVGs you actually changed (faster, and no needless
    diffs). Pass force=True (CLI: --force) to rebuild every PNG.

    Per-asset PDFs are intentionally NOT generated: the SVG is the vector download
    and covers every design tool, while the print/designer case is served by the
    aggregate tearsheet.pdf. (SVG→PDF was just a container swap — same RGB paths,
    no CMYK/fonts — and cairo stamped a live date into each one, churning git.)

    Caveat: a fresh `git clone` sets every file's mtime to checkout time, so the
    first build after a clone may re-render a few assets whose SVG landed a hair
    after its PNG — harmless, and `--force` always does a clean full rebuild.
    """
    import cairosvg
    made = skipped = 0
    for dirpath, _, files in os.walk(MARKS):
        for fn in sorted(files):
            if not fn.endswith(".svg"):
                continue
            svg = os.path.join(dirpath, fn)
            png = svg[:-4] + ".png"
            if (not force and os.path.exists(png)
                    and os.path.getmtime(png) >= os.path.getmtime(svg)):
                skipped += 1
                continue
            try:
                cairosvg.svg2png(url=svg, write_to=png, output_width=PNG_SIZE)
                made += 1
            except Exception as e:
                print(f"  !! failed {svg}: {e}")
    return made, skipped


def _source_for(meta, cid):
    """Where a reference-only mark's vector is acquired: the entry's `source`,
    else the crediting contributor's primary link."""
    if meta.get("source"):
        return meta["source"]
    for c in CREDITS:
        if c["id"] == cid and c["links"]:
            return c["links"][0][1]
    return ""


def _home_url(url):
    """The 'main page' behind a deep link: a DeviantArt artwork → the artist's
    profile; a GitHub blob/tree deep link → the repo root; otherwise the site root.
    Used so credit cards link to the source's main page, not just the specific work."""
    if not url:
        return ""
    m = re.match(r"(https?://[^/]+)(/.*)?$", url)
    if not m:
        return url
    root, path = m.group(1), m.group(2) or ""
    host = re.sub(r"^www\.", "", root.split("//", 1)[1])
    segs = [s for s in path.split("/") if s]
    if host == "deviantart.com" and segs:
        return f"{root}/{segs[0]}"                    # artist profile
    if host == "github.com" and len(segs) >= 2:
        return f"{root}/{segs[0]}/{segs[1]}"          # repo main page
    return root


def _home_label(url):
    """Compact label for a main-page link (scheme + www stripped)."""
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", url)).rstrip("/")


def _with_home_link(links):
    """Prepend a link to the source's main page (profile / repo root) when the
    existing links only deep-link to specific works. No-op if already present or empty."""
    if not links:
        return links
    home = _home_url(links[0][1])
    if not home or any(u == home for _, u in links):
        return links
    return [(_home_label(home), home)] + list(links)


def build_manifest():
    """Build the in-memory asset index by scanning marks/ and looking each file up in
    data/marks.toml (1:1). Warns on drift — a file with no entry, or an entry with
    no file — but keeps building. Returned to the page generators; not written to disk."""
    sections = []
    total = 0
    seen = set()
    for folder, (title, blurb) in SECTIONS:
        d = os.path.join(MARKS, folder)
        if not os.path.isdir(d):
            continue
        files = set(os.listdir(d))
        assets = []
        for fn in sorted(files):
            # An SVG = a hosted mark. A PNG with no sibling SVG = a reference-only
            # mark (we don't hold/redistribute the vector — show the PNG, link out).
            if fn.endswith(".svg"):
                slug, hosted, ext = fn[:-4], True, ".svg"
            elif fn.endswith(".png") and (fn[:-4] + ".svg") not in files:
                slug, hosted, ext = fn[:-4], False, ".png"
            else:
                continue
            filekey = f"{folder}/{slug}{ext}"
            seen.add(filekey)
            meta = ASSETS_META.get(filekey)
            if meta is None:
                print(f"  !! metadata missing: {filekey} — add a [[asset]] with "
                      f"file = \"{filekey}\" to data/marks.toml")
                meta = {}
            cid = meta.get("credit", "")
            cname = CREDIT_NAME.get(cid, cid) if cid else ""
            rel = f"marks/{folder}/{slug}"
            entry = {"slug": slug, "name": meta.get("name") or title_case(slug),
                     "svg": (rel + ".svg") if hosted else None,
                     "png": rel + ".png",
                     "credit": cid, "credit_name": cname}
            if not hosted:
                entry["hosting"] = "reference"
                entry["source"] = _source_for(meta, cid)
            assets.append(entry)
        if assets:
            sections.append({"id": folder.replace("/", "-"), "folder": folder,
                             "title": title, "blurb": blurb, "assets": assets})
            total += len(assets)
    for key in sorted(set(ASSETS_META) - seen):
        print(f"  !! no file for entry: {key} — remove it from data/marks.toml or add the file")
    return {
        "name": "awesome-wipeout — marks",
        "generated": datetime.date.today().isoformat(),
        "total": total, "sections": sections,
    }


def render_reference_thumbs(force=False):
    """Generate a downscaled <slug>.thumb.jpg next to each reference screenshot,
    for the gallery grid (the lightbox loads the full image). Only (re)made when
    stale, like the PNGs. TOLERANT: if Pillow is missing the step is skipped, not
    fatal — any committed thumbs still serve, and the grid falls back to the full
    image where a thumb is absent."""
    from PIL import Image, ImageOps
    made = skipped = 0
    if not os.path.isdir(REFERENCE):
        return made, skipped
    for dirpath, _, files in os.walk(REFERENCE):
        for fn in sorted(files):
            if not fn.lower().endswith(".jpg") or _is_thumb(fn):
                continue
            src = os.path.join(dirpath, fn)
            thumb = src[:-4] + ".thumb.jpg"
            if (not force and os.path.exists(thumb)
                    and os.path.getmtime(thumb) >= os.path.getmtime(src)):
                skipped += 1
                continue
            try:
                im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
                w, h = im.size
                if w > REF_THUMB_W:
                    im = im.resize((REF_THUMB_W, round(h * REF_THUMB_W / w)),
                                   Image.Resampling.LANCZOS)
                im.save(thumb, "JPEG", quality=82, optimize=True, progressive=True)
                made += 1
            except Exception as e:
                print(f"  !! thumb failed {src}: {e}")
    return made, skipped


def build_reference_manifest():
    """Scan reference/<game>/<team>/*.jpg into an in-memory reference index. Games and
    teams are ordered + named from data/reference.toml (unknown folders fall to the
    end, title-cased); each team carries its emblem (a mark reused as the header) and
    a per-shot {name, jpg, thumb}. Empty team folders are skipped. Screenshots are
    reference-only — never offered as downloads, excluded from the tear sheet.
    Returned to build_reference_page; not written to disk."""
    def team_meta(slug):
        return REF_TEAMS.get(slug, {})

    def shot_name(team_slug, slug):
        # Drop the redundant team prefix so a caption reads "Rear Chase", not
        # "Feisar Rear Chase" (the team is already the section header).
        base = slug[len(team_slug) + 1:] if slug.startswith(team_slug + "-") else slug
        return title_case(base or slug)

    gmeta = {g["slug"]: g for g in REF_GAMES}
    listed = [g["slug"] for g in REF_GAMES]
    on_disk = ([d for d in sorted(os.listdir(REFERENCE))
                if os.path.isdir(os.path.join(REFERENCE, d))] if os.path.isdir(REFERENCE) else [])
    games_out, total = [], 0
    for gslug in listed + [d for d in on_disk if d not in listed]:
        gdir = os.path.join(REFERENCE, gslug)
        if not os.path.isdir(gdir):
            continue
        g = gmeta.get(gslug, {})
        teams_disk = [d for d in sorted(os.listdir(gdir))
                      if os.path.isdir(os.path.join(gdir, d))]
        team_order = g.get("teams", [])
        teams_out = []
        for tslug in team_order + [d for d in teams_disk if d not in team_order]:
            tdir = os.path.join(gdir, tslug)
            if not os.path.isdir(tdir):
                continue
            images = []
            for fn in sorted(os.listdir(tdir)):
                if not fn.lower().endswith(".jpg") or _is_thumb(fn):
                    continue
                slug = fn[:-4]
                rel = f"reference/{gslug}/{tslug}/{slug}"
                thumb = rel + ".thumb.jpg"
                images.append({
                    "slug": slug, "name": shot_name(tslug, slug), "jpg": rel + ".jpg",
                    "thumb": thumb if os.path.exists(os.path.join(ROOT, thumb)) else rel + ".jpg",
                })
            if not images:
                continue
            tm = team_meta(tslug)
            logo = tm.get("logo")
            teams_out.append({
                "id": f"{gslug}-{tslug}", "slug": tslug,
                "name": tm.get("name") or title_case(tslug),
                "logo": logo if (logo and os.path.exists(os.path.join(ROOT, logo))) else None,
                "images": images,
            })
            total += len(images)
        if teams_out:
            games_out.append({"id": gslug, "slug": gslug,
                              "name": g.get("name") or title_case(gslug),
                              "blurb": g.get("blurb", ""), "teams": teams_out})
    return {
        "name": "awesome-wipeout — in-game reference",
        "generated": datetime.date.today().isoformat(),
        "credit": REF_CREDIT, "total": total, "games": games_out,
    }


from awbuild.styles import CSS, TEAMS_CSS, LEAGUES_CSS, VERSIONS_CSS
# Contributors registry (id -> display name, blurb, licence, source links), from
# data/contributors.toml. `who`/`what` keep the internal names the renderers expect.
CREDITS = [
    {"id": c["id"], "who": c["name"], "what": c.get("blurb", ""),
     "license": c.get("license"),
     "links": [(l["label"], l["url"]) for l in c.get("links", [])]}
    for c in _load_toml("contributors.toml")["contributor"]
]
CREDIT_NAME = {c["id"]: c["who"] for c in CREDITS}


# ---- Fonts (referenced only — no font files are hosted here) ----
# Sample sheets are generated at build time from fonts installed on the build
# machine, outlined to vector paths (no font is embedded/hosted). If a font is
# not installed, the recreations fall back to NR74W's own preview image.
_FONTS_DATA = _load_toml("fonts.toml")
FONTS_REPO = _FONTS_DATA["source"]["repo"]
FONT_BLOB = _FONTS_DATA["source"]["blob"]
FONT_PREVIEW = _FONTS_DATA["source"]["preview"]
# Reconstruct the shapes the font renderers expect, straight from data/fonts.toml.
FONTS_RECREATED = [(g["era"], [(f["family"], f["ttf"]) for f in g["fonts"]])
                   for g in _FONTS_DATA["recreated"]]
FONTS_THIRDPARTY = [(t["family"], t["usage"], t["license"], t["url"])
                    for t in _FONTS_DATA["thirdparty"]]
FONTS_DAFONT = [(t["family"], t["usage"], t["license"], t["url"])
                for t in _FONTS_DATA["dafont"]]
FONTS_REFER = [(t["family"], t["usage"], t["note"]) for t in _FONTS_DATA["refer"]]
FONT_LORE = _FONTS_DATA["lore"]

# Font credit comes from the SHARED contributor registry (contributors.toml), same as
# marks: each font entry carries `credit = "<contributor-id>"`. Reconstruct the
# family -> (designer, url) / designer -> [extra links] shapes the renderers expect.
_CONTRIB = {c["id"]: c for c in CREDITS}
_FONT_CID = {}
for _g in _FONTS_DATA["recreated"]:
    for _f in _g["fonts"]:
        if _f.get("credit"):
            _FONT_CID[_f["family"]] = _f["credit"]
for _t in _FONTS_DATA["thirdparty"] + _FONTS_DATA["dafont"]:
    if _t.get("credit"):
        _FONT_CID[_t["family"]] = _t["credit"]
FONT_CREDIT = {}
FONT_CREDIT_EXTRA = {}
for _fam, _cid in _FONT_CID.items():
    _c = _CONTRIB[_cid]
    _links = _c["links"]                       # [(label, url), ...]
    FONT_CREDIT[_fam] = (_c["who"], _links[0][1] if _links else None)
    if len(_links) > 1:
        FONT_CREDIT_EXTRA[_c["who"]] = [(lbl, u) for lbl, u in _links[1:]]

import sys

_TTF = {}


def _load_ttf(spec):
    if spec not in _TTF:
        from fontTools.ttLib import TTFont
        path, _, num = spec.partition("::")
        f = TTFont(path, fontNumber=int(num)) if num else TTFont(path)
        _TTF[spec] = (f.getGlyphSet(), f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
    return _TTF[spec]


def _norm_family(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


_FONT_INDEX = None
_FONT_ORIG = {}   # normalised family -> first-seen original family name (for hints)


def _style_score(font):
    """Lower = more 'regular'. Used to prefer upright/regular over italic/bold
    when several faces share a family name (e.g. TRACEROUTE Regular vs Italic)."""
    score = 0
    try:
        ms = font["head"].macStyle
        if ms & 0b01:
            score += 2          # bold
        if ms & 0b10:
            score += 4          # italic
    except Exception:
        pass
    try:
        for rec in font["name"].names:
            if rec.nameID in (2, 17):          # subfamily / typographic subfamily
                s = rec.toUnicode().lower()
                if "italic" in s or "oblique" in s:
                    score += 4
                if "bold" in s:
                    score += 2
                if any(w in s for w in ("light", "thin", "black", "heavy",
                                        "filled", "outline", "condensed", "expanded")):
                    score += 1
                break
    except Exception:
        pass
    return score


def _font_index():
    """Scan the OS font folders once and map normalised family name -> font spec.
    Cross-platform (macOS / Windows / Linux) — no fontconfig required."""
    global _FONT_INDEX
    if _FONT_INDEX is not None:
        return _FONT_INDEX
    from fontTools.ttLib import TTFont, TTCollection
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        dirs = [os.path.join(home, "Library/Fonts"), "/Library/Fonts",
                "/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
                "/Network/Library/Fonts"]
    elif sys.platform.startswith("win"):
        dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts")]
    else:
        dirs = ["/usr/share/fonts", "/usr/local/share/fonts",
                os.path.join(home, ".fonts"), os.path.join(home, ".local/share/fonts")]
    # a local, gitignored drop-in folder scanned first — put any font file here
    # (no system install needed) and its specimen is generated on the next build.
    dirs = [os.path.join(ROOT, "downloads", "fonts")] + dirs
    idx = {}
    score = {}

    def add(font, spec):
        try:
            names = font["name"].names
        except Exception:
            return
        sc = _style_score(font)
        for nid in (16, 1, 4, 6):           # typographic family, family, full, postscript
            for rec in names:
                if rec.nameID == nid:
                    try:
                        val = rec.toUnicode()
                    except Exception:
                        continue
                    k = _norm_family(val)
                    if k and (k not in idx or sc < score[k]):   # prefer the most regular face
                        idx[k] = spec
                        score[k] = sc
                        _FONT_ORIG[k] = val

    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                ext = fn.lower().rsplit(".", 1)[-1] if "." in fn else ""
                if ext not in ("ttf", "otf", "ttc", "otc"):
                    continue
                p = os.path.join(root, fn)
                try:
                    if ext in ("ttc", "otc"):
                        for i, f in enumerate(TTCollection(p, lazy=True).fonts):
                            add(f, f"{p}::{i}")
                    else:
                        add(TTFont(p, lazy=True), p)
                except Exception:
                    continue
    _FONT_INDEX = idx
    return idx


def _ttf_line(path, text, x, baseline, size, fill):
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    gs, cmap, hmtx, upm = _load_ttf(path)
    sc = size / upm
    spen = SVGPathPen(gs)
    penx = x
    for ch in text:
        g = cmap.get(ord(ch)) or cmap.get(ord("?"))
        if g is None:
            continue
        rec = DecomposingRecordingPen(gs)
        gs[g].draw(rec)
        rec.replay(TransformPen(spen, (sc, 0, 0, -sc, penx, baseline)))
        penx += hmtx[g][0] * sc
    return f'<path d="{spen.getCommands()}" fill="{fill}"/>', penx - x


def _inked_chars(spec, chars):
    """The subset of `chars` the font renders with a non-empty (inked) glyph."""
    from fontTools.pens.boundsPen import BoundsPen
    gs, cmap, _, _ = _load_ttf(spec)
    out = []
    for ch in chars:
        g = cmap.get(ord(ch))
        if not g:
            continue
        pen = BoundsPen(gs)
        try:
            gs[g].draw(pen)
        except Exception:
            continue
        if pen.bounds is not None:
            out.append(ch)
    return "".join(out)


def _sample_sheet(path, name, phrase):
    """Outlined vector sample sheet (name + lore phrase + specimen) — no font hosted.
    A lowercase-only display face (missing most capitals — e.g. the Wipeout tribute font,
    whose W/T come from Saturn in the real logo) renders its whole sample in lowercase so
    the name and specimen don't show gaps."""
    PAD = 30
    if len(_inked_chars(path, "ABCDEFGHIJKLMNOPQRSTUVWXYZ")) < 13:
        name, phrase = name.lower(), phrase.lower()
        digits, punct = _inked_chars(path, "0123456789"), _inked_chars(path, "&.,!?")
        charset = "abcdefghijklmnopqrstuvwxyz"
        charset += (f"  {digits}" if digits else "") + (f"  {punct}" if punct else "")
        alpha = [(charset, 16, "#6b7280", 4)]
    else:
        alpha = [("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 16, "#6b7280", 13),
                 ("abcdefghijklmnopqrstuvwxyz  0123456789  &.,!?", 16, "#6b7280", 4)]
    lines = [(name, 46, "#12151a", 28), (phrase, 23, "#3a3f47", 22)] + alpha
    y, paths, maxw = PAD, [], 0
    for txt, size, fill, gap in lines:
        y += size
        try:
            p, w = _ttf_line(path, txt, PAD, y, size, fill)
        except Exception:
            p, w = "", 0
        if p:
            paths.append(p)
        maxw = max(maxw, w)
        y += gap
    W, H = maxw + 2 * PAD, y + PAD - 6
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.1f} {H:.1f}" '
            f'width="{W:.0f}" height="{H:.0f}">{"".join(paths)}</svg>')


def font_slug(family):
    return re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-")


# Display name -> the installed font's actual family, when they differ, so the specimen
# lookup still finds the file. e.g. Paul Willocks' "Wipeout Typeface" ships as "Wipeout".
_FONT_FILE_ALIAS = {"Wipeout Typeface": "Wipeout"}


def _locate_font(family):
    """Return the font spec of an installed font matching `family`, else None.
    Matching is on the normalised family name, so 'OCR B' also matches 'OCRB';
    `_FONT_FILE_ALIAS` maps a display name to the font's real family when they differ."""
    return _font_index().get(_norm_family(_FONT_FILE_ALIAS.get(family, family)))


def generate_font_samples():
    """Render an outlined sample sheet for every font found on the build machine.

    The build is ADDITIVE and TOLERANT: the font source (system fonts + the
    ephemeral downloads/fonts drop-in) may be absent. Nothing is ever deleted, so
    a specimen once generated + committed survives builds where its font is gone
    (e.g. CI, or after downloads/ is wiped). A font is only reported "missing"
    when there is no committed specimen to fall back on. One bad/corrupt font
    never breaks the build. Returns (missing_families, name_hints)."""
    try:
        import fontTools  # noqa: F401 — only needed to outline specimens; absent in CI
    except ImportError:
        print("  fontTools not installed — skipping specimen generation; "
              "committed fonts/*.svg are used as-is")
        return [], {}
    outdir = os.path.join(ROOT, "fonts")
    os.makedirs(outdir, exist_ok=True)
    _font_index()  # populates _FONT_ORIG for hints; skips any font dir that's absent
    fams = ([f for _, lst in FONTS_RECREATED for f, _ in lst]
            + [t[0] for t in FONTS_THIRDPARTY] + [d[0] for d in FONTS_DAFONT])
    missing, hints = [], {}
    for fam in fams:
        target = os.path.join(outdir, font_slug(fam) + ".svg")
        path = _locate_font(fam)
        if path:
            try:
                svg = _sample_sheet(path, fam, FONT_LORE.get(fam, fam))
                with open(target, "w") as fh:
                    fh.write(svg)
                continue
            except Exception as e:
                print(f"  !! could not render '{fam}': {e} — keeping any existing specimen")
        # font unavailable (or render failed) — keep any committed specimen;
        # only flag as missing when there's nothing to show.
        if not os.path.exists(target):
            missing.append(fam)
            q = _norm_family(fam)
            near = sorted({o for k, o in _FONT_ORIG.items()
                           if len(k) >= 3 and (q in k or k in q)})
            if near:
                hints[fam] = near[:3]
    return missing, hints


def build_font_manifest():
    """Build the in-memory font index — the font analogue of the marks manifest.

    Same shape as the vector manifest (name / generated / total / sections[] with
    per-item slug + name + credit). Font metadata is authored in the FONTS_* /
    FONT_CREDIT tables above; this index is derived from them. Fonts are referenced,
    not hosted: 'specimen' is the committed outlined sample sheet, or null if none
    exists yet. Returned to the page generators; not written to disk."""
    def simple_lic(lic):
        return "commercial" if "commercial" in lic else "free"

    def entry(family, usage, licence, source, kind):
        slug = font_slug(family)
        spec = f"fonts/{slug}.svg"
        designer, dl = FONT_CREDIT.get(family, (None, None))
        credits = []
        if designer:
            credits.append({"name": designer, "url": dl})
            credits += [{"name": lbl, "url": u} for lbl, u in FONT_CREDIT_EXTRA.get(designer, [])]
        return {
            "slug": slug, "name": family, "usage": usage, "kind": kind, "licence": licence,
            "specimen": spec if os.path.exists(os.path.join(ROOT, spec)) else None,
            "source": source, "credit": designer, "credit_url": dl,
            "credits": credits, "sample_phrase": FONT_LORE.get(family, ""),
        }

    # Link to the repo's main page, not a deep-link to the individual .ttf file.
    fan = ([entry(f, era, "free", FONTS_REPO, "recreation")
            for era, lst in FONTS_RECREATED for f, ttf in lst]
           + [entry(f, used, simple_lic(lic), url, "fan-made")
              for f, used, lic, url in FONTS_DAFONT])
    free = [entry(f, used, "free", url, "foundry")
            for f, used, lic, url in FONTS_THIRDPARTY if simple_lic(lic) == "free"]
    comm = [entry(f, used, "commercial", url, "foundry")
            for f, used, lic, url in FONTS_THIRDPARTY if simple_lic(lic) == "commercial"]
    system = [{"slug": font_slug(f), "name": f, "usage": u, "kind": "system",
               "licence": "system", "specimen": None, "source": None,
               "credit": None, "credit_url": None, "credits": [], "note": n}
              for f, u, n in FONTS_REFER]
    sections = [
        {"id": "fan-made", "title": "Fan-made WipEout fonts", "fonts": fan},
        {"id": "foundry-free", "title": "Type foundries — free", "fonts": free},
        {"id": "foundry-commercial", "title": "Type foundries — commercial", "fonts": comm},
        {"id": "system", "title": "System fonts (referenced only)", "fonts": system},
    ]
    return {
        "name": "awesome-wipeout — fonts",
        "generated": datetime.date.today().isoformat(),
        "note": ("Fonts are referenced, never hosted. Specimen SVGs are outlined from "
                 "locally-installed fonts at build time; specimen=null means no committed "
                 "sample yet."),
        "total": sum(len(s["fonts"]) for s in sections),
        "sections": sections,
    }


def esc(s):
    return html.escape(s, quote=True)


def _load_pages():
    """The site's page registry (nav order + which generator renders each page),
    authored in data/pages.toml. `kind` selects the generator: marks | fonts |
    prose (a simple intro/links page). Falls back to a built-in default so a
    missing/renamed file never breaks the build. index.html is the marks page."""
    try:
        pages = _load_toml("pages.toml")["page"]
    except Exception:
        pages = [
            {"slug": "index", "nav": "Marks", "title": "Marks", "kind": "marks"},
            {"slug": "fonts", "nav": "Fonts", "title": "Fonts", "kind": "fonts"},
        ]
    for p in pages:
        p["file"] = "index.html" if p["slug"] == "index" else f'{p["slug"]}.html'
    return pages


NAV_PAGES = _load_pages()


# Nav items that expand to a dropdown of sub-pages (the rendered .md docs aren't
# NAV_PAGES, so they live here under About).
NAV_SUBMENUS = {
    "about": [("contributing.html", "Contributing"),
              ("licensing.html", "Licensing"),
              ("credits.html", "Credits")],
}


def _nav_html(active):
    """The thin sticky header: brand + one link per page; the About item expands to a
    dropdown of its sub-pages (inline on touch)."""
    def link(href, label, is_active):
        cls = ' class="active"' if is_active else ""
        return f'<a href="{href}"{cls}>{esc(label)}</a>'
    items = []
    for p in NAV_PAGES:
        if p.get("kind") == "versions":
            continue  # footer-only, not shown in main nav
        sub = NAV_SUBMENUS.get(p["slug"])
        if sub:
            sub_slugs = {f[:-5] for f, _ in sub}
            here = active == p["slug"] or active in sub_slugs
            subhtml = "".join(link(f, lbl, active == f[:-5]) for f, lbl in sub)
            top = link(p["file"], p["nav"] + " ▾", here)
            items.append(f'<div class="navitem">{top}<div class="submenu">{subhtml}</div></div>')
        else:
            items.append(link(p["file"], p["nav"], p["slug"] == active))
    return ('<nav class="topnav"><div class="topnav-inner">'
            '<a class="brand" href="index.html">awesome&#8209;<b>wipeout</b></a>'
            f'<div class="navlinks">{"".join(items)}</div></div></nav>')


# Google Analytics 4 (gtag.js). Injected into every page's <head> by _document().
# Loaded async so it never blocks render. Measurement ID: awesome-wipeout web stream.
#
# Custom events (see also the "Analytics" section in CLAUDE.md). One delegated,
# capture-phase click listener on `document` catches clicks anywhere — including the
# lightbox / vbox / fonts overlays whose markup is built in JS — so there are no
# per-element onclick handlers to keep in sync. Event ⇄ trigger:
#   download_svg      — an asset's SVG button (any a[download] href ending .svg)
#   download_png      — an asset's PNG button (any a[download] href ending .png)
#   download_pdf      — the aggregate tear-sheet PDF link (.pdflink)
#   get_font          — a font's "get ↗" link (.font-get, card or lightbox)
#   contributor_link  — an outbound link to a contributor's own site (.contrib-link:
#                       credit cards, font "by <designer>", the restricted-vector overlay)
# Two more — view_mark / view_font — are lightbox-open events fired from the marks/fonts
# lightbox scripts themselves (openLb / openFb), since those opens are <div> clicks, not
# anchors this listener would see.
# gtag() is defined synchronously below, so calls queue to dataLayer even before the
# async library finishes loading. Params are plain event params — to slice reports by
# them, register matching custom dimensions in the GA4 admin (Analytics section, CLAUDE.md).
# GA4 (gtag.js) + the site's one delegated action-tracking listener. Written once to
# the shared analytics.js (see write_shared_assets) and referenced by every page via
# _document — no longer inlined per page. The async gtag library is injected from here
# so a single <script src="analytics.js"> in <head> is all a page needs.
_ANALYTICS_JS = r"""window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', 'G-KX3WW4Q3NG');
(function(){var s=document.createElement('script');s.async=true;
  s.src='https://www.googletagmanager.com/gtag/js?id=G-KX3WW4Q3NG';document.head.appendChild(s);})();
// Custom action tracking — one delegated listener for the whole site.
(function(){
  function ev(name, params){ try{ gtag('event', name, params||{}); }catch(e){} }
  function slug(h){ return (h.split('#')[0].split('?')[0].split('/').pop()||'').replace(/\.[^.]+$/,''); }
  document.addEventListener('click', function(e){
    var a = e.target.closest && e.target.closest('a'); if(!a) return;
    if(a.hasAttribute('download')){
      var href = a.getAttribute('href') || '';
      if(/\.svg(?:[?#]|$)/i.test(href)) ev('download_svg', {mark: slug(href), file: href});
      else if(/\.png(?:[?#]|$)/i.test(href)) ev('download_png', {mark: slug(href), file: href});
      return;
    }
    if(a.classList.contains('pdflink')){ ev('download_pdf', {file: a.getAttribute('href') || ''}); return; }
    if(a.classList.contains('font-get')){ ev('get_font', {font: a.getAttribute('data-font') || '', link_url: a.href, link_domain: a.hostname}); return; }
    if(a.classList.contains('contrib-link')){ ev('contributor_link', {contributor: a.getAttribute('data-contrib') || '', link_url: a.href, link_domain: a.hostname}); return; }
  }, true);
})();
"""


def write_shared_assets():
    """Write the two shared, generated static assets that every page links instead of
    inlining: styles.css (the site CSS + Teams-page CSS) and analytics.js (GA4 + the
    delegated action listener). Keeping them external de-duplicates ~25 KB of CSS and the
    analytics block from every HTML page."""
    _write("styles.css", CSS + VERSIONS_CSS + TEAMS_CSS + LEAGUES_CSS)
    _write("analytics.js", _ANALYTICS_JS)


SITE_DESCRIPTION = (
    "A community-maintained, normalised library of WipEout-universe logos, emblems and "
    "marks — teams, sponsors, tracks, speed classes, game modes and series titles — "
    "every asset available as SVG and PNG."
)


FOOTER = """<footer>
  <p><a href="changelog.html">Changelog</a> &middot; WipEout and all related logos, names and marks are trademarks of Sony Interactive Entertainment /
  Studio Liverpool (formerly Psygnosis). This is a non-commercial, fan-made archive for the community.
  Assets compiled from the work of the original creators &mdash; see
  <a href="credits.html">CREDITS</a>. Contributions welcome via
  <a href="contributing.html">pull request</a>.</p>
  <a class="gh-link" href="https://github.com/awesome-wipeout/awesome-wipeout.github.io"
     target="_blank" rel="noopener" aria-label="Source on GitHub">
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
    <span>Source on GitHub</span>
  </a>
</footer>"""


def _document(slug, title, header_inner, body, scripts="", description=None):
    """Wrap a page's body in the shared shell: <head>, sticky nav, optional hero
    <header>, content <div class="wrap">, footer, then any page scripts."""
    hero = f"<header>\n{header_inner}\n</header>\n" if header_inner else ""
    desc = esc(description or SITE_DESCRIPTION)
    page_title = esc(title)
    page_url = f"https://awesome-wipeout.github.io/{slug + '.html' if slug != 'index' else ''}"
    social_image = "https://awesome-wipeout.github.io/social-card.png"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{page_title} · awesome-wipeout</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{page_title} · awesome-wipeout">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{social_image}">
<meta property="og:url" content="{page_url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="awesome-wipeout">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{page_title} · awesome-wipeout">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{social_image}">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="icon" href="favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="stylesheet" href="styles.css">
<script defer src="analytics.js"></script></head>
<body>
{_nav_html(slug)}
{hero}<div class="wrap">
{body}
</div>
{FOOTER}
{scripts}
</body></html>"""


def _write(name, doc):
    with open(os.path.join(ROOT, name), "w") as f:
        f.write(doc)


# ---- Minimal, zero-dependency Markdown -> HTML (for the prose About body and for
# rendering the repo's .md docs into styled site pages). Handles the constructs our
# docs actually use: headings, paragraphs, bold/italic/inline-code/links, fenced code,
# blockquotes, tables, and (one level of) unordered/ordered lists. ----
def _md_inline(s):
    s = esc(s)
    s = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\*\w])\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    return s


def _md_list(lines, start):
    """Render a list (with one level of nesting) starting at lines[start]. A blank line
    ends the list; a non-marker, non-blank line is a lazy continuation of the current
    item (so a bullet whose text wraps across lines stays one <li>). Returns
    (html, next_index)."""
    def kind(ln):
        return "ol" if re.match(r"^\s*\d+\.\s+", ln) else "ul"
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    tag = kind(lines[start])
    items, i, n = [], start, len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():                             # blank line ends the list
            break
        if re.match(r"^\s*([-*+]|\d+\.)\s+", ln):
            indent = len(ln) - len(ln.lstrip())
            if indent < base_indent:
                break
            if indent > base_indent:                   # nested sub-list
                sub, i = _md_list(lines, i)
                if items:
                    items[-1] = items[-1][:-5] + sub + "</li>"   # graft before </li>
                continue
            text = re.sub(r"^\s*([-*+]|\d+\.)\s+", "", ln)
            items.append(f"<li>{_md_inline(text.strip())}</li>")
            i += 1
        elif items:                                    # wrapped text: continue this item
            items[-1] = items[-1][:-5] + " " + _md_inline(ln.strip()) + "</li>"
            i += 1
        else:
            break
    return f"<{tag}>{''.join(items)}</{tag}>", i


def md_to_html(md):
    lines = md.replace("\r\n", "\n").split("\n")
    out, para, i, n = [], [], 0, len(lines)

    def flush():
        if para:
            out.append("<p>" + _md_inline(" ".join(para).strip()) + "</p>")
            para.clear()

    while i < n:
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush(); i += 1; code = []
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i]); i += 1
            i += 1
            out.append(f"<pre><code>{esc(chr(10).join(code))}</code></pre>"); continue
        if not s:
            flush(); i += 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush(); lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_md_inline(m.group(2).strip())}</h{lvl}>"); i += 1; continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            flush(); out.append("<hr>"); i += 1; continue
        if s.startswith(">"):
            flush(); quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i])); i += 1
            out.append(f"<blockquote>{md_to_html(chr(10).join(quote))}</blockquote>"); continue
        if "|" in s and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1]):
            flush()
            row = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            header = row(lines[i]); i += 2; body_rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                body_rows.append(row(lines[i])); i += 1
            th = "".join(f"<th>{_md_inline(c)}</th>" for c in header)
            trs = "".join("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in r) + "</tr>"
                          for r in body_rows)
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"); continue
        if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
            flush(); html_list, i = _md_list(lines, i); out.append(html_list); continue
        para.append(s); i += 1
    flush()
    return "\n".join(out)


# Repo docs rendered into styled site pages (linked from About + footer). GitHub renders
# the .md natively; on the static site we render our own HTML so links don't dump raw text.
DOC_PAGES = [
    ("CONTRIBUTING.md", "contributing.html", "Contributing"),
    ("LICENSING.md", "licensing.html", "Licensing"),
    ("CREDITS.md", "credits.html", "Credits"),
    ("LICENSE.md", "license.html", "Licence"),
]
# Rewrite intra-doc .md cross-links to their rendered .html on the static site.
DOC_LINK_MAP = {src: out for src, out, _ in DOC_PAGES}
GITHUB = "https://github.com/awesome-wipeout/awesome-wipeout.github.io"


def _fix_repo_links(s):
    """Repo-relative links in the docs (CLAUDE.md, tools/…, data/…, *.toml/*.py) don't
    exist on the static site — point them at the GitHub source instead."""
    def repl(m):
        path = m.group(1)
        p = path.rstrip("/")
        kind = "tree" if path.endswith("/") or "." not in os.path.basename(p) else "blob"
        return f'href="{GITHUB}/{kind}/main/{p}"'
    return re.sub(r'href="(CLAUDE\.md|tools/[^"]*|data/[^"]*|[^":/#]+\.(?:toml|py))"', repl, s)



# Re-export every module-level name (incl. _underscore helpers) so the
# page/pdf modules can `from awbuild.core import *` and get the full toolkit.
__all__ = [n for n in dir() if not n.startswith("__")]
