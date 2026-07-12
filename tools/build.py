#!/usr/bin/env python3
"""
build.py  --  Build awesome-wipeout (the WipEout Vector Asset Library).

For every SVG under marks/ this:
  1. renders a transparent high-res PNG (longest edge = PNG_SIZE) next to it,
  2. writes marks/manifest.json describing every asset,
  3. regenerates index.html (the tear sheet) from that manifest,
  4. regenerates tearsheet.pdf — a multi-page, fully-vector tear sheet a designer
     can open and copy/paste logos straight into their artwork.

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def build_manifest():
    """Build the asset index by scanning marks/ and looking each file up in
    data/marks.toml (1:1). Warns on drift — a file with no entry, or an entry with
    no file — but keeps building."""
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
    manifest = {
        "name": "awesome-wipeout — marks",
        "generated": datetime.date.today().isoformat(),
        "total": total, "sections": sections,
    }
    with open(os.path.join(MARKS, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


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
    """Scan reference/<game>/<team>/*.jpg into reference/manifest.json. Games and
    teams are ordered + named from data/reference.toml (unknown folders fall to the
    end, title-cased); each team carries its emblem (a mark reused as the header) and
    a per-shot {name, jpg, thumb}. Empty team folders are skipped. Screenshots are
    reference-only — never offered as downloads, excluded from the tear sheet."""
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
    manifest = {
        "name": "awesome-wipeout — in-game reference",
        "generated": datetime.date.today().isoformat(),
        "credit": REF_CREDIT, "total": total, "games": games_out,
    }
    os.makedirs(REFERENCE, exist_ok=True)
    with open(os.path.join(REFERENCE, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


CSS = """
:root{--bg:#f7f8fa;--card:#fff;--ink:#12151a;--muted:#6b7280;--line:#e5e7eb;
--accent:#0b7fd4;--check:#d5dbe2}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:var(--ink);background:var(--bg)}
header{padding:48px 32px 24px;max-width:1600px;margin:0 auto}
h1{margin:0 0 22px;font-size:30px;letter-spacing:-.02em;position:relative}
/* standardised accent underline under every page title */
h1::after{content:"";position:absolute;left:0;bottom:-9px;width:54px;height:5px;
background:var(--accent);border-radius:3px}
.lead{color:var(--muted);max-width:70ch;margin:0 0 12px}
.stat{display:inline-block;margin-right:18px;color:var(--muted);font-size:13px}
.wrap{max-width:1600px;margin:0 auto;padding:0 32px 64px}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 8px}
.toc a{font-size:12.5px;text-decoration:none;color:var(--accent);border:1px solid var(--line);
background:var(--card);padding:4px 10px;border-radius:999px}
.pdflink{font-weight:600;color:var(--accent);text-decoration:none;border:1px solid var(--accent);
padding:6px 12px;border-radius:8px;display:inline-block}
.pdflink:hover{background:var(--accent);color:#fff}
.hero-top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px 28px;flex-wrap:wrap}
.hero-top h1{margin:0}
.pdfcta{display:flex;flex-direction:column;align-items:flex-end;text-align:right;gap:6px}
.pdfcta-note{font-size:12.5px;color:var(--muted);max-width:34ch}
@media(max-width:640px){.pdfcta{align-items:flex-start;text-align:left}}
section{margin-top:40px}
.sh{border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:20px}
.sh h2{margin:0;font-size:19px}
.sh p{margin:4px 0 0;color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
display:flex;flex-direction:column}
.thumb{height:220px;display:flex;align-items:center;justify-content:center;padding:28px;cursor:zoom-in;position:relative;
background:
 linear-gradient(45deg,var(--check) 25%,transparent 25%,transparent 75%,var(--check) 75%) 0 0/22px 22px,
 linear-gradient(45deg,var(--check) 25%,transparent 25%,transparent 75%,var(--check) 75%) 11px 11px/22px 22px,
 #fff}
.thumb img{width:100%;height:164px;object-fit:contain;display:block}
.meta{padding:10px 12px;border-top:1px solid var(--line)}
.name{font-weight:600;font-size:13.5px;margin-bottom:6px;word-break:break-word}
.dl{display:flex;gap:6px}
.dl a{font-size:11px;text-decoration:none;color:var(--muted);border:1px solid var(--line);
padding:2px 8px;border-radius:6px}
.dl a:hover{color:var(--accent);border-color:var(--accent)}
.dl a.get{color:var(--accent);border-color:var(--accent);font-weight:600}
.dl a.get:hover{background:var(--accent);color:#fff}
.dl a.locked{cursor:pointer}
/* restricted-vector overlay: shown when the SVG button of a non-redistributable mark is clicked */
.vbox{position:fixed;inset:0;z-index:1200;display:none;align-items:center;justify-content:center;
padding:20px;background:rgba(12,15,20,.62)}
.vbox.open{display:flex}
.vbox-panel{position:relative;background:var(--card);color:var(--ink);max-width:360px;width:100%;
border:1px solid var(--line);border-radius:12px;padding:24px;box-shadow:0 24px 64px rgba(0,0,0,.4);text-align:center}
.vbox-panel h3{margin:0 0 10px;font-size:16px}
.vbox-panel p{margin:0 0 18px;font-size:13px;line-height:1.55;color:var(--muted)}
.vbox-go{display:inline-block;text-decoration:none;background:var(--accent);color:#fff;font-weight:600;
font-size:13px;padding:9px 18px;border-radius:8px}
.vbox-go:hover{filter:brightness(1.08)}
.vbox-x{position:absolute;top:8px;right:10px;background:none;border:0;font-size:22px;line-height:1;
color:var(--muted);cursor:pointer}
.vbox-x:hover{color:var(--ink)}
.src{display:block;margin-top:8px;font-size:11px;color:var(--muted);text-decoration:none}
.src:hover{color:var(--accent);text-decoration:underline}
.src-none{color:#aab2bd;font-style:italic}
.credit:target{border-color:var(--accent);box-shadow:0 0 0 2px rgba(11,127,212,.15)}
.fonts{margin-top:56px;border-top:1px solid var(--line);padding-top:28px}
.fonts h2{font-size:19px;margin:0 0 6px}
.fonts>p{color:var(--muted);font-size:13px;margin:0 0 6px;max-width:82ch}
.fonts h3{font-size:14px;margin:24px 0 12px;color:var(--ink)}
.font-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.font-card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;cursor:zoom-in}
.font-card:hover{border-color:var(--accent)}
.font-shot{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px 16px;height:150px;display:flex;align-items:center;justify-content:center;overflow:hidden}
.font-shot img{width:100%;height:100%;object-fit:contain;display:block}
.font-shot-missing{flex-direction:column;align-items:flex-start;justify-content:center;border-style:dashed;gap:4px;color:#9aa3af}
.font-shot-missing b{font-weight:600;font-size:19px;color:#8a929c}
.font-shot-missing small{font-size:11px}
.font-meta{margin-top:12px;display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:12px;text-align:left}
.font-info{min-width:0}
.font-name{font-weight:600;font-size:13.5px;color:var(--ink)}
.font-use{color:var(--muted);font-size:11.5px;margin-top:3px}
.font-cred{color:var(--muted);font-size:11.5px;margin-top:2px;min-height:1.25em}
.font-cred a{color:var(--muted);text-decoration:none;border-bottom:1px dotted var(--line)}
.font-cred a:hover{color:var(--accent)}
.font-refer{list-style:none;padding:0;margin:8px 0 0;display:flex;flex-wrap:wrap;gap:8px 22px;font-size:13px}
.font-refer li{color:var(--muted)}
.font-refer .font-name{color:var(--ink);font-size:13px}
.font-get{flex:none;align-self:center;color:var(--accent);text-decoration:none;border:1px solid var(--line);padding:4px 11px;border-radius:6px;white-space:nowrap}
.font-get:hover{border-color:var(--accent)}
.fbox{position:fixed;inset:0;z-index:1000;display:none;background:#fff}
.fbox.open{display:flex;flex-direction:column}
.fbox-top{height:60px;display:flex;align-items:center;gap:14px;padding:0 22px;border-bottom:1px solid var(--line)}
.fbox-name{font-weight:600;font-size:16px}
.fbox-era{color:var(--muted);font-size:13px}
.fbox-spacer{flex:1}
.fbox-get{font-size:13px;text-decoration:none;color:var(--accent);border:1px solid var(--line);padding:5px 11px;border-radius:7px}
.fbox-get:hover{border-color:var(--accent)}
.fbox-x{background:transparent;border:0;font-size:28px;line-height:1;cursor:pointer;color:var(--ink);padding:0 4px}
.fbox-body{flex:1;overflow:hidden;padding:24px 84px;display:flex;flex-direction:column;gap:18px;align-items:center;justify-content:center}
.fbox-body img{width:100%;height:100%;object-fit:contain}
.fbox-note{color:#9a3b3b;font-size:14px;max-width:60ch;text-align:center}
.fbox-nav{position:absolute;top:50%;transform:translateY(-50%);z-index:2;background:var(--card);
border:1px solid var(--line);color:var(--ink);width:48px;height:60px;font-size:28px;cursor:pointer;border-radius:8px}
.fbox-nav:hover{border-color:var(--accent);color:var(--accent)}
.fbox-prev{left:16px}.fbox-next{right:16px}
@media(max-width:640px){.fbox-body{padding:24px 16px}.fbox-nav{width:38px;height:50px;font-size:22px}}
.credits{margin-top:56px;border-top:1px solid var(--line);padding-top:28px}
.credits h2{font-size:19px;margin:0 0 6px}
.credits>p{color:var(--muted);font-size:13px;margin:0 0 18px;max-width:80ch}
.credits-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.credit{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.credit .who{font-weight:600;font-size:14px}
.credit .what{color:var(--muted);font-size:12.5px;margin:4px 0 8px}
.credit .lic{color:var(--muted);font-size:12px;margin:0 0 8px;line-height:1.4}
.credit .lic span{font-weight:600;color:var(--ink)}
.credit .lic a{display:inline;color:var(--accent)}
.credit a{color:var(--accent);text-decoration:none;font-size:12.5px;display:block;word-break:break-word}
.credit a:hover{text-decoration:underline}
footer{max-width:1600px;margin:0 auto;padding:24px 32px 60px;color:var(--muted);font-size:12.5px;
border-top:1px solid var(--line)}
footer a{color:var(--accent)}
.gh-link{display:inline-flex;align-items:center;gap:7px;margin-top:14px;color:var(--muted);
text-decoration:none;font-weight:600}
.gh-link:hover{color:var(--accent)}
.gh-link svg{flex:none}
.thumb::after{content:"⤢";position:absolute;top:8px;right:10px;font-size:14px;color:var(--muted);
opacity:0;transition:opacity .15s}
.thumb:hover::after{opacity:.7}
/* full-screen lightbox */
.lightbox{position:fixed;inset:0;z-index:1000;display:none}
.lightbox.open{display:block}
.lb-stage{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:88px 72px}
.lb-stage img{width:100%;height:100%;object-fit:contain}
.lb-stage.bg-transparent{background:
 linear-gradient(45deg,#d5dbe2 25%,#fff 25%,#fff 75%,#d5dbe2 75%) 0 0/30px 30px,
 linear-gradient(45deg,#d5dbe2 25%,#fff 25%,#fff 75%,#d5dbe2 75%) 15px 15px/30px 30px,#fff}
.lb-stage.bg-white{background:#fff}
.lb-stage.bg-dark{background:#0d0f12}
.lb-topbar{position:absolute;top:0;left:0;right:0;height:60px;display:flex;align-items:center;
gap:16px;padding:0 20px;background:rgba(20,24,30,.82);color:#fff;z-index:2;backdrop-filter:blur(6px)}
.lb-name{font-weight:600;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lb-spacer{flex:1}
.lb-toggle{display:flex;align-items:center;gap:6px;font-size:12px;color:#c5ccd6}
.lb-toggle button{font:inherit;font-size:12px;color:#c5ccd6;background:transparent;
border:1px solid rgba(255,255,255,.25);padding:4px 10px;border-radius:999px;cursor:pointer}
.lb-toggle button.on{background:#fff;color:#12151a;border-color:#fff}
.lb-dl{display:flex;gap:6px}
.lb-dl a{font-size:12px;text-decoration:none;color:#c5ccd6;border:1px solid rgba(255,255,255,.25);
padding:4px 10px;border-radius:6px}
.lb-dl a:hover{color:#fff;border-color:#fff}
.lb-x{background:transparent;border:0;color:#fff;font-size:26px;line-height:1;cursor:pointer;padding:0 4px}
.lb-nav{position:absolute;top:50%;transform:translateY(-50%);z-index:2;background:rgba(20,24,30,.55);
color:#fff;border:0;width:52px;height:64px;font-size:30px;cursor:pointer;border-radius:8px}
.lb-nav:hover{background:rgba(20,24,30,.85)}
.lb-prev{left:14px}.lb-next{right:14px}
@media(max-width:640px){.lb-stage{padding:70px 16px}.lb-dl{display:none}}
/* thin sticky top nav (shared across every page) */
.topnav{position:sticky;top:0;z-index:900;background:rgba(247,248,250,.86);
backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.topnav-inner{max-width:1600px;margin:0 auto;padding:0 32px;min-height:52px;
display:flex;align-items:center;gap:22px;flex-wrap:wrap}
.brand{font-weight:700;font-size:16px;letter-spacing:-.01em;color:var(--ink);
text-decoration:none;white-space:nowrap}
.brand b{color:var(--accent);font-weight:700}
.navlinks{display:flex;flex-wrap:wrap;gap:2px}
.navlinks a{font-size:13px;text-decoration:none;color:var(--muted);padding:6px 11px;
border-radius:7px;white-space:nowrap}
.navlinks a:hover{color:var(--ink);background:rgba(0,0,0,.05)}
.navlinks a.active{color:var(--accent);font-weight:600}
/* nav dropdown (About → Contributing / Licensing / Credits) */
.navitem{position:relative;display:inline-flex}
.submenu{position:absolute;top:100%;left:0;min-width:160px;background:var(--card);
border:1px solid var(--line);border-radius:9px;box-shadow:0 12px 30px rgba(0,0,0,.14);
padding:5px;display:none;z-index:30}
.navitem:hover .submenu,.navitem:focus-within .submenu{display:block}
.navlinks .submenu a{display:block;font-size:13px;padding:7px 12px;border-radius:6px}
@media(max-width:640px){.topnav-inner{padding:8px 16px;gap:6px 14px}
.wrap{padding:0 16px 48px}header{padding:28px 16px 16px}
/* no hover on touch — show the sub-links inline instead of as a dropdown */
.navitem{display:contents}
.submenu{position:static;display:flex;flex-wrap:wrap;background:none;border:0;box-shadow:none;
padding:0;min-width:0}
.navlinks .submenu a{padding:6px 11px}}
/* simple prose pages (about / links / reference placeholders) */
.prose{max-width:80ch;margin:8px 0}
.prose h1{font-size:30px;letter-spacing:-.02em;margin:0 0 22px}
.prose p{color:var(--ink);margin:0 0 14px}
.prose .lead{color:var(--muted);font-size:16px}
.prose a{color:var(--accent);text-decoration:none}
.prose a:hover{text-decoration:underline}
.signoff{margin:22px 0 0;font-style:italic;color:var(--ink);line-height:1.5}
.social{display:flex;flex-wrap:wrap;gap:16px;margin:14px 0 0}
.social a{display:inline-flex;align-items:center;gap:7px;color:var(--muted);text-decoration:none;
font-size:13px;font-weight:600}
.social a:hover{color:var(--accent)}
.social svg{width:19px;height:19px;flex:none}
.linklist{list-style:none;padding:0;margin:14px 0}
.linklist li{padding:9px 0;border-bottom:1px solid var(--line)}
.linklist a{color:var(--accent);text-decoration:none;font-weight:600}
.linklist a:hover{text-decoration:underline}
.linkcat{font-size:19px;margin:34px 0 2px;padding-bottom:6px;border-bottom:2px solid var(--ink)}
.linkcat-blurb{color:var(--muted);font-size:14px;margin:6px 0 0}
/* rendered Markdown doc pages (contributing / licensing / credits) */
.prose.doc h2{font-size:21px;margin:30px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.prose.doc h3{font-size:16px;margin:22px 0 6px}
.prose.doc h4{font-size:14px;margin:18px 0 4px}
.prose.doc ul,.prose.doc ol{padding-left:22px;margin:0 0 14px}
.prose.doc li{margin:4px 0}
.prose.doc a{color:var(--accent);text-decoration:none}
.prose.doc a:hover{text-decoration:underline}
.prose.doc code{background:rgba(0,0,0,.05);border:1px solid var(--line);border-radius:4px;
padding:1px 5px;font-size:.9em}
.prose.doc pre{background:#12151a;color:#e6e8ec;padding:14px 16px;border-radius:8px;overflow-x:auto}
.prose.doc pre code{background:none;border:0;padding:0;color:inherit;font-size:12.5px}
.prose.doc blockquote{margin:0 0 14px;padding:2px 14px;border-left:3px solid var(--accent);
color:var(--muted)}
.prose.doc table{border-collapse:collapse;width:100%;margin:0 0 16px;font-size:13.5px;display:block;overflow-x:auto}
.prose.doc th,.prose.doc td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
.prose.doc th{background:rgba(0,0,0,.03);font-weight:600}
.prose.doc hr{border:0;border-top:1px solid var(--line);margin:24px 0}
/* in-game reference gallery */
.rgame{margin-top:40px}
.rgame>.sh h2{font-size:19px}
.rteam{display:flex;align-items:center;gap:14px;margin:30px 0 14px;padding-bottom:10px;
border-bottom:1px solid var(--line)}
.rteam-logo{height:44px;width:auto;max-width:150px;object-fit:contain;display:block}
.rteam h3{margin:0;font-size:16px}
.rteam .rcount{font-size:11px;color:var(--muted);font-weight:400;border:1px solid var(--line);
border-radius:999px;padding:1px 9px;margin-left:2px}
.rgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.rcard{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;cursor:zoom-in}
.rcard:hover{border-color:var(--accent)}
.rthumb{aspect-ratio:16/9;background:#0d0f12;overflow:hidden}
.rthumb img{width:100%;height:100%;object-fit:cover;display:block}
.rmeta{padding:8px 12px;font-size:12.5px;color:var(--ink);border-top:1px solid var(--line)}
.rcredit{color:var(--muted);font-size:12px;margin:14px 0 0}
/* full-screen photo lightbox (screenshots) */
.plightbox{position:fixed;inset:0;z-index:1000;display:none;background:#0d0f12}
.plightbox.open{display:block}
.pl-topbar{position:absolute;top:0;left:0;right:0;height:56px;display:flex;align-items:center;
gap:14px;padding:0 20px;background:rgba(13,15,18,.72);color:#fff;z-index:2;backdrop-filter:blur(6px)}
.pl-logo{height:26px;width:auto;max-width:90px;object-fit:contain;filter:invert(1);flex:none}
.pl-name{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pl-spacer{flex:1}
.pl-x{background:transparent;border:0;color:#fff;font-size:26px;line-height:1;cursor:pointer;padding:0 4px}
.pl-stage{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:76px 72px}
.pl-stage img{max-width:100%;max-height:100%;object-fit:contain}
.pl-nav{position:absolute;top:50%;transform:translateY(-50%);z-index:2;background:rgba(255,255,255,.12);
color:#fff;border:0;width:52px;height:64px;font-size:30px;cursor:pointer;border-radius:8px}
.pl-nav:hover{background:rgba(255,255,255,.28)}
.pl-prev{left:14px}.pl-next{right:14px}
@media(max-width:640px){.pl-stage{padding:64px 12px}.pl-nav{width:40px;height:52px;font-size:24px}}
"""

# Teams page (brand-guidelines matrix + slide-out drawer). Appended to the shared
# styles.css. Class names are chosen not to collide with the marks/fonts/reference
# pages (the one overlap, the marks-page `.dl`, is renamed here to `.tdl`).
TEAMS_CSS = """
/* ================= Teams (brand guidelines) ================= */
:root{--gap:#f0a800;--warn:#c2570b;--ok:#1a9d63;--drawer:400px}
body{transition:padding-right .3s ease}
body.drawer-open{padding-right:var(--drawer)}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:14px 0 2px}
.legend .item{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;color:var(--muted)}
.key{width:22px;height:16px;border-radius:4px;border:1px solid var(--line);flex:none}
.key.gap{background:#fafafa;border:1px dashed #cbd0d6}
.key.na{background:#e9ebef}
.hint{font-size:12.5px;color:var(--muted)}
.matrix{display:grid;grid-auto-rows:minmax(112px,auto);width:100%;background:var(--card);
  border:1px solid var(--line);margin-top:12px}
.cell{border-right:1px solid var(--line);border-bottom:1px solid var(--line);padding:10px;position:relative}
.corner,.colhead{position:sticky;top:52px;z-index:5;background:#eef1f6}
.corner{left:0;z-index:6;border-bottom:2px solid var(--ink)}
.colhead{display:flex;flex-direction:column;justify-content:flex-end;gap:2px;padding:12px 14px 10px;border-bottom:2px solid var(--ink)}
.colhead .yr{font-size:11px;color:var(--muted);font-weight:600}
.colhead .nm{font-weight:800;font-size:14.5px;letter-spacing:-.015em;line-height:1.12;color:var(--ink)}
.slcell{display:flex;flex-direction:column;justify-content:center;gap:5px;padding:12px 14px;
  background:#fbfcfd;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}
.slcell.slhead{position:sticky;left:0;z-index:2;font-size:11px;color:var(--muted);font-weight:700;letter-spacing:.05em;text-transform:uppercase}
.slcell.lgrow{background:#f6f8fb;align-items:center;justify-content:center}
.slcell.slhead.lgrow{align-items:flex-start}
.slcell .thead-logo{max-height:40px;max-width:100%;width:auto;object-fit:contain;object-position:left center;align-self:flex-start}
.slcell .league-logo{max-height:64px;max-width:130px;width:auto;object-fit:contain;align-self:center}
.slcell .lg{align-self:flex-start;font-size:10px;font-weight:800;letter-spacing:.06em;color:var(--accent);background:#eaf4fc;border:1px solid #cfe6f8;border-radius:5px;padding:1px 7px}
.slcell .lgneed{font-size:9.5px;color:#9aa1a9;margin-top:2px}
.rowhead{position:sticky;left:0;z-index:2;display:flex;align-items:stretch;background:var(--card);border-right:2px solid var(--line);overflow:hidden}
.rowhead .bar{width:14px;align-self:stretch;flex:none}
.rowhead .rh-body{display:flex;flex-direction:column;justify-content:center;padding:10px 14px;min-width:0}
.rowhead .tname{font-weight:800;font-size:14px;letter-spacing:-.015em}
.rowhead .tsub{font-size:11px;color:var(--muted)}
.mk{display:flex;flex-direction:column;height:100%;cursor:pointer;border-radius:8px;transition:background .12s,box-shadow .12s;padding:2px}
.mk:hover{background:#f2f7fc;box-shadow:inset 0 0 0 1px #cfe3f5}
.mk .logo{flex:1;display:flex;align-items:center;justify-content:center;min-height:56px;overflow:hidden}
.mk .logo img{max-width:100%;max-height:72px;object-fit:contain}
.gapcell{display:flex;align-items:center;justify-content:center;height:100%;cursor:pointer;border:1px dashed #cbd0d6;border-radius:8px;color:#9aa1a9;font-size:11.5px;text-align:center;background:#fcfcfd;transition:border-color .12s,color .12s}
.gapcell:hover{border-color:var(--gap);color:var(--warn)}
.gapcell .plus{font-size:18px;line-height:1;display:block;margin-bottom:2px;color:#c3c8ce}
.gapcell:hover .plus{color:var(--gap)}
.cell.na{background:#eaecef}
.drawer{position:fixed;top:0;right:0;height:100vh;height:100dvh;width:var(--drawer);z-index:1000;display:flex;flex-direction:column;background:var(--card);border-left:3px solid var(--ink);box-shadow:-18px 0 50px rgba(16,20,26,.22);transform:translateX(100%);transition:transform .3s cubic-bezier(.22,1,.36,1)}
body.drawer-open .drawer{transform:translateX(0)}
.drawer-inner{flex:1;width:100%;overflow-y:auto;overflow-x:hidden}
.dhead{position:relative;padding:26px 24px 22px;color:#fff;flex:none;border-bottom:5px solid rgba(0,0,0,.18)}
.dhead .kicker{font-size:11px;letter-spacing:.14em;text-transform:uppercase;opacity:.92;font-weight:800}
.dhead h2{margin:4px 0 0;font-size:28px;font-weight:800;letter-spacing:-.03em;line-height:1;color:#fff}
.dhead .series{font-size:13px;opacity:.92;margin-top:6px;font-weight:500}
.dclose{position:absolute;top:14px;right:14px;background:rgba(255,255,255,.2);border:0;color:#fff;width:40px;height:40px;border-radius:50%;font-size:24px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;transition:background .12s}
.dclose:hover{background:rgba(255,255,255,.42)}
.dclose:active{background:rgba(255,255,255,.55)}
.dlogo{padding:26px 22px;display:flex;align-items:center;justify-content:center;min-height:150px;background:#fff;border-bottom:1px solid var(--line)}
.dlogo img{max-width:100%;max-height:150px;object-fit:contain}
.dbody{padding:18px 22px 30px}
.dbody h3{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 10px}
.status{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:4px 10px;border-radius:999px;margin-bottom:16px}
.status.official{color:var(--ok);background:#e8f7f0}
.status.sampled{color:var(--warn);background:#fff2e2}
.status.unknown{color:#5b6270;background:#eef0f3}
.status.gap{color:var(--warn);background:#fff7ed}
.csource{font-size:12px;color:var(--muted);line-height:1.5;margin:12px 0 0}
.csource b{color:var(--ink);font-weight:700}
.tdl{display:flex;gap:8px;margin:0 0 18px}
.tdl a{flex:1;text-align:center;font-size:12.5px;font-weight:600;text-decoration:none;color:var(--accent);border:1px solid var(--line);border-radius:8px;padding:8px 14px;transition:border-color .12s,background .12s}
.tdl a:hover{border-color:var(--accent);background:#eaf4fc}
.sw{display:flex;align-items:center;gap:12px;padding:9px 10px;border:1px solid var(--line);border-radius:10px;margin-bottom:8px;cursor:pointer;background:var(--card);transition:border-color .12s,transform .06s}
.sw:hover{border-color:var(--accent)}
.sw:active{transform:scale(.995)}
.sw .chip{width:40px;height:40px;border-radius:8px;flex:none;border:1px solid rgba(0,0,0,.1)}
.sw .swmeta{flex:1;min-width:0}
.sw .swname{font-weight:600;font-size:13.5px}
.sw .swhex{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.02em}
.sw .copy{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:3px 8px;white-space:nowrap}
.sw:hover .copy{color:var(--accent);border-color:var(--accent)}
.sw.copied .copy{color:#fff;background:var(--ok);border-color:var(--ok)}
.notes{font-size:13px;color:#374151;line-height:1.55;margin:16px 0 0}
.needbox{border:1px dashed var(--gap);background:#fffdf6;border-radius:10px;padding:14px 15px;font-size:13px;color:#6b4a12;line-height:1.5}
.needbox b{color:var(--warn)}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(20px);background:#14171c;color:#fff;font-size:13px;padding:9px 16px;border-radius:999px;opacity:0;pointer-events:none;transition:opacity .2s,transform .2s;z-index:1100}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.toast code{font-family:ui-monospace,Menlo,monospace}
@media (max-width:820px){
  body.drawer-open{padding-right:0;overflow:hidden}
  .drawer{width:100%;border-left:0;box-shadow:none}
  .matrix{--first:132px;--colmin:128px;width:max-content;min-width:100%}
}
"""

# Leagues page (sortable table of racing leagues + full-screen lightbox). Appended to the
# shared styles.css. Classes are prefixed `l`/`llb` so they don't collide with the marks,
# fonts, teams or reference pages.
LEAGUES_CSS = """
.ltable-wrap{overflow-x:auto;margin-top:18px;border:1px solid var(--line);border-radius:12px;background:var(--card)}
.ltable{border-collapse:collapse;width:100%;min-width:920px;font-size:13.5px}
.ltable th,.ltable td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:middle}
.ltable thead th{position:sticky;top:0;z-index:1;background:#eef1f6;font-size:12px;
text-transform:uppercase;letter-spacing:.04em;color:var(--muted);border-bottom:2px solid var(--ink);white-space:nowrap}
.ltable th.sortable{cursor:pointer;user-select:none}
.ltable th.sortable:hover{color:var(--ink)}
.ltable th.sortable .arw{opacity:.35;font-size:10px;margin-left:5px}
.ltable th.sorted-asc .arw,.ltable th.sorted-desc .arw{opacity:1;color:var(--accent)}
.ltable tbody tr{cursor:pointer}
.ltable tbody tr:hover{background:rgba(11,127,212,.055)}
.ltable tbody tr:last-child td{border-bottom:0}
.l-logo{width:124px}
.l-logo img{width:99px;height:57px;object-fit:contain;display:block}
.l-name{font-weight:700;font-size:16px;letter-spacing:-.01em;white-space:nowrap}
.l-game{white-space:nowrap}
.l-yr{white-space:nowrap;font-variant-numeric:tabular-nums}
.l-marks{white-space:nowrap}
.l-marks .mchip{display:inline-flex;align-items:center;justify-content:center;width:38px;height:30px;
padding:3px;margin:0 4px 0 0;border:1px solid var(--line);border-radius:6px;background:#fff;vertical-align:middle}
.l-marks .mchip img{max-width:100%;max-height:100%;object-fit:contain;display:block}
.l-fonts{min-width:120px}
.l-fonts .fpill{display:inline-block;font-size:11.5px;color:var(--muted);border:1px solid var(--line);
border-radius:999px;padding:2px 9px;margin:2px 4px 2px 0;white-space:nowrap}
.l-desc{color:var(--muted);font-size:12.5px;min-width:280px;max-width:420px;line-height:1.5}
.l-open{color:var(--accent);font-size:11px;font-weight:600;white-space:nowrap}
/* full-screen league lightbox */
.llb{position:fixed;inset:0;z-index:1000;display:none;background:rgba(12,15,20,.72)}
.llb.open{display:block}
.llb-panel{position:absolute;inset:0;overflow-y:auto;background:var(--bg)}
.llb-top{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:16px;padding:0 24px;height:64px;
background:rgba(20,24,30,.9);color:#fff;backdrop-filter:blur(6px)}
.llb-top .llb-emblem{height:38px;width:auto;max-width:120px;object-fit:contain}
.llb-title{font-weight:700;font-size:19px;letter-spacing:-.01em}
.llb-sub{color:#c5ccd6;font-size:13px}
.llb-spacer{flex:1}
.llb-x{background:transparent;border:0;color:#fff;font-size:28px;line-height:1;cursor:pointer;padding:0 4px}
.llb-arrow{position:fixed;top:50%;transform:translateY(-50%);z-index:3;width:46px;height:66px;
background:rgba(20,24,30,.5);color:#fff;border:0;border-radius:10px;font-size:30px;line-height:1;cursor:pointer;
display:flex;align-items:center;justify-content:center}
.llb-arrow:hover{background:rgba(20,24,30,.82)}
.llb-arrow:disabled{opacity:.28;cursor:default}
.llb-prev{left:16px}.llb-next{right:16px}
@media(max-width:900px){.llb-arrow{width:40px;height:54px;font-size:26px}.llb-prev{left:8px}.llb-next{right:8px}}
/* full-window two-column layout: left = full-height details card, right = marks row / fonts row */
.llb-body{padding:32px 40px 88px;display:grid;grid-template-columns:minmax(300px,32%) 1fr;
gap:44px;align-items:start}
/* left column is a full-height white "details" card (distinct from the checkerboard asset thumbs) */
.llb-left{min-width:0;position:sticky;top:96px;height:calc(100vh - 128px);
display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);border-top:4px solid var(--accent);
border-radius:16px;box-shadow:0 10px 34px rgba(12,15,20,.08);padding:20px 24px 24px;overflow-y:auto}
.llb-card-title{flex:none;font-size:26px;font-weight:800;letter-spacing:-.02em;margin:2px 0 14px;line-height:1.05}
.llb-left .herobox{flex:none;height:300px;background:#fff;border:1px solid var(--line);
border-radius:12px;padding:28px;display:flex;align-items:center;justify-content:center}
.llb-left .herobox img{max-width:100%;max-height:100%;object-fit:contain}
.llb-facts{flex:none;list-style:none;margin:18px 0 0;padding:0;font-size:14px}
.llb-facts li{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:10px 2px;border-bottom:1px solid var(--line)}
.llb-facts .k{color:var(--muted)}
.llb-facts .v{font-weight:600;text-align:right}
.llb-plats{display:inline-flex;flex-wrap:wrap;gap:5px;justify-content:flex-end}
.llb-plat{font-size:11px;font-weight:600;color:var(--muted);background:var(--bg);
border:1px solid var(--line);border-radius:5px;padding:2px 7px}
.llb-metac{display:inline-flex;align-items:center;gap:7px;text-decoration:none;font-weight:700;color:#fff;
border-radius:6px;padding:3px 9px;font-size:13px}
.llb-metac:hover{filter:brightness(1.08)}
.llb-metac .mc-out{font-size:10px;opacity:.85}
.llb-bg{flex:1 0 auto;margin-top:26px}
.llb-bg h2{margin-bottom:12px}
.llb-lore{font-size:15px;line-height:1.65;margin:0}
.llb-right{display:flex;flex-direction:column;gap:36px;min-width:0}
.llb h2{font-size:14px;margin:0 0 16px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.llb-mgrid,.llb-fgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px}
.llb-mcard,.llb-fcard{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.llb-mthumb{height:190px;display:flex;align-items:center;justify-content:center;padding:24px;background:
 linear-gradient(45deg,var(--check) 25%,transparent 25%,transparent 75%,var(--check) 75%) 0 0/22px 22px,
 linear-gradient(45deg,var(--check) 25%,transparent 25%,transparent 75%,var(--check) 75%) 11px 11px/22px 22px,#fff}
.llb-mthumb img{max-width:100%;max-height:150px;object-fit:contain}
.llb-mmeta{padding:10px 12px;border-top:1px solid var(--line)}
.llb-mnote{font-size:12px;color:var(--muted);line-height:1.45;margin:0 0 8px}
.llb-dl{display:flex;gap:6px}
.llb-dl a{font-size:11px;text-decoration:none;color:var(--muted);border:1px solid var(--line);padding:2px 8px;border-radius:6px}
.llb-dl a:hover{color:var(--accent);border-color:var(--accent)}
.llb-dl a.held{cursor:default;font-style:italic}
/* font cards mirror the mark cards: same column width, just taller (specimen on top, note below) */
.llb-fshot{height:150px;display:flex;align-items:center;justify-content:center;padding:20px;background:#fff;border-bottom:1px solid var(--line)}
.llb-fshot img{max-width:100%;max-height:100%;object-fit:contain}
.llb-fshot-none{color:#aab2bd;font-weight:700;font-size:17px;font-style:italic;border-bottom:1px dashed var(--line)}
.llb-fmeta{padding:12px 14px;display:flex;flex-direction:column;gap:8px;flex:1}
.llb-fname{font-weight:600;font-size:14px}
.llb-fnote{font-size:12px;color:var(--muted);line-height:1.45;flex:1}
.llb-fget{align-self:flex-start;color:var(--accent);text-decoration:none;border:1px solid var(--line);padding:4px 11px;border-radius:6px;font-size:12px;white-space:nowrap}
.llb-fget:hover{border-color:var(--accent)}
/* mobile: the card is natural-height and the right column (marks + fonts) wraps under it */
@media(max-width:900px){.llb-body{grid-template-columns:1fr;gap:28px;padding:24px 18px 64px}
  .llb-left{position:static;height:auto;overflow:visible}.llb-left .herobox{flex:none;height:240px}.llb-right{gap:28px}}
@media(max-width:520px){.llb-mgrid,.llb-fgrid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}}
"""

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


def _sample_sheet(path, name, phrase):
    """Outlined vector sample sheet (name + lore phrase + specimen) — no font hosted."""
    PAD = 30
    lines = [(name, 46, "#12151a", 28), (phrase, 23, "#3a3f47", 22),
             ("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 16, "#6b7280", 13),
             ("abcdefghijklmnopqrstuvwxyz  0123456789  &.,!?", 16, "#6b7280", 4)]
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


def _locate_font(family):
    """Return the font spec of an installed font matching `family`, else None.
    Matching is on the normalised family name, so 'OCR B' also matches 'OCRB'."""
    return _font_index().get(_norm_family(family))


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
    """Emit fonts/manifest.json — the font analogue of marks/manifest.json.

    Same shape as the vector manifest (name / generated / total / sections[] with
    per-item slug + name + credit), so both indexes can be consumed the same way.
    Font metadata is authored in the FONTS_* / FONT_CREDIT tables above; this file
    is GENERATED from them (never hand-edit). Fonts are referenced, not hosted:
    'specimen' is the committed outlined sample sheet, or null if none exists yet."""
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

    fan = ([entry(f, era, "free", FONT_BLOB + ttf.replace(" ", "%20"), "recreation")
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
    manifest = {
        "name": "awesome-wipeout — fonts",
        "generated": datetime.date.today().isoformat(),
        "note": ("Fonts are referenced, never hosted. Specimen SVGs are outlined from "
                 "locally-installed fonts at build time; specimen=null means no committed "
                 "sample yet. Generated from tools/build.py — do not hand-edit."),
        "total": sum(len(s["fonts"]) for s in sections),
        "sections": sections,
    }
    os.makedirs(os.path.join(ROOT, "fonts"), exist_ok=True)
    with open(os.path.join(ROOT, "fonts", "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


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
    _write("styles.css", CSS + TEAMS_CSS + LEAGUES_CSS)
    _write("analytics.js", _ANALYTICS_JS)


FOOTER = """<footer>
  <p>WipEout and all related logos, names and marks are trademarks of Sony Interactive Entertainment /
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


def _document(slug, title, header_inner, body, scripts=""):
    """Wrap a page's body in the shared shell: <head>, sticky nav, optional hero
    <header>, content <div class="wrap">, footer, then any page scripts."""
    hero = f"<header>\n{header_inner}\n</header>\n" if header_inner else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · awesome-wipeout</title>
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


def build_doc_pages():
    made = []
    for src, outfile, title in DOC_PAGES:
        path = os.path.join(ROOT, src)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            rendered = md_to_html(f.read())
        for md, htmlf in DOC_LINK_MAP.items():
            rendered = rendered.replace(f'href="{md}"', f'href="{htmlf}"')
        rendered = _fix_repo_links(rendered)
        body = f'<div class="prose doc">\n{rendered}\n</div>'
        _write(outfile, _document(outfile[:-5], title, "", body))
        made.append(outfile)
    return made


def _linklist(links):
    """Render an authored [{label,url,note?}] array as a <ul>. Local .md/.html
    targets open in-place; external (http) links open in a new tab."""
    items = []
    for l in links:
        note = f' &mdash; {esc(l["note"])}' if l.get("note") else ""
        ext = l["url"].startswith("http")
        tgt = ' target="_blank" rel="noopener"' if ext else ""
        items.append(f'<li><a href="{esc(l["url"])}"{tgt}>{esc(l["label"])}</a>{note}</li>')
    return f'<ul class="linklist">{"".join(items)}</ul>'


# Inline social icons (self-contained; stroke uses currentColor). Keyed by `icon` in
# a prose page's [[page.social]] entries.
SOCIAL_ICONS = {
    "globe": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/>'
             '<line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 '
             '15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    "instagram": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="2" width="20" '
                 'height="20" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/>'
                 '<line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/></svg>',
}


def build_prose_page(page):
    """A simple intro/prose page (about / links). All copy is authored in
    data/pages.toml — `intro`, `body` (Markdown), `paragraphs[]`, an optional
    `sign_off` + `social[]`, a flat `links[]`, and/or grouped `[[page.section]]`."""
    parts = []
    if page.get("intro"):
        parts.append(f'<p class="lead">{esc(page["intro"])}</p>')
    if page.get("body"):                       # rich Markdown body (bold/italic/links)
        parts.append(md_to_html(page["body"]))
    for para in page.get("paragraphs", []):
        parts.append(f"<p>{esc(para)}</p>")
    if page.get("sign_off"):
        parts.append('<p class="signoff">'
                     + "<br>".join(esc(l) for l in page["sign_off"].split("\n")) + "</p>")
    if page.get("social"):
        icons = "".join(
            f'<a href="{esc(s["url"])}" target="_blank" rel="noopener">'
            f'{SOCIAL_ICONS.get(s.get("icon", ""), "")}{esc(s["label"])}</a>'
            for s in page["social"])
        parts.append(f'<div class="social">{icons}</div>')
    if page.get("links"):
        parts.append(_linklist(page["links"]))
    for sec in page.get("section", []):
        parts.append(f'<h2 class="linkcat">{esc(sec["title"])}</h2>')
        if sec.get("blurb"):
            parts.append(f'<p class="linkcat-blurb">{esc(sec["blurb"])}</p>')
        parts.append(_linklist(sec.get("links", [])))
    body = (f'<div class="prose"><h1>{esc(page["title"])}</h1>\n'
            + "\n".join(parts) + "\n</div>")
    _write(page["file"], _document(page["slug"], page["title"], "", body))


def _photo_lightbox_html():
    return """<div class="plightbox" id="plightbox" aria-hidden="true">
  <div class="pl-topbar">
    <img class="pl-logo" id="plLogo" alt="">
    <div class="pl-name" id="plName"></div>
    <div class="pl-spacer"></div>
    <button class="pl-x" id="plClose" aria-label="Close">&times;</button>
  </div>
  <button class="pl-nav pl-prev" id="plPrev" aria-label="Previous">&#8249;</button>
  <button class="pl-nav pl-next" id="plNext" aria-label="Next">&#8250;</button>
  <div class="pl-stage" id="plStage"><img id="plImg" alt=""></div>
</div>"""


def _photo_lightbox_script(shots):
    return """<script>
(function(){
  var SHOTS=__SHOTS__;
  var lb=document.getElementById('plightbox'), img=document.getElementById('plImg'),
      nameEl=document.getElementById('plName'), logo=document.getElementById('plLogo'),
      stage=document.getElementById('plStage'); var i=0;
  function show(n){ i=(n+SHOTS.length)%SHOTS.length; var s=SHOTS[i];
    img.src=s.full; img.alt=s.name; nameEl.textContent=(s.team? s.team+' — ':'')+s.name;
    if(s.logo){ logo.src=s.logo; logo.style.display=''; } else { logo.removeAttribute('src'); logo.style.display='none'; } }
  function openLb(n){ show(n); lb.classList.add('open'); lb.setAttribute('aria-hidden','false'); document.body.style.overflow='hidden'; }
  function closeLb(){ lb.classList.remove('open'); lb.setAttribute('aria-hidden','true'); img.removeAttribute('src'); document.body.style.overflow=''; }
  document.querySelectorAll('.rcard').forEach(function(c){
    c.addEventListener('click', function(){ openLb(parseInt(c.getAttribute('data-idx'),10)); }); });
  document.getElementById('plClose').addEventListener('click', closeLb);
  document.getElementById('plPrev').addEventListener('click', function(){ show(i-1); });
  document.getElementById('plNext').addEventListener('click', function(){ show(i+1); });
  stage.addEventListener('click', function(e){ if(e.target===stage) closeLb(); });
  document.addEventListener('keydown', function(e){ if(!lb.classList.contains('open')) return;
    if(e.key==='Escape') closeLb(); else if(e.key==='ArrowLeft') show(i-1); else if(e.key==='ArrowRight') show(i+1); });
})();
</script>""".replace("__SHOTS__", json.dumps(shots))


def build_reference_page(page, manifest):
    """The in-game reference gallery: screenshots grouped by game → team, each team
    headed by its emblem (a mark reused as the header), tiles opening a full-screen
    photo lightbox that also shows the team emblem."""
    games = manifest["games"]
    total = manifest["total"]
    # One toc entry per team (there's effectively one game — Omega — so teams are the
    # useful navigation unit), jumping to each team's anchored header.
    toc = "".join(
        f'<a href="#{t["id"]}">{esc(t["name"])} ({len(t["images"])})</a>'
        for g in games for t in g["teams"])
    shots = []
    secs = []
    for g in games:
        blocks = []
        for t in g["teams"]:
            logo_html = (f'<img class="rteam-logo" src="{esc(t["logo"])}" alt="{esc(t["name"])} emblem">'
                         if t.get("logo") else "")
            cards = []
            for im in t["images"]:
                i = len(shots)
                shots.append({"name": im["name"], "team": t["name"],
                              "full": im["jpg"], "logo": t.get("logo")})
                cards.append(
                    f'      <div class="rcard" data-idx="{i}">\n'
                    f'        <div class="rthumb"><img src="{esc(im["thumb"])}" '
                    f'alt="{esc(t["name"])} — {esc(im["name"])}" loading="lazy"></div>\n'
                    f'        <div class="rmeta">{esc(im["name"])}</div>\n'
                    f'      </div>')
            blocks.append(
                f'    <div class="rteam" id="{t["id"]}">{logo_html}'
                f'<h3>{esc(t["name"])}</h3><span class="rcount">{len(t["images"])} shots</span></div>\n'
                f'    <div class="rgrid">\n{chr(10).join(cards)}\n    </div>')
        secs.append(
            f'  <section class="rgame" id="{g["id"]}">\n'
            f'    <div class="sh"><h2>{esc(g["name"])}</h2><p>{esc(g["blurb"])}</p></div>\n'
            f'{chr(10).join(blocks)}\n  </section>')
    cred = manifest.get("credit") or {}
    cred_html = ""
    if cred.get("holder"):
        note = f' &mdash; {esc(cred["note"])}' if cred.get("note") else ""
        cred_html = f'<p class="rcredit">{esc(cred["holder"])}{note}</p>'
    n_teams = sum(len(g["teams"]) for g in games)
    header_inner = f"""  <h1>{esc(page["title"])}</h1>
  <p class="lead">{esc(page.get("intro", ""))}</p>
  <span class="stat">{total} screenshots</span>
  <span class="stat">{n_teams} teams</span>
  <div class="toc">{toc}</div>
  {cred_html}"""
    body = "\n".join(secs)
    scripts = f"{_photo_lightbox_html()}\n{_photo_lightbox_script(shots)}"
    _write(page["file"], _document(page["slug"], page["title"], header_inner, body, scripts))


def _lum(hexv):
    h = hexv.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


_TEAMS_SCRIPT = r"""<script>
const REC = __REC_JSON__;
const drawer = document.getElementById("drawer");
const dInner = document.getElementById("drawerInner");
const toast = document.getElementById("toast");
let toastT;
function showToast(m){ toast.innerHTML=m; toast.classList.add("show"); clearTimeout(toastT); toastT=setTimeout(function(){toast.classList.remove("show");},1400); }
function esc(s){ return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function swatchHTML(x){ return '<div class="sw" data-hex="'+x.hex+'"><span class="chip" style="background:'+x.hex+'"></span><span class="swmeta"><span class="swname">'+esc(x.name)+'</span><span class="swhex">'+x.hex+'</span></span><span class="copy">Copy</span></div>'; }
function openCell(id){
  const c = REC[id]; if(!c) return;
  const head='<div class="dhead" style="background:'+c.bar+';color:'+c.txt+'"><button class="dclose" onclick="closeDrawer()" aria-label="Close">×</button><div class="kicker">'+esc(c.series)+' · '+c.yr+(c.league?' · '+esc(c.league):'')+'</div><h2>'+esc(c.team)+'</h2><div class="series">'+esc(c.sub)+'</div></div>';
  let logoBlock="", body="";
  if(c.state==="gap"){
    logoBlock='<div class="dlogo"><div style="color:#b6bcc3;font-size:13px;text-align:center"><div style="font-size:34px;line-height:1">◍</div>no logo yet</div></div>';
    body='<span class="status gap">◍ Logo needed</span><div class="needbox"><b>This one’s a gap.</b> '+esc(c.team)+' raced in '+esc(c.series)+', but we don’t have the era logo yet. Drop <code>marks/teams/'+c.sser+'/'+c.steam+'.svg</code> and it fills in automatically.</div>';
  } else {
    logoBlock='<div class="dlogo"><img src="'+c.png+'" alt="'+esc(c.team)+' — '+esc(c.series)+'"></div>';
    const dl='<div class="tdl"><a href="'+c.svg+'" download>SVG</a><a href="'+c.png+'" download>PNG</a></div>';
    let colours;
    if(c.state==="official"){ colours='<h3>Colours</h3>'+c.colors.map(swatchHTML).join('')+'<p class="csource"><b>Official.</b> Taken from brand documentation.</p>'+(c.notes?'<p class="notes">'+esc(c.notes)+'</p>':''); }
    else if(c.state==="sampled"){ colours='<h3>Colours</h3>'+c.colors.map(swatchHTML).join('')+'<p class="csource"><b>Sampled.</b> Measured from the logo art — approximate, and may differ from the official values.</p>'+(c.notes?'<p class="notes">'+esc(c.notes)+'</p>':''); }
    else { colours='<span class="status unknown">? Colours unknown</span><div class="needbox">We have the <b>'+esc(c.series)+'</b> logo for '+esc(c.team)+', but its colours aren’t documented or sampled yet.</div>'; }
    body=dl+colours;
  }
  dInner.innerHTML=head+logoBlock+'<div class="dbody">'+body+'</div>';
  document.body.classList.add("drawer-open"); drawer.setAttribute("aria-hidden","false"); dInner.scrollTop=0;
}
function closeDrawer(){ document.body.classList.remove("drawer-open"); drawer.setAttribute("aria-hidden","true"); }
function copy(t){ if(navigator.clipboard&&navigator.clipboard.writeText) return navigator.clipboard.writeText(t); var a=document.createElement("textarea");a.value=t;a.style.position="fixed";a.style.opacity="0";document.body.appendChild(a);a.select();try{document.execCommand("copy");}catch(e){}document.body.removeChild(a);return Promise.resolve(); }
document.addEventListener("click", function(e){
  var cell=e.target.closest("[data-id]"); if(cell){ openCell(cell.getAttribute("data-id")); return; }
  var sw=e.target.closest(".sw"); if(sw){ var hex=sw.getAttribute("data-hex"); copy(hex).then(function(){ sw.classList.add("copied"); sw.querySelector(".copy").textContent="Copied"; showToast('Copied <code>'+hex+'</code>'); setTimeout(function(){ sw.classList.remove("copied"); sw.querySelector(".copy").textContent="Copy"; },1100); }); }
});
document.addEventListener("keydown", function(e){ if(e.key==="Escape") closeDrawer(); });
</script>"""


def build_teams_page(page):
    """The Teams page (brand guidelines): a series (columns) x teams (rows) matrix driven
    by data/teams.toml. The grid is server-rendered here; a small script drives the
    slide-out drawer (colours + click-to-copy hex + SVG/PNG downloads). Logos reuse the
    marks/ vectors — shown as PNG, offered as SVG+PNG (the shared analytics.js listener
    fires download_svg / download_png from the a[download] links)."""
    data = _load_toml("teams.toml")
    series = data.get("series", [])
    teams = data.get("team", [])
    brands = {(b["team"], b["series"]): b for b in data.get("brand", [])}

    def png(rel):  # marks/<rel>.svg -> the PNG shown in the grid
        return "marks/" + rel[:-4] + ".png" if rel.endswith(".svg") else "marks/" + rel

    cells = ['<div class="cell corner"></div>']
    for s in series:
        cells.append(f'<div class="cell colhead"><span class="yr">{s["year"]}</span>'
                     f'<span class="nm">{esc(s["name"])}</span></div>')
    cells.append('<div class="slcell slhead">Series</div>')
    for s in series:
        t = s.get("title")
        logo = (f'<img class="thead-logo" src="{png(t)}" alt="{esc(s["name"])}">'
                if t else f'<span class="nm">{esc(s["name"])}</span>')
        cells.append(f'<div class="slcell">{logo}</div>')
    cells.append('<div class="slcell slhead lgrow">League</div>')
    for s in series:
        ll, lg = s.get("league_logo"), s.get("league")
        if ll:
            inner = f'<img class="league-logo" src="{png(ll)}" alt="{esc(lg or "")} league">'
        elif lg:
            inner = f'<span class="lg">{esc(lg)}</span><span class="lgneed">emblem needed</span>'
        else:
            inner = ""
        cells.append(f'<div class="slcell lgrow">{inner}</div>')

    rec = {}
    for ti, t in enumerate(teams):
        txt = "#12151a" if _lum(t["bar"]) > .6 else "#fff"
        cells.append(f'<div class="cell rowhead"><span class="bar" style="background:{esc(t["bar"])}"></span>'
                     f'<span class="rh-body"><span class="tname">{esc(t["name"])}</span>'
                     f'<span class="tsub">{esc(t.get("sub",""))}</span></span></div>')
        for si, s in enumerate(series):
            b = brands.get((t["slug"], s["slug"]))
            cid = f"{ti}_{si}"
            base = {"team": t["name"], "sub": t.get("sub", ""), "bar": t["bar"], "txt": txt,
                    "series": s["name"], "yr": s["year"], "league": s.get("league", "")}
            if b:
                state = b.get("state") or "unknown"
                cells.append(f'<div class="cell"><div class="mk" data-id="{cid}">'
                             f'<div class="logo"><img src="{png(b["logo"])}" '
                             f'alt="{esc(t["name"])} — {esc(s["name"])}" loading="lazy"></div></div></div>')
                rec[cid] = {**base, "state": state, "png": png(b["logo"]), "svg": "marks/" + b["logo"],
                            "colors": b.get("colors", []), "notes": b.get("notes", "")}
            elif t["slug"] in s.get("roster", []):
                cells.append(f'<div class="cell"><div class="gapcell" data-id="{cid}">'
                             f'<span><span class="plus">+</span>logo&nbsp;needed</span></div></div>')
                rec[cid] = {**base, "state": "gap", "sser": s["slug"], "steam": t["slug"]}
            else:
                cells.append(f'<div class="cell na" title="{esc(t["name"])} didn’t race in {esc(s["name"])}"></div>')

    ncols = len(series)
    grid_style = f"grid-template-columns:var(--first,168px) repeat({ncols}, minmax(var(--colmin,0px),1fr))"
    matrix = f'<div class="matrix" style="{grid_style}">\n' + "\n".join(cells) + "\n</div>"

    header_inner = (f'<h1>{esc(page["title"])}</h1>\n'
                    f'<p class="lead">{esc(page.get("intro", ""))}</p>\n'
                    '<div class="legend">'
                    '<span class="item"><span class="key gap"></span>Logo needed</span>'
                    '<span class="item"><span class="key na"></span>Didn’t race this series</span>'
                    '<span class="hint">· click any logo for its colours &amp; status →</span></div>')
    body = (f'{matrix}\n'
            '<aside class="drawer" id="drawer" aria-hidden="true"><div class="drawer-inner" id="drawerInner"></div></aside>\n'
            '<div class="toast" id="toast"></div>')
    scripts = _TEAMS_SCRIPT.replace("__REC_JSON__", json.dumps(rec))
    _write(page["file"], _document(page["slug"], page["title"], header_inner, body, scripts))


_LEAGUES_SCRIPT = r"""<script>
const LREC = __LREC_JSON__;
const llb = document.getElementById("llb");
const llbPanel = document.getElementById("llbPanel");
function esc(s){ return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function markCard(m){
  var dl;
  if(m.svg){ dl='<div class="llb-dl"><a href="'+esc(m.svg)+'" download>SVG</a><a href="'+esc(m.png)+'" download>PNG</a></div>'; }
  else { dl='<div class="llb-dl"><a href="'+esc(m.png)+'" download>PNG</a>'+(m.source?'<a class="held" href="'+esc(m.source)+'" target="_blank" rel="noopener" title="The artist hosts the vector">SVG held ↗</a>':'<span class="held">vector held</span>')+'</div>'; }
  return '<div class="llb-mcard"><div class="llb-mthumb"><img src="'+esc(m.png)+'" alt="'+esc(m.name)+'" loading="lazy"></div><div class="llb-mmeta"><div class="llb-mnote">'+esc(m.note)+'</div>'+dl+'</div></div>';
}
function fontCard(f){
  var shot = f.specimen ? '<div class="llb-fshot"><img src="'+esc(f.specimen)+'" alt="'+esc(f.name)+' specimen"></div>' : '<div class="llb-fshot llb-fshot-none">'+esc(f.name)+'</div>';
  var get = f.source ? '<a class="llb-fget font-get" data-font="'+esc(f.name)+'" href="'+esc(f.source)+'" target="_blank" rel="noopener">get ↗</a>' : '';
  return '<div class="llb-fcard">'+shot+'<div class="llb-fmeta"><div class="llb-fname">'+esc(f.name)+'</div><div class="llb-fnote">'+esc(f.note)+'</div>'+get+'</div></div>';
}
function metacRow(c){
  if(!c.metascore) return '';
  var s=c.metascore, bg='#54a72a', fg='#fff';
  if(s<50){ bg='#d14b3d'; } else if(s<75){ bg='#e6b800'; fg='#1a1a1a'; }
  return '<li><span class="k">Metacritic</span><span class="v"><a class="llb-metac" style="background:'+bg+';color:'+fg
    +'" href="'+esc(c.metacritic)+'" target="_blank" rel="noopener" title="Metascore on Metacritic">'
    +s+'<span class="mc-out" style="color:'+fg+'">↗</span></a></span></li>';
}
var currentId=null;
function orderedSlugs(){ return [].slice.call(document.querySelectorAll("#lbody .lrow")).map(function(r){return r.getAttribute("data-id");}); }
function showLeague(id){
  var c = LREC[id]; if(!c) return;
  currentId=id;
  var facts='<ul class="llb-facts">'
    +'<li><span class="k">Game</span><span class="v">'+esc(c.game)+'</span></li>'
    +'<li><span class="k">Released</span><span class="v">'+c.released+'</span></li>'
    +'<li><span class="k">In-game year</span><span class="v">'+esc(c.game_year)+'</span></li>'
    +(c.platforms&&c.platforms.length?'<li><span class="k">Platforms</span><span class="v"><span class="llb-plats">'
      +c.platforms.map(function(p){return '<span class="llb-plat">'+esc(p)+'</span>';}).join('')+'</span></span></li>':'')
    +metacRow(c)
    +'</ul>';
  var left='<div class="llb-left"><div class="llb-card-title">'+esc(c.name)+'</div><div class="herobox"><img src="'+esc(c.logo)+'" alt="'+esc(c.name)+' emblem"></div>'+facts+'<div class="llb-bg"><h2>Background</h2><p class="llb-lore">'+esc(c.blurb)+'</p></div></div>';
  var marks = c.marks.length ? '<section><h2>Marks</h2><div class="llb-mgrid">'+c.marks.map(markCard).join('')+'</div></section>' : '';
  var fonts = c.fonts.length ? '<section><h2>Fonts</h2><div class="llb-fgrid">'+c.fonts.map(fontCard).join('')+'</div></section>' : '';
  var right='<div class="llb-right">'+marks+fonts+'</div>';
  var top='<div class="llb-top"><img class="llb-emblem" src="'+esc(c.logo)+'" alt=""><div><div class="llb-title">'+esc(c.name)+'</div><div class="llb-sub">'+esc(c.game)+' · '+esc(c.game_year)+'</div></div><div class="llb-spacer"></div><button class="llb-x" aria-label="Close">×</button></div>';
  llbPanel.innerHTML=top+'<div class="llb-body">'+left+right+'</div>';
  llb.classList.add("open"); llb.setAttribute("aria-hidden","false");
  document.body.style.overflow="hidden"; llbPanel.scrollTop=0;
  var o=orderedSlugs(), i=o.indexOf(id);
  document.getElementById("llbPrev").disabled=(i<=0);
  document.getElementById("llbNext").disabled=(i<0||i>=o.length-1);
}
function navLeague(dir){
  if(!currentId) return;
  var o=orderedSlugs(), i=o.indexOf(currentId); if(i<0) return;
  var j=i+dir; if(j<0||j>=o.length) return;
  location.hash=o[j];
}
function hideLeague(){ currentId=null; llb.classList.remove("open"); llb.setAttribute("aria-hidden","true"); document.body.style.overflow=""; }
function openLeague(id){ if(LREC[id]) location.hash=id; }
function closeLeague(){ if(location.hash){ history.replaceState(null,"",location.pathname+location.search); } hideLeague(); }
function handleHash(){ var id=(location.hash||"").slice(1); if(id&&LREC[id]){ showLeague(id); } else { hideLeague(); } }
window.addEventListener("hashchange", handleHash);
document.addEventListener("click", function(e){
  if(e.target.closest(".llb-dl a")||e.target.closest(".llb-fget")) return;
  if(e.target.closest(".llb-x")){ closeLeague(); return; }
  if(e.target.closest(".llb-prev")){ navLeague(-1); return; }
  if(e.target.closest(".llb-next")){ navLeague(1); return; }
  var row=e.target.closest(".lrow"); if(row){ openLeague(row.getAttribute("data-id")); return; }
  if(e.target===llb){ closeLeague(); return; }
});
document.addEventListener("keydown", function(e){
  if(!llb.classList.contains("open")) return;
  if(e.key==="Escape") closeLeague();
  else if(e.key==="ArrowLeft") navLeague(-1);
  else if(e.key==="ArrowRight") navLeague(1);
});
function sortBy(key, d){
  var tbody=document.getElementById("lbody");
  var rows=[].slice.call(tbody.querySelectorAll(".lrow"));
  rows.sort(function(a,b){ return (parseInt(a.getAttribute("data-"+key),10)-parseInt(b.getAttribute("data-"+key),10))*d; });
  rows.forEach(function(r){ tbody.appendChild(r); });
  document.querySelectorAll(".ltable th.sortable").forEach(function(th){
    th.classList.remove("sorted-asc","sorted-desc");
    if(th.getAttribute("data-sort")===key) th.classList.add(d>0?"sorted-asc":"sorted-desc");
  });
}
var _dir={ingame:1};
document.querySelectorAll(".ltable th.sortable").forEach(function(th){
  th.addEventListener("click", function(){
    var k=th.getAttribute("data-sort");
    _dir[k] = _dir[k]===1 ? -1 : 1;
    sortBy(k, _dir[k]);
  });
});
handleHash();  // open the deep-linked league (leagues.html#<slug>) on load
</script>"""


def build_leagues_page(page):
    """The Leagues page: a sortable table of every anti-gravity racing league (rows) from
    data/leagues.toml, each row opening a full-screen lightbox with the league's marks, fonts
    and lore. Marks and fonts are resolved from the generated manifests so their names,
    downloads and specimens stay 1:1 with the collections (reference-only marks — a .png with
    no sibling vector — link out to where the artist hosts the SVG instead of downloading)."""
    data = _load_toml("leagues.toml")
    leagues = data.get("league", [])

    with open(os.path.join(ROOT, "marks", "manifest.json")) as f:
        mman = json.load(f)
    MK = {}
    for s in mman["sections"]:
        for a in s["assets"]:
            MK[(a["svg"] or a["png"])[len("marks/"):]] = a

    with open(os.path.join(ROOT, "fonts", "manifest.json")) as f:
        fman = json.load(f)
    FT = {}
    for s in fman["sections"]:
        for it in (s.get("items") or s.get("fonts") or []):
            FT[it["slug"]] = it

    def png(rel):
        return "marks/" + (rel[:-4] + ".png" if rel.endswith(".svg") else rel)

    def font_name(slug):
        return (FT.get(slug) or {}).get("name", slug)

    rows, rec = [], {}
    for lg in leagues:
        slug = lg["slug"]
        marks_out = []
        for m in lg.get("marks", []):
            a = MK.get(m["file"])
            is_ref = not m["file"].endswith(".svg") or (a is not None and not a.get("svg"))
            marks_out.append({
                "name": a["name"] if a else m["file"],
                "note": m.get("note", ""),
                "png": png(m["file"]),
                "svg": None if is_ref else "marks/" + m["file"],
                "source": (a or {}).get("source"),
            })
        fonts_out = [{
            "name": font_name(fo["slug"]),
            "note": fo.get("note", ""),
            "specimen": (FT.get(fo["slug"]) or {}).get("specimen"),
            "source": (FT.get(fo["slug"]) or {}).get("source"),
        } for fo in lg.get("fonts", [])]
        rec[slug] = {
            "name": lg["name"], "game": lg["game"], "released": lg["released"],
            "game_year": lg["game_year"], "blurb": " ".join(lg["blurb"].split()),
            "logo": png(lg["logo"]), "marks": marks_out, "fonts": fonts_out,
            "metascore": lg.get("metascore"), "metacritic": lg.get("metacritic"),
            "platforms": lg.get("platforms", []),
        }
        mchips = "".join(
            f'<span class="mchip"><img src="{esc(png(m["file"]))}" alt="" '
            f'title="{esc(m.get("note",""))}" loading="lazy"></span>'
            for m in lg.get("marks", []))
        fpills = "".join(
            f'<span class="fpill" title="{esc(fo.get("note",""))}">{esc(font_name(fo["slug"]))}</span>'
            for fo in lg.get("fonts", []))
        rows.append(
            f'<tr class="lrow" data-id="{esc(slug)}" data-released="{lg["released"]}" '
            f'data-ingame="{lg["game_year_sort"]}">'
            f'<td class="l-logo"><img src="{esc(png(lg["logo"]))}" alt="{esc(lg["name"])} emblem" loading="lazy"></td>'
            f'<td class="l-name">{esc(lg["name"])}</td>'
            f'<td class="l-game">{esc(lg["game"])}</td>'
            f'<td class="l-yr">{lg["released"]}</td>'
            f'<td class="l-yr">{esc(lg["game_year"])}</td>'
            f'<td class="l-marks">{mchips}</td>'
            f'<td class="l-fonts">{fpills}</td>'
            f'<td class="l-desc">{esc(" ".join(lg["blurb"].split()))}</td>'
            f'</tr>')

    thead = ('<thead><tr>'
             '<th></th><th>League</th><th>Game</th>'
             '<th class="sortable" data-sort="released">Released<span class="arw">▲▼</span></th>'
             '<th class="sortable sorted-asc" data-sort="ingame">In-game year<span class="arw">▲▼</span></th>'
             '<th>Marks</th><th>Fonts</th><th>Background</th>'
             '</tr></thead>')
    table = ('<div class="ltable-wrap"><table class="ltable" id="ltable">' + thead +
             '<tbody id="lbody">' + "".join(rows) + '</tbody></table></div>')

    header_inner = (f'<h1>{esc(page["title"])}</h1>\n'
                    f'<p class="lead">{esc(page.get("intro", ""))}</p>')
    body = (table + '\n'
            '<div class="llb" id="llb" aria-hidden="true">'
            '<button class="llb-arrow llb-prev" id="llbPrev" aria-label="Previous league">‹</button>'
            '<button class="llb-arrow llb-next" id="llbNext" aria-label="Next league">›</button>'
            '<div class="llb-panel" id="llbPanel"></div></div>')
    scripts = _LEAGUES_SCRIPT.replace("__LREC_JSON__", json.dumps(rec))
    _write(page["file"], _document(page["slug"], page["title"], header_inner, body, scripts))


def build_pages(manifest, ref_manifest=None):
    """Render every registered page. Marks + fonts share the intermediate build
    below (cards, credits, lightbox); the two are written as separate documents.
    Reference pages render the screenshot gallery; anything else is a prose page."""
    toc = "".join(
        f'<a href="#{s["id"]}">{esc(s["title"])} ({len(s["assets"])})</a>'
        for s in manifest["sections"])
    secs = []
    lb_assets = []
    idx = 0
    for s in manifest["sections"]:
        cards = []
        for a in s["assets"]:
            # Thumbnails reference the SVG via <img> (not inline) so each asset
            # is an isolated document — this avoids internal id collisions
            # (clip_1, use refs, …) that blank out logos when many SVGs share a page.
            # Reference-only assets have no hosted SVG — show the indicative PNG and
            # link out to the source for the vector.
            is_ref = a.get("svg") is None
            thumb = a["png"] if is_ref else a["svg"]
            lb_entry = {"name": a["name"], "svg": a["svg"], "png": a["png"],
                        "id": (a["svg"] or a["png"])[len("marks/"):].rsplit(".", 1)[0]}
            if is_ref:
                lb_entry["source"] = a.get("source")
                lb_entry["who"] = a.get("credit_name")
            lb_assets.append(lb_entry)
            src = (f'<a class="src" href="#credit-{esc(a["credit"])}" '
                   f'title="Source — jump to credits">source: {esc(a["credit_name"])}</a>'
                   if a.get("credit") else '<span class="src src-none">source: needed</span>')
            if is_ref:
                # Restricted vector: both buttons shown, but SVG opens the "held by the
                # artist" overlay (data-locked-*) instead of downloading — no vector here.
                dl = (f'<div class="dl"><a class="locked" role="button" href="#" '
                      f'data-locked-src="{esc(a["source"])}" '
                      f'data-locked-who="{esc(a["credit_name"])}">SVG</a>'
                      f'<a href="{esc(a["png"])}" download>PNG</a></div>')
            else:
                dl = (f'<div class="dl"><a href="{esc(a["svg"])}" download>SVG</a>\n'
                      f'          <a href="{esc(a["png"])}" download>PNG</a></div>')
            cards.append(f"""      <div class="card">
        <div class="thumb" data-idx="{idx}"><img src="{esc(thumb)}" alt="{esc(a['name'])}" loading="lazy"></div>
        <div class="meta"><div class="name">{esc(a['name'])}</div>
          {dl}
          {src}
        </div>
      </div>""")
            idx += 1
        secs.append(f"""  <section id="{s['id']}">
    <div class="sh"><h2>{esc(s['title'])}</h2><p>{esc(s['blurb'])}</p></div>
    <div class="grid">
{chr(10).join(cards)}
    </div>
  </section>""")
    # Mark-credit cards: only contributors actually crediting a mark (font designers
    # live in the same registry but are shown in the Fonts credits below instead).
    used = {a["credit"] for s in manifest["sections"] for a in s["assets"] if a.get("credit")}
    credit_cards = []
    for c in CREDITS:
        if c["id"] not in used:
            continue
        link_html = "".join(
            f'<a class="contrib-link" data-contrib="{esc(c["id"])}" '
            f'href="{esc(u)}" target="_blank" rel="noopener">{esc(t)}</a>'
            for t, u in c["links"])
        lic = c.get("license")
        lic_html = ""
        if lic:
            lname = esc(lic["name"])
            if lic.get("url"):
                lname = (f'<a href="{esc(lic["url"])}" target="_blank" '
                         f'rel="noopener license">{lname} ↗</a>')
            note = f' — {esc(lic["note"])}' if lic.get("note") else ""
            lic_html = f'<div class="lic"><span>Licence:</span> {lname}{note}</div>'
        credit_cards.append(f"""      <div class="credit" id="credit-{esc(c['id'])}">
        <div class="who">{esc(c['who'])}</div><div class="what">{esc(c['what'])}</div>
        {lic_html}
        {link_html}
      </div>""")
    # font designer credits, grouped by designer — rendered as the same credit tiles as the vectors
    def _host(u):
        return re.sub(r"^www\.", "", re.sub(r"^https?://", "", u).split("/")[0]) if u else ""
    by_designer = {}
    for _fam, (_des, _url) in FONT_CREDIT.items():
        by_designer.setdefault((_des, _url), []).append(_fam)
    fc_cards = []
    for (des, url), fams in sorted(by_designer.items(), key=lambda kv: kv[0][0].lower()):
        links = ([(_host(url), url)] if url else []) + FONT_CREDIT_EXTRA.get(des, [])
        link_html = "".join(
            f'<a class="contrib-link" data-contrib="{esc(des)}" '
            f'href="{esc(u)}" target="_blank" rel="noopener">{esc(lbl)}</a>'
            for lbl, u in links)
        fc_cards.append(f"""      <div class="credit">
        <div class="who">{esc(des)}</div><div class="what">{esc(", ".join(sorted(fams)))}</div>
        {link_html}
      </div>""")
    # Mark credits live on the marks page; font-designer credits on the fonts page.
    mark_credits_html = f"""  <div class="credits" id="credits">
    <h2>Credits &amp; attribution</h2>
    <p>These vectors were traced and compiled by members of the WipEout community; all original
    creators retain credit for their work. WipEout and all related names, logos and marks are
    trademarks of Sony Interactive Entertainment / Studio Liverpool (formerly Psygnosis). This is
    a non-commercial, fan-made archive. Each contributor released their work under different
    terms (shown per card below); full details in <a href="credits.html">CREDITS</a> and
    <a href="licensing.html">LICENSING</a>.</p>
    <div class="credits-grid">
{chr(10).join(credit_cards)}
    </div>
  </div>"""
    font_credits_block = ('  <div class="credits" id="credits">\n'
                          '    <h2>Fonts &amp; typefaces — attribution</h2>\n'
                          '    <p>Specimen sheets are outlined at build time from locally-installed fonts; '
                          'no font files are hosted. Attributions, where certain:</p>\n'
                          '    <div class="credits-grid">\n' + "\n".join(fc_cards) + "\n    </div>\n  </div>")

    # ---- Fonts section (references only; sample sheets outlined at build time) ----
    font_lb = []

    def fcard(family, era, link, link_label, preview_png=None):
        slug = font_slug(family)
        sample = f"fonts/{slug}.svg"
        src = (sample if os.path.exists(os.path.join(ROOT, sample))
               else (FONT_PREVIEW + preview_png.replace(" ", "%20") if preview_png else ""))
        i = len(font_lb)
        designer, dl = FONT_CREDIT.get(family, (None, None))
        cred = ("by " + (f'<a class="contrib-link" data-contrib="{esc(designer)}" '
                         f'href="{esc(dl)}" target="_blank" rel="noopener">{esc(designer)}</a>'
                         if dl else esc(designer))) if designer else ""
        font_lb.append({"name": family, "slug": slug,
                        "meta": era + ((" · by " + designer) if designer else ""),
                        "link": link, "getlabel": link_label, "shot": src})
        linkh = (f'<a class="font-get" data-font="{esc(family)}" href="{esc(link)}" '
                 f'target="_blank" rel="noopener">{esc(link_label)} ↗</a>' if link else "")
        if src:
            shot = f'<div class="font-shot"><img src="{esc(src)}" alt="{esc(family)} specimen" loading="lazy"></div>'
        else:
            shot = (f'<div class="font-shot font-shot-missing"><b>{esc(family)}</b>'
                    f'<small>no specimen yet — add the font to downloads/fonts and rebuild</small></div>')
        return (f'<div class="font-card" data-idx="{i}">{shot}'
                f'<div class="font-meta"><div class="font-info">'
                f'<div class="font-name">{esc(family)}</div>'
                f'<div class="font-use">{esc(era)}</div>'
                f'<div class="font-cred">{cred}</div></div>{linkh}</div></div>')

    def _simple_lic(lic):
        return "commercial" if "commercial" in lic else "free"

    # Grouped by TYPE, not author. Fan-made = NR74W recreations + fan team/game faces.
    fan_cards = ([fcard(fam, era, FONT_BLOB + ttf.replace(" ", "%20"),
                        "get", preview_png=ttf[:-4] + ".png")
                  for era, fonts in FONTS_RECREATED for fam, ttf in fonts]
                 + [fcard(fam, used, url, "get") for fam, used, lic, url in FONTS_DAFONT])
    free_cards = [fcard(fam, used, url, "get")
                  for fam, used, lic, url in FONTS_THIRDPARTY if _simple_lic(lic) == "free"]
    comm_cards = [fcard(fam, used, url, "get")
                  for fam, used, lic, url in FONTS_THIRDPARTY if _simple_lic(lic) == "commercial"]
    refer_items = "".join(
        f'<li><span class="font-name">{esc(f)}</span> — <span class="font-era">{esc(u)} · {esc(n)}</span></li>'
        for f, u, n in FONTS_REFER)
    fonts_html = f"""  <div class="fonts" id="fonts">
    <p style="color:var(--muted);font-size:13px;margin:0 0 6px">Where a font isn't present at build time,
    a placeholder is shown until someone adds it to <code>downloads/fonts</code> and rebuilds.</p>
    <h3>Fan-made WipEout fonts</h3>
    <div class="font-grid">
{chr(10).join(fan_cards)}
    </div>
    <h3>Type foundries — free</h3>
    <div class="font-grid">
{chr(10).join(free_cards)}
    </div>
    <h3>Type foundries — commercial</h3>
    <div class="font-grid">
{chr(10).join(comm_cards)}
    </div>
    <h3>Also used (common system fonts — referenced only)</h3>
    <ul class="font-refer">{refer_items}</ul>
  </div>"""

    lb_json = json.dumps(lb_assets)
    lightbox_html = """<div class="lightbox" id="lightbox" aria-hidden="true">
  <div class="lb-topbar">
    <div class="lb-name" id="lbName"></div>
    <div class="lb-spacer"></div>
    <div class="lb-toggle"><span>Background</span>
      <button data-bg="transparent">Transparent</button>
      <button data-bg="white">White</button>
      <button data-bg="dark">Black</button></div>
    <div class="lb-dl" id="lbDl"></div>
    <button class="lb-x" id="lbClose" aria-label="Close">&times;</button>
  </div>
  <button class="lb-nav lb-prev" id="lbPrev" aria-label="Previous">&#8249;</button>
  <button class="lb-nav lb-next" id="lbNext" aria-label="Next">&#8250;</button>
  <div class="lb-stage bg-transparent" id="lbStage"><img id="lbImg" alt=""></div>
</div>"""
    lb_script = """<script>
(function(){
  var ASSETS = __ASSETS__;
  var lb=document.getElementById('lightbox'), img=document.getElementById('lbImg'),
      stage=document.getElementById('lbStage'), nameEl=document.getElementById('lbName'),
      dl=document.getElementById('lbDl'); var i=0, bg='transparent';
  try{ bg = localStorage.getItem('wo-lb-bg') || 'transparent'; }catch(e){}
  function applyBg(){ stage.className='lb-stage bg-'+bg;
    lb.querySelectorAll('.lb-toggle button').forEach(function(b){
      b.classList.toggle('on', b.getAttribute('data-bg')===bg); }); }
  var BYID={}; ASSETS.forEach(function(a,idx){ BYID[a.id]=idx; });
  function render(n){ i=(n+ASSETS.length)%ASSETS.length; var a=ASSETS[i];
    img.setAttribute('src', a.svg || a.png); img.setAttribute('alt', a.name); nameEl.textContent=a.name;
    dl.innerHTML = a.svg
      ? '<a href="'+a.svg+'" download>SVG</a><a href="'+a.png+'" download>PNG</a>'
      : '<a class="locked" role="button" href="#" data-locked-src="'+(a.source||'')+'" data-locked-who="'+(a.who||'')+'">SVG</a><a href="'+a.png+'" download>PNG</a>'; }
  // deep-linkable: index.html#m/<cat>/<slug> opens that mark; navigation updates the hash
  function goHash(n){ location.hash = 'm/' + ASSETS[(n+ASSETS.length)%ASSETS.length].id; }
  function hideLb(){ lb.classList.remove('open'); lb.setAttribute('aria-hidden','true');
    img.removeAttribute('src'); document.body.style.overflow=''; }
  function closeLb(){ if(/^#m\\//.test(location.hash)){ history.replaceState(null,'',location.pathname+location.search); } hideLb(); }
  function handleHash(){
    var h=(location.hash||'').replace(/^#/,'');
    if(h.indexOf('m/')===0 && BYID[h.slice(2)]!=null){
      var wasOpen=lb.classList.contains('open'); render(BYID[h.slice(2)]);
      if(!wasOpen){ applyBg(); lb.classList.add('open'); lb.setAttribute('aria-hidden','false');
        document.body.style.overflow='hidden';
        var a=ASSETS[i]; try{ gtag('event','view_mark',{mark:a.name, file:(a.svg||a.png||'')}); }catch(e){} }
    } else if(lb.classList.contains('open')){ hideLb(); }
  }
  window.addEventListener('hashchange', handleHash);
  document.querySelectorAll('.thumb').forEach(function(t){
    t.addEventListener('click', function(){ goHash(parseInt(t.getAttribute('data-idx'),10)); }); });
  document.getElementById('lbClose').addEventListener('click', closeLb);
  document.getElementById('lbPrev').addEventListener('click', function(){ goHash(i-1); });
  document.getElementById('lbNext').addEventListener('click', function(){ goHash(i+1); });
  lb.querySelectorAll('.lb-toggle button').forEach(function(b){
    b.addEventListener('click', function(){ bg=b.getAttribute('data-bg');
      try{localStorage.setItem('wo-lb-bg',bg);}catch(e){} applyBg(); }); });
  stage.addEventListener('click', function(e){ if(e.target===stage) closeLb(); });
  document.addEventListener('keydown', function(e){
    if(!lb.classList.contains('open')) return;
    if(e.key==='Escape') closeLb();
    else if(e.key==='ArrowLeft') goHash(i-1);
    else if(e.key==='ArrowRight') goHash(i+1); });
  handleHash();
})();
</script>""".replace("__ASSETS__", lb_json)

    # Restricted-vector overlay: shared by the card grid and the lightbox. Clicking the
    # SVG button of any non-redistributable mark opens this instead of downloading.
    vbox_html = """<div class="vbox" id="vbox" aria-hidden="true" role="dialog" aria-modal="true">
  <div class="vbox-panel">
    <button class="vbox-x" id="vboxClose" aria-label="Close">&times;</button>
    <h3>The artist hosts this vector</h3>
    <p id="vboxMsg"></p>
    <a class="vbox-go contrib-link" id="vboxGo" target="_blank" rel="noopener">Visit the artist's page ↗</a>
  </div>
</div>"""
    vbox_script = """<script>
(function(){
  var vb=document.getElementById('vbox'), msg=document.getElementById('vboxMsg'), go=document.getElementById('vboxGo');
  function openVb(src,who){
    msg.textContent=(who?who+' asks ':'The artist asks ')+'that this vector be obtained from their own page rather than redistributed here \\u2014 the licence does not permit us to share the vector.';
    if(src){ go.href=src; go.setAttribute('data-contrib', who||''); go.style.display=''; } else { go.style.display='none'; }
    vb.classList.add('open'); vb.setAttribute('aria-hidden','false');
  }
  function closeVb(){ vb.classList.remove('open'); vb.setAttribute('aria-hidden','true'); }
  document.addEventListener('click', function(e){
    var t=e.target.closest ? e.target.closest('.locked') : null;
    if(t){ e.preventDefault(); openVb(t.getAttribute('data-locked-src'), t.getAttribute('data-locked-who')); return; }
    if(e.target===vb) closeVb();
  });
  document.getElementById('vboxClose').addEventListener('click', closeVb);
  document.addEventListener('keydown', function(e){ if(e.key==='Escape' && vb.classList.contains('open')) closeVb(); });
})();
</script>"""

    fbox_html = """<div class="fbox" id="fbox" aria-hidden="true">
  <div class="fbox-top">
    <span class="fbox-name" id="fbName"></span>
    <span class="fbox-era" id="fbEra"></span>
    <span class="fbox-spacer"></span>
    <a class="fbox-get font-get" id="fbGet" target="_blank" rel="noopener"></a>
    <button class="fbox-x" id="fbClose" aria-label="Close">&times;</button>
  </div>
  <button class="fbox-nav fbox-prev" id="fbPrev" aria-label="Previous">&#8249;</button>
  <button class="fbox-nav fbox-next" id="fbNext" aria-label="Next">&#8250;</button>
  <div class="fbox-body"><img id="fbImg" alt=""><div class="fbox-note" id="fbNote"></div></div>
</div>"""
    fonts_script = """<script>
(function(){
  var FONTS = __FONTS__;
  var fb=document.getElementById('fbox'), img=document.getElementById('fbImg'),
      nm=document.getElementById('fbName'), era=document.getElementById('fbEra'),
      note=document.getElementById('fbNote'), get=document.getElementById('fbGet');
  var i=0;
  var BYSLUG={}; FONTS.forEach(function(f,idx){ BYSLUG[f.slug]=idx; });
  function render(n){
    i=(n+FONTS.length)%FONTS.length; var f=FONTS[i];
    nm.textContent=f.name; era.textContent=f.meta;
    if(f.shot){ img.src=f.shot; img.style.display=''; note.textContent=''; }
    else { img.removeAttribute('src'); img.style.display='none';
      note.textContent=f.name+' was not installed on the build machine, so no specimen was generated. Install the font and rebuild to create one.'; }
    if(f.link){ get.href=f.link; get.setAttribute('data-font', f.name); get.textContent=(f.getlabel||'get')+' \\u2197'; get.style.display=''; }
    else get.style.display='none';
  }
  // deep-linkable: fonts.html#f/<slug> opens that font; navigation updates the hash
  function goHash(n){ location.hash='f/'+FONTS[(n+FONTS.length)%FONTS.length].slug; }
  function hideFb(){ fb.classList.remove('open'); fb.setAttribute('aria-hidden','true'); document.body.style.overflow=''; }
  function closeFb(){ if(/^#f\\//.test(location.hash)){ history.replaceState(null,'',location.pathname+location.search); } hideFb(); }
  function handleHash(){
    var h=(location.hash||'').replace(/^#/,'');
    if(h.indexOf('f/')===0 && BYSLUG[h.slice(2)]!=null){
      var wasOpen=fb.classList.contains('open'); render(BYSLUG[h.slice(2)]);
      if(!wasOpen){ fb.classList.add('open'); fb.setAttribute('aria-hidden','false'); document.body.style.overflow='hidden';
        var f=FONTS[i]; try{ gtag('event','view_font',{font:f.name}); }catch(e){} }
    } else if(fb.classList.contains('open')){ hideFb(); }
  }
  window.addEventListener('hashchange', handleHash);
  document.querySelectorAll('.font-card').forEach(function(card){
    card.addEventListener('click', function(e){ if(e.target.closest('.font-get')) return;
      goHash(parseInt(card.getAttribute('data-idx'),10)); }); });
  document.getElementById('fbClose').addEventListener('click', closeFb);
  document.getElementById('fbPrev').addEventListener('click', function(){ goHash(i-1); });
  document.getElementById('fbNext').addEventListener('click', function(){ goHash(i+1); });
  fb.addEventListener('click', function(e){ if(e.target===fb) closeFb(); });
  document.addEventListener('keydown', function(e){
    if(!fb.classList.contains('open')) return;
    if(e.key==='Escape') closeFb();
    else if(e.key==='ArrowLeft') goHash(i-1);
    else if(e.key==='ArrowRight') goHash(i+1); });
  handleHash();
})();
</script>""".replace("__FONTS__", json.dumps(font_lb))

    # ---- Assemble the pages from the shared shell ----
    marks_page = next(p for p in NAV_PAGES if p["kind"] == "marks")
    fonts_page = next((p for p in NAV_PAGES if p["kind"] == "fonts"), None)

    marks_header = f"""  <div class="hero-top">
    <h1>{esc(marks_page['title'])}</h1>
    <div class="pdfcta">
      <a href="tearsheet.pdf" class="pdflink">⬇&nbsp;Tear sheet PDF</a>
      <span class="pdfcta-note">Every logo is copy-paste-ready in Illustrator, Affinity or Acrobat.</span>
    </div>
  </div>
  <p class="lead">A community-maintained, normalised set of WipEout-universe logos, emblems and
  marks &mdash; teams, sponsors, tracks, speed classes, game modes and series titles &mdash;
  every asset available as SVG and PNG.</p>
  <span class="stat">{manifest['total']} assets</span>
  <span class="stat">{len(manifest['sections'])} categories</span>
  <span class="stat">Updated {manifest['generated']}</span>
  <div class="toc">{toc}<a href="#credits">Credits</a></div>"""
    marks_body = f"{chr(10).join(secs)}\n{mark_credits_html}"
    marks_scripts = f"{lightbox_html}\n{vbox_html}\n{lb_script}\n{vbox_script}"
    _write(marks_page["file"],
           _document(marks_page["slug"], marks_page["title"], marks_header, marks_body, marks_scripts))

    if fonts_page:
        fonts_header = """  <h1>Fonts</h1>
  <p class="lead">The typefaces used across the WipEout series. <strong>No font files are hosted here</strong> &mdash;
  this section only references them. Specimen sheets are rendered from the fonts installed on the build machine and
  outlined to vector paths, so they display for everyone without shipping a single font. Click a specimen to view it
  full-screen.</p>"""
        fonts_body = f"{fonts_html}\n{font_credits_block}"
        fonts_scripts = f"{fbox_html}\n{fonts_script}"
        _write(fonts_page["file"],
               _document(fonts_page["slug"], fonts_page["title"], fonts_header, fonts_body, fonts_scripts))

    # Remaining pages: the reference gallery, else a prose page (about / links).
    for p in NAV_PAGES:
        if p["kind"] in ("marks", "fonts"):
            continue
        if p["kind"] == "reference":
            build_reference_page(p, ref_manifest or build_reference_manifest())
        elif p["kind"] == "teams":
            build_teams_page(p)
        elif p["kind"] == "leagues":
            build_leagues_page(p)
        else:
            build_prose_page(p)


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
_BUNDLED_FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
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
    for p in pages:
        page_svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
                    f'xmlns:xlink="http://www.w3.org/1999/xlink" '
                    f'width="{PAGE_W}" height="{PAGE_H}" viewBox="0 0 {PAGE_W} {PAGE_H}">'
                    f'<rect width="{PAGE_W}" height="{PAGE_H}" fill="#ffffff"/>'
                    f'{"".join(p["back"])}{"".join(p["front"])}</svg>')
        sub = fitz.open("pdf", cairosvg.svg2pdf(bytestring=page_svg.encode()))
        master.insert_pdf(sub)
        sub.close()
    n = master.page_count
    pdf_bytes = master.tobytes(garbage=4, deflate=True)
    master.close()
    with open(os.path.join(ROOT, "tearsheet.pdf"), "wb") as f:
        f.write(pdf_bytes)
    return n


if __name__ == "__main__":
    force = "--force" in sys.argv or "-f" in sys.argv
    print("Rendering PNG + PDF derivatives…" + ("  (--force: rebuilding all)" if force else ""))
    try:
        n, skipped = render_derivatives(force=force)
        print(f"  {n} rendered, {skipped} up-to-date")
    except Exception as e:
        print(f"  !! skipped (cairosvg unavailable): {e}")
        print("     Keeping existing PNG/PDF derivatives. Font specimens + HTML still build.")
    print("Writing manifest.json…")
    m = build_manifest()
    print(f"  {m['total']} assets across {len(m['sections'])} sections")
    print("Generating font sample sheets…")
    miss, hints = generate_font_samples()
    if miss:
        print(f"  fonts not found on this machine (no specimen generated): {', '.join(miss)}")
        for fam in miss:
            if fam in hints:
                print(f"      · '{fam}' — closest installed: {', '.join(hints[fam])}")
    else:
        print("  all fonts found")
    print("Writing fonts/manifest.json…")
    fm = build_font_manifest()
    print(f"  {fm['total']} fonts across {len(fm['sections'])} groups")
    print("Rendering reference thumbnails…")
    try:
        rn, rs = render_reference_thumbs(force=force)
        print(f"  {rn} made, {rs} up-to-date")
    except Exception as e:
        print(f"  !! skipped (Pillow unavailable): {e}")
        print("     Keeping existing thumbnails; grid falls back to full images where absent.")
    print("Writing reference/manifest.json…")
    rm = build_reference_manifest()
    print(f"  {rm['total']} screenshots across {len(rm['games'])} game(s)")
    print("Writing shared styles.css + analytics.js…")
    write_shared_assets()
    print("Writing pages…")
    build_pages(m, rm)
    print(f"  {len(NAV_PAGES)} pages: " + ", ".join(p["file"] for p in NAV_PAGES))
    print("Rendering doc pages from Markdown…")
    docs = build_doc_pages()
    print(f"  {len(docs)} doc pages: " + ", ".join(docs))
    print("Writing tearsheet.pdf…")
    try:
        n = build_pdf_tearsheet(m)
        print(f"  {n} pages")
    except Exception as e:
        print(f"  !! tearsheet PDF failed: {e}")
    print("Done.")
