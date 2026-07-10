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
h1{margin:0 0 8px;font-size:30px;letter-spacing:-.02em}
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
.prose h1{font-size:30px;letter-spacing:-.02em;margin:0 0 12px}
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
ANALYTICS = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-KX3WW4Q3NG"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-KX3WW4Q3NG');
</script>
<script>
  // Custom action tracking — one delegated listener for the whole site.
  (function(){
    function ev(name, params){ try{ gtag('event', name, params||{}); }catch(e){} }
    function slug(h){ return (h.split('#')[0].split('?')[0].split('/').pop()||'').replace(/\\.[^.]+$/,''); }
    document.addEventListener('click', function(e){
      var a = e.target.closest && e.target.closest('a'); if(!a) return;
      if(a.hasAttribute('download')){
        var href = a.getAttribute('href') || '';
        if(/\\.svg(?:[?#]|$)/i.test(href)) ev('download_svg', {mark: slug(href), file: href});
        else if(/\\.png(?:[?#]|$)/i.test(href)) ev('download_png', {mark: slug(href), file: href});
        return;
      }
      if(a.classList.contains('pdflink')){
        ev('download_pdf', {file: a.getAttribute('href') || ''});
        return;
      }
      if(a.classList.contains('font-get')){
        ev('get_font', {font: a.getAttribute('data-font') || '', link_url: a.href, link_domain: a.hostname});
        return;
      }
      if(a.classList.contains('contrib-link')){
        ev('contributor_link', {contributor: a.getAttribute('data-contrib') || '', link_url: a.href, link_domain: a.hostname});
        return;
      }
    }, true);
  })();
</script>
"""


FOOTER = """<footer>
  <p>WipEout and all related logos, names and marks are trademarks of Sony Interactive Entertainment /
  Studio Liverpool (formerly Psygnosis). This is a non-commercial, fan-made archive for the community.
  Assets compiled from the work of the original creators &mdash; see
  <a href="credits.html">CREDITS</a>. Contributions welcome via
  <a href="contributing.html">pull request</a>.</p>
</footer>"""


def _document(slug, title, header_inner, body, scripts=""):
    """Wrap a page's body in the shared shell: <head>, sticky nav, optional hero
    <header>, content <div class="wrap">, footer, then any page scripts."""
    hero = f"<header>\n{header_inner}\n</header>\n" if header_inner else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · awesome-wipeout</title>
{ANALYTICS}<style>{CSS}</style></head>
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
            lb_entry = {"name": a["name"], "svg": a["svg"], "png": a["png"]}
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
        font_lb.append({"name": family,
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
  function show(n){ i=(n+ASSETS.length)%ASSETS.length; var a=ASSETS[i];
    img.setAttribute('src', a.svg || a.png); img.setAttribute('alt', a.name); nameEl.textContent=a.name;
    dl.innerHTML = a.svg
      ? '<a href="'+a.svg+'" download>SVG</a><a href="'+a.png+'" download>PNG</a>'
      : '<a class="locked" role="button" href="#" data-locked-src="'+(a.source||'')+'" data-locked-who="'+(a.who||'')+'">SVG</a><a href="'+a.png+'" download>PNG</a>'; }
  function openLb(n){ show(n); applyBg(); lb.classList.add('open');
    lb.setAttribute('aria-hidden','false'); document.body.style.overflow='hidden';
    var a=ASSETS[i]; try{ gtag('event','view_mark',{mark:a.name, file:(a.svg||a.png||'')}); }catch(e){} }
  function closeLb(){ lb.classList.remove('open'); lb.setAttribute('aria-hidden','true');
    img.removeAttribute('src'); document.body.style.overflow=''; }
  document.querySelectorAll('.thumb').forEach(function(t){
    t.addEventListener('click', function(){ openLb(parseInt(t.getAttribute('data-idx'),10)); }); });
  document.getElementById('lbClose').addEventListener('click', closeLb);
  document.getElementById('lbPrev').addEventListener('click', function(){ show(i-1); });
  document.getElementById('lbNext').addEventListener('click', function(){ show(i+1); });
  lb.querySelectorAll('.lb-toggle button').forEach(function(b){
    b.addEventListener('click', function(){ bg=b.getAttribute('data-bg');
      try{localStorage.setItem('wo-lb-bg',bg);}catch(e){} applyBg(); }); });
  stage.addEventListener('click', function(e){ if(e.target===stage) closeLb(); });
  document.addEventListener('keydown', function(e){
    if(!lb.classList.contains('open')) return;
    if(e.key==='Escape') closeLb();
    else if(e.key==='ArrowLeft') show(i-1);
    else if(e.key==='ArrowRight') show(i+1); });
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
  function show(n){
    i=(n+FONTS.length)%FONTS.length; var f=FONTS[i];
    nm.textContent=f.name; era.textContent=f.meta;
    if(f.shot){ img.src=f.shot; img.style.display=''; note.textContent=''; }
    else { img.removeAttribute('src'); img.style.display='none';
      note.textContent=f.name+' was not installed on the build machine, so no specimen was generated. Install the font and rebuild to create one.'; }
    if(f.link){ get.href=f.link; get.setAttribute('data-font', f.name); get.textContent=(f.getlabel||'get')+' \\u2197'; get.style.display=''; }
    else get.style.display='none';
  }
  function openFb(n){ show(n); fb.classList.add('open'); fb.setAttribute('aria-hidden','false'); document.body.style.overflow='hidden';
    var f=FONTS[i]; try{ gtag('event','view_font',{font:f.name}); }catch(e){} }
  function closeFb(){ fb.classList.remove('open'); fb.setAttribute('aria-hidden','true'); document.body.style.overflow=''; }
  document.querySelectorAll('.font-card').forEach(function(card){
    card.addEventListener('click', function(e){ if(e.target.closest('.font-get')) return;
      openFb(parseInt(card.getAttribute('data-idx'),10)); }); });
  document.getElementById('fbClose').addEventListener('click', closeFb);
  document.getElementById('fbPrev').addEventListener('click', function(){ show(i-1); });
  document.getElementById('fbNext').addEventListener('click', function(){ show(i+1); });
  fb.addEventListener('click', function(e){ if(e.target===fb) closeFb(); });
  document.addEventListener('keydown', function(e){
    if(!fb.classList.contains('open')) return;
    if(e.key==='Escape') closeFb();
    else if(e.key==='ArrowLeft') show(i-1);
    else if(e.key==='ArrowRight') show(i+1); });
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
