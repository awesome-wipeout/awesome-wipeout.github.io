# CLAUDE.md — guidance for AI agents working on this repo

This repository is **awesome-wipeout** (the WipEout Vector Asset Library): a normalised, community-maintained
collection of WipEout-universe logos, emblems and marks (teams, sponsors, tracks, speed
classes, game modes, weapons, series titles, pilots and custom marks). It is published as a
static site via GitHub Pages and is meant to be contributed to by the community.

**Scope of this file: the public repository only.** Everything documented here assumes only
what is inside this repo — a contributor with a fresh clone must be able to build the site with
no external files. This repo is self-contained and world-readable; treat anything committed
here as public. Do not add guidance that depends on files outside the repo. (Withheld vectors
we can't redistribute appear here purely as reference-only PNG tiles — see *Reference-only
assets* below; that public behaviour is the full extent of what this repo knows about them.)

## The one rule that matters most

**SVG is the single source of truth. Everything else is generated.**

For every logo the canonical file is `marks/<cat>/<slug>.svg`. The matching `.png`, every
generated HTML page (`index.html`, `fonts.html`, `teams.html`, `about.html`, `links.html`,
`reference.html`, …), the shared `styles.css` + `analytics.js`, and `tearsheet.pdf`, are all
**derived** and overwritten on every build. Edit the SVG (or the `data/*.toml`), never the
PNG/HTML/CSS/JS. (The marks/fonts/reference **indexes** are also derived, but they're built in
memory and handed straight to the page generators — no `manifest.json` is written to disk.)

**Shared CSS/JS, not inlined per page.** `styles.css` (the whole site stylesheet, incl. the
Teams-page rules) and `analytics.js` (GA4 + the one delegated action listener) are written
once by `write_shared_assets()` and linked by every page in `_document` — pages no longer
carry a `<style>` block or an inline analytics script. Edit the `CSS`/`TEAMS_CSS`/`_ANALYTICS_JS`
constants in `tools/build.py`, never the generated `styles.css`/`analytics.js`.

**The site is multi-page.** `data/pages.toml` is the page registry (nav order + which
generator renders each page via `kind`: `marks` | `fonts` | `prose`). A thin sticky header
shared by every page (built by `_nav_html`/`_document` in `tools/build.py`) links them.
`index.html` = the marks page (site entry point); `fonts.html` = the fonts page; `prose`
pages (about / links / in-game reference) author all their copy in `data/pages.toml`
(`intro` / `paragraphs` / `links`). Add a page = add a `[[page]]` block (+ a generator only
if you need a new `kind`) — no bespoke HTML surgery. The site brand is **awesome-wipeout**.

**No per-asset PDFs.** The site offers only SVG (the vector download) and PNG (raster) per
asset — a per-logo PDF was just the SVG re-wrapped (same RGB paths, no CMYK/fonts) and cairo
stamped a live date into each one, churning git. The designer/print case is served by the
aggregate `tearsheet.pdf`. Don't reintroduce per-asset `.pdf` output.

**What happens when `downloads/` isn't available?** Nothing breaks. `downloads/` holds
only original third-party source art and is gitignored/ephemeral. A normal build needs
only the committed `marks/**/*.svg` (font specimens additionally use whatever fonts are
installed — also optional). You only need `downloads/` to re-derive an asset from a
brand-new source pack. The PNG step and the font-specimen step are each wrapped so a
missing dependency is skipped, not fatal.

**Recovering a damaged/lost SVG:** the SVG is the sole source of truth, and it's in git —
recover a bad edit with `git checkout -- marks/<cat>/<slug>.svg` (or from any earlier commit).
(Historically the committed per-asset PDF was a viewBox-cropped vector fallback and 17
`weapons`/`teams/hd`/`sponsors`/`custom` marks were regenerated from it via
`fitz.open(pdf)[0].get_svg_image()` after a bad clean — those PDFs are gone now, so git
history is the backup.)

After adding, editing or removing any SVG under `marks/`, run:

```bash
pip install cairosvg pymupdf fonttools lxml pillow   # first time only

# THE rebuild command on this machine (arm64 macOS): libcairo is at /opt/homebrew/lib
# but not on the default loader path, so it must be prefixed. On Linux, drop the prefix.
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python3 tools/build.py
```

Run `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python3 tools/build.py` verbatim — with
the prefix, the **entire** build succeeds (PNG, HTML, reference thumbnails and
`tearsheet.pdf`). Without it, cairosvg can't load libcairo and PNG + tearsheet are skipped.
(The `DYLD_*` value is read at process start, so it must be a command prefix — exporting it
mid-shell won't help an already-running process.)

**There is no CI — the full build must run locally**, and it does: PNG, HTML,
reference thumbnails **and `tearsheet.pdf`** are all produced by `python3 tools/build.py` on
macOS/Windows/Linux. The tear-sheet font is **bundled in the repo** (`tools/fonts/DejaVuSans*.ttf`,
Bitstream Vera licence — see `tools/fonts/LICENSE.txt`) and outlined to curves, so the PDF is
self-contained and deterministic with no system-font dependency.

**Local build environment (macOS / Apple Silicon):** the one remaining native dependency is
`cairosvg`'s `libcairo` (used for the PNGs and for rasterising each tear-sheet page), which must
match your Python's architecture. If Python is arm64 but the only Homebrew is the Intel one under
Rosetta (`brew --prefix` → `/usr/local`), its `libcairo` is x86_64 and every cairosvg call dies
with *"incompatible architecture"*. Install the arm64 Homebrew (at `/opt/homebrew`) and
`brew install cairo`; if `/opt/homebrew/lib` isn't on the loader path for your (non-login) shell,
**prefix every build command** with it:
`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python3 tools/build.py`. Without cairo the build
still runs but **skips PNG + tearsheet** (tolerant by design); with it, everything builds.

`tools/build.py` regenerates, for every `marks/**/*.svg`:
- a transparent PNG (1024 px) next to it (rebuilt only when the SVG is newer; `--force` rebuilds all),
- the in-memory asset + font indexes (`build_manifest` / `build_font_manifest` — the marks and
  fonts data the pages are rendered from; see Fonts below), passed to the generators, not written to disk,
- `index.html` (the HTML tear sheet), and
- `tearsheet.pdf` (a multi-page, fully-vector tear sheet a designer can open and
  copy/paste logos from). It is composed as one flat SVG per page (cairosvg → PDF,
  stitched with PyMuPDF) so it has **no fonts** (all labels are outlined to curves
  via fonttools — no missing-font prompt on Mac/Windows), **no Form XObjects** and
  **no page-wrapping group**. Card backgrounds + labels are drawn first (at the back);
  each logo is inlined last (on top) inside a nested `<svg>` viewport sized exactly to
  the fitted artwork — that tight viewport clips off any neighbouring geometry the
  source SVG may still carry, and reads back as one directly-selectable group.

**Never hand-edit any generated `*.html` or `tearsheet.pdf`** — they are
overwritten on every build. **There is no CI**: run `python3 tools/build.py` yourself and
commit the regenerated artifacts alongside your SVG/data change. (A
`.github/workflows/build.yml` exists for if/when the repo is pushed, but nothing runs it today.)

## Repository layout

```
data/contributors.toml        AUTHORED — creators, licences, links (shared)
data/marks.toml               AUTHORED — mark sections + one entry per file (1:1)
data/fonts.toml               AUTHORED — font references
data/pages.toml               AUTHORED — site page registry (nav order + prose-page copy)
data/reference.toml           AUTHORED — in-game reference: game/team names, emblems, credit
data/teams.toml               AUTHORED — Teams page: series×teams brand matrix + colours
marks/<category>/<slug>.svg   + matching .png   (.png generated; PNG-only slug = reference-only)
fonts/<slug>.svg              generated font specimen sheets (committed)
reference/<game>/<team>/<slug>.jpg   + generated <slug>.thumb.jpg   (SCREENSHOTS — raster)
index.html                    generated marks page (GitHub Pages entry point)
fonts.html                    generated fonts page
reference.html                generated in-game reference gallery
teams.html                    generated Teams page (brand-guidelines matrix, from data/teams.toml)
about.html links.html         generated prose pages (from data/pages.toml)
styles.css analytics.js       generated SHARED assets, linked by every page (not inlined)
tearsheet.pdf                 generated multi-page vector tear sheet (marks only)
tools/                        build + extraction + cleanup scripts
tools/fonts/                  BUNDLED DejaVu Sans (tear-sheet labels; Bitstream Vera licence)
downloads/                    ORIGINAL source packs — gitignored, may be ABSENT
downloads/fonts/              optional font drop-in for specimens — gitignored
```

**In-game reference is a separate, RASTER collection** (`reference/`, [issue 04]). Unlike
marks, these are photographic screenshots (JPG), so the "vector only" rule does NOT apply to
them. They're grouped game → team, each team headed by an emblem reused from the marks
collection (mapped in `data/reference.toml`), and are reference-only (shown, never offered as
downloads; excluded from the tear sheet). Images are discovered by scanning — drop JPGs in
`reference/<game>/<team>/` and rebuild, no per-image entry. `build.py` generates a downscaled
`<slug>.thumb.jpg` next to each (Pillow; tolerant if absent) for the gallery grid, while the
lightbox loads the full image. `pip install pillow` if thumbnails are being skipped.

Categories (each folder is one tear-sheet section, ordered in `data/sections.toml`):
`titles`, `teams/{wo1,2097,wip3out,pure}`, `pilots`, `classes`, `game-modes`, `weapons`,
`sponsors`, `tracks`, `misc`.

## `downloads/` is not committed

`downloads/` holds the original third-party/source art (Adobe Illustrator, CorelDRAW,
Photoshop custom-shape packs, the contributors' layered AIs). **It is gitignored and will
usually not be present.** The committed `marks/*.svg` files are already extracted and are what
you work with. You only need `downloads/` (and the extraction tools below) if you are
re-deriving an asset or ingesting a brand-new source pack.

## Conventions

- **Vector only — no bitmaps.** Never embed raster images inside an SVG. Reject/redo any such contribution.
- Filenames are **lowercase-kebab-case**; the `viewBox` must be cropped tightly to the artwork.
- Team logos live under a **per-era** subfolder (`teams/wo1|2097|wip3out|pure`).
- Single-colour marks (sponsors/tracks/classes/game-modes from Photoshop shapes) are solid black `#000000`.
- Display names come from the asset's `name` in `data/marks.toml` (omit it → title-cased slug).

## Authored metadata lives in `data/*.toml` (build = code, data = data)

`tools/build.py` holds **no authored metadata** — it reads these TOML files (via stdlib
`tomllib`) and generates everything else. The asset/font indexes it derives stay in memory
(never written, nothing to hand-edit). A **collection** = a folder + a matching
`data/<name>.toml` (this repeats: `marks/` +
`data/marks.toml`, `fonts/` + `data/fonts.toml`, and any future set). Editing metadata means
editing `data/`, not Python:
- `data/contributors.toml` — every creator (shared by all collections): `id`, `name`, `blurb`,
  **`license`** {name,url?,note?}, `links`.
- `data/marks.toml` — the mark collection: `[[section]]` display groupings (folder/title/blurb,
  in order) **plus one `[[asset]]` entry per file (1:1)**. Each entry names its file explicitly:
  `file = "folder/slug.ext"` (folder = section, `.svg` = hosted / `.png` = reference-only), with
  `credit` (contributor id; `""` = uncredited), optional `name`, and `source` for reference-only.
- `data/fonts.toml` — font references (see Fonts below).

Adding marks: drop the file(s) in `marks/<section>/`, run `python3 tools/scaffold.py` to print
(or `--write` to append) a stub entry per new file, fill in each `credit`, then build.

## Credits & licences (per-tile + credits section)

Every asset shows a "source:" link that jumps to a credit card, and each credit card shows the
contributor's **licence** (see `LICENSING.md`). Credit is **per-asset and explicit** — the
`credit` on the mark's `[[asset]]` entry (no folder defaults, no fallback). To add a
contributor: add a `[[contributor]]` block to `data/contributors.toml`, then set `credit` on each
of their asset entries (scaffold stubs them with an empty `credit` to fill).

**1:1 integrity:** `build_manifest` warns (but keeps building) on any drift — a file in `marks/`
with no entry (`metadata missing: …`) or an entry with no file (`no file for entry: …`). A
lingering generated PNG after you delete its SVG will surface as a phantom reference-only mark
here — delete the orphan `.png` too.

## Reference-only assets (indicative PNG, artist-link overlay)

Some art can't be redistributed as a vector (e.g. CC BY-NC-ND — the artist permits showing the
mark but not sharing the vector). Such an asset is committed as a **PNG with no sibling SVG** —
that absence is the signal: `build_manifest` emits `svg:null`, `hosting:"reference"` and a source
URL (the entry's `source`, else the contributor's first link). Its `data/marks.toml` entry names
the `.png` (`file = "<cat>/<slug>.png"`).

**UX:** the tile shows **both** an `SVG` and a `PNG` button. `PNG` downloads; the `SVG` button
does **not** download — it opens a small overlay ("the artist hosts this vector → Visit the
artist's page ↗", the `source` link). This is shared by the card grid and the lightbox via the
`.locked` / `data-locked-*` hook + the `#vbox` overlay in `build.py`. Reference-only assets are
excluded from `tearsheet.pdf`.

**The PNG is a committed artifact, not rebuilt by this build.** With no source SVG in `marks/`,
`render_derivatives` never regenerates it — it persists as committed (a smaller, indicative
raster). Don't expect `build.py` to produce or resize it; treat the committed PNG as canonical.
Converting a hosted contributor to reference-only = remove their SVGs from `marks/` (keep the
PNGs) and point their `[[asset]]` entries at the `.png`.

## Fonts (referenced, not hosted)

The tear sheet has a **Fonts** section backed by an in-memory font index (`build_font_manifest`)
— the font analogue of the marks index, same shape (`name` / `generated` / `total`
/ `sections[]`, each item carrying `slug` + `name` + `credit`). **Where is font
metadata stored?** Authored in `data/fonts.toml` — grouped arrays `[[recreated]]` (NR74W
OpenType recreations, by era), `[[thirdparty]]`, `[[dafont]]`, `[[refer]]` (referenced-only
system faces, no specimen), plus `[lore]` (specimen phrase per family) and a `[source]` table
of repo/blob/preview URLs. Each font carries **`credit = "<contributor-id>"`** referencing the
**shared** `data/contributors.toml` (same registry as marks — font designers are contributors
there; a designer's `links[0]` is their primary link, further links show as extra credit links).
Fonts keep a per-font `license`. `build.py` reconstructs the internal tables from it; the
font index is **generated** in memory each build (nothing to hand-edit).

Key rules:
- **No font files are ever hosted.** We only *reference* fonts (a "get ↗" link per tile).
  Specimen sheets (`fonts/<slug>.svg`) are outlined to vector paths at build time from
  whatever font is installed, so they render for everyone without shipping a font.
- Fonts are grouped **by type**, not author: Fan-made (NR74W recreations + fan team/game
  faces), Type foundries — free, Type foundries — commercial, and referenced-only system
  fonts. Tiles are uniform: name / usage / `by <designer>` stacked left, "get" pinned right.
- The specimen step is **additive & tolerant**: a committed `fonts/*.svg` survives builds
  where its font is absent (CI, or `downloads/fonts` wiped); a font is only reported
  "missing" when there's no committed specimen; one bad font never breaks the build.
- Drop-in fonts: put `.ttf/.otf/.ttc` in `downloads/fonts/` (gitignored) and rebuild to
  generate a specimen without a system install. A font's `specimen` is `null`
  when no sample is committed yet (e.g. a placeholder like *Wipeout Typeface*).

## Analytics (Google Analytics 4)

The site loads **gtag.js** (GA4 measurement ID `G-KX3WW4Q3NG`) plus a small custom-event
tracker. Both live in the `_ANALYTICS_JS` constant in `tools/build.py`, written once to the
shared **`analytics.js`** (by `write_shared_assets()`) and referenced by **every page's
`<head>`** via `<script defer src="analytics.js">` in `_document()` — analytics.js injects the
async gtag library itself, so one script tag is all a page needs. **Never paste GA snippets
into the `*.html` or `analytics.js`; edit `_ANALYTICS_JS`.** (The measurement ID is a public
web-stream ID — safe to commit; it identifies the stream, it is not a secret.)

Custom events are fired by **one delegated, capture-phase `click` listener on `document`**.
A single listener (rather than per-element `onclick`) is deliberate: it also catches clicks
inside the lightbox / restricted-vector (`vbox`) / fonts overlays, whose markup is built in
JS at runtime and so can't carry server-rendered handlers. Events ⇄ triggers:

| Event | Fires when | Key params |
|-------|-----------|-----------|
| `download_svg` | an asset's **SVG** button is clicked (any `a[download]` whose href ends `.svg`) | `mark` (slug), `file` |
| `download_png` | an asset's **PNG** button is clicked (any `a[download]` whose href ends `.png`) | `mark` (slug), `file` |
| `download_pdf` | the aggregate **tear-sheet PDF** link is clicked (`.pdflink`) | `file` |
| `get_font` | a font's **"get ↗"** link is clicked (`.font-get`, on a card or in the fonts lightbox) | `font`, `link_url`, `link_domain` |
| `contributor_link` | an **outbound** link to a contributor's own site is clicked (`.contrib-link`) | `contributor`, `link_url`, `link_domain` |
| `view_mark` | the **marks lightbox** is opened on a mark (fired in `openLb`) | `mark`, `file` |
| `view_font` | the **fonts lightbox** is opened on a font (fired in `openFb`) | `font` |

`view_mark` / `view_font` are the exception to the one-listener rule: a lightbox opens from a
`<div class="thumb">` / `.font-card` click (not an anchor), so they're fired directly from the
marks/fonts lightbox scripts (`openLb` / `openFb`) rather than the delegated listener. They
fire on **open only** — arrow-key / prev-next navigation within an open lightbox is not
re-counted.

How the triggers are wired, so new UI keeps tracking for free:
- **Downloads** need no marker — the listener sniffs the `download` attribute + file
  extension, which every SVG/PNG button already has (grid *and* lightbox). The internal
  "source:" credit-jump is a same-page `#anchor` (no `download`), so it correctly fires
  nothing. The tear-sheet PDF link has no `download` attr, so it's matched by its own
  `.pdflink` class instead (→ `download_pdf`).
- **`.font-get`** marks every "get" link (font cards + the `#fbGet` lightbox link); its
  `data-font` carries the family name (set server-side on cards, in JS on the lightbox link).
- **`.contrib-link`** marks every offsite contributor link — credit cards, the font
  "by &lt;designer&gt;" byline, and the restricted-vector overlay's "Visit the artist's
  page"; its `data-contrib` carries the contributor id/name.

Adding a tracked action = give the element the right class/`data-*` (or, for downloads, just
the `download` attr) — no new listener. The event **params** above are sent as-is; to slice
GA4 reports by `mark` / `font` / `contributor`, register matching **custom dimensions** in the
GA4 admin (Admin → Custom definitions). `gtag()` is defined synchronously ahead of the async
library, so early clicks queue on `dataLayer` and are never lost.

## Cleaning SVGs — `tools/clean_svgs.py`

Some extracted SVGs carried geometry **outside** their cropped viewBox (neighbouring
logos / stray sub-paths, only hidden because the viewBox clips them). `clean_svgs.py`
removes that safely: it renders the SVG at its native viewBox, removes each drawable
element, re-renders, and keeps the removal only if the visible artwork is unchanged;
then it vacuums empty `<g>`/`<defs>` and editor cruft (inkscape/sodipodi). Run:

```bash
python3 tools/clean_svgs.py marks/weapons/shield.svg   # specific files
python3 tools/clean_svgs.py --all                      # every marks/**/*.svg
python3 tools/clean_svgs.py --vacuum-only <files>       # cruft strip, skip the cull
```

It writes SVGs only; run `tools/build.py` afterwards to refresh the PNG + regenerate the site. If a
clean goes wrong, recover the previous SVG from git (`git checkout -- <file>`) rather than
re-running it.

## Extraction tools (only for re-deriving or new source packs)

- `tools/ai_to_svg.py` — legacy CorelDRAW-exported `.ai` whose PDF page is empty and whose
  artwork lives in the native Illustrator private-data (AI5 PostScript) stream. **Handles
  Illustrator compound paths (`*u … *U`) by emitting one even-odd `<path>`** so letter counters
  and holes punch through correctly.
- `tools/csh_to_svg.py` — decodes Adobe Photoshop Custom Shape (`.csh`, magic `cush`) binaries.
- `tools/title_ai_to_svg.py` — modern Adobe title `.ai`. Uses `get_svg_image()` (preserves live
  text), removes any full-span opaque background panel, and crops to rendered pixels.
- The contributor "custom glyphs" file (djdrey909, `tools/layered_ai_to_svg.py`) is a single
  layered AI: each glyph is a named layer stored as an `/OC /MCn BDC … EMC` marked-content block.
  Split by isolating those blocks to get names/positions, but crop the **unmodified** page for
  correct colour (see gotchas). **Sub-layer names** (e.g. the individual weapon names) are NOT in
  the PDF OCG tree — they live in the native Illustrator data, `%AI24_ZStandard_Data` spread
  across `AIPrivateData1..N`. Concatenate those streams (keep the `(` — it is zstd magic `0x28`),
  Zstandard-decompress, and read `(name) Ln` records; map each name to its glyph via the first
  `x y m` (moveto) coordinate after the name.

## Hard-won gotchas (read before touching extraction)

- **Comparing two renders? Never diff RGBA and call `Image.getbbox()`.** The difference
  image's *alpha* channel is ~0 everywhere, and `getbbox()` treats alpha-0 pixels as empty
  — so it reports "identical" even when the RGB colours differ wildly. This silently let a
  cleaner delete opaque detail that sat on an opaque silhouette (multi-colour marks like
  `weapons/shield`, `teams/hd/*`). **Flatten each render onto a solid background (do it for
  BOTH black and white) and diff the resulting RGB.** See `same()` in `tools/clean_svgs.py`.
- **`get_svg_image()` bakes a clipPath from the crop box** that can trim artwork. Prefer cropping
  by rewriting the **root `<svg>` viewBox** (measure true bounds by rendering to alpha), rather
  than a tight `set_cropbox` before export.
- **Strip leftover `<clipPath>`/`clip-path` before committing an extracted SVG.** `get_svg_image()`
  leaves clip defs + `clip-path` attributes in the file, and **`clean_svgs.py` does NOT remove
  them** (it only culls out-of-viewBox geometry). Opening such an SVG in Illustrator warns
  *"Clipping will be lost on roundtrip to Tiny"*; the repo's other marks are clip-free. After a
  clean the crop-box clip is usually a no-op, so remove every `<clipPath>` and `clip-path` and
  confirm the render is **pixel-identical on both black and white** (the `same()` test) before
  keeping it.
- **MuPDF OCG toggling (`set_layer`) is not honoured when rendering this contributor file.** To
  isolate a layer, edit the page content stream to keep a single marked-content block.
- **Content-stream isolation loses fill colours** for some layers. Use layer isolation only to
  get each layer's name + bounding box, then crop the untouched full-colour page to that bbox.
- **The djdrey909 "custom glyphs" AI stacks a white/reversed twin of each mark on top of the
  coloured one, at the same position** (a for-dark-backgrounds variant). It is invisible when a
  crop is flattened on white, so an untouched-page crop looks clean — but the white geometry is
  really there and shows on any coloured background. A layer can also hold the same mark
  duplicated at several sizes, and some sit partly off the 2000×2000 page. So: verify every
  extracted mark on a **mid-grey/dark** background, not just white, and pick an instance with no
  overlapping twin. When every copy of a mark is contaminated (e.g. the bare F9000 emblem),
  derive it from a clean sibling instead — the emblem was recovered from the clean `f9000`
  wordmark lockup by keeping only the two gold fills (`#cdb62c`, `#7c6e1d`) and dropping the rest,
  then re-tightening. The F9000 + 2048 league marks came from this file's `f9000` / `2048 league`
  layers.
- **Compound paths:** if counters/holes render filled, you are painting sub-paths separately —
  group them into one even-odd path.
- Keep a `viewBox` on every SVG so it scales cleanly.
- **The tear sheet references each thumbnail via `<img src>`, NOT inline `<svg>`.** SVGs produced
  by `get_svg_image()` reuse internal ids (`clip_1`, `clip_2`, `<use>` refs …); inlining many of
  them into one page causes id collisions that blank out or mis-clip logos. `<img>` isolates each
  SVG as its own document. The lightbox also uses `<img>` with `object-fit: contain`.
- File deletes may be blocked in the working mount while `mv` still works — retire unwanted files
  by moving them into the gitignored `downloads/` tree rather than `rm`.

## Verifying changes

Rebuild, then eyeball a contact sheet (render each PNG onto a checker background) and confirm
per-category counts against the build's `Indexing marks…` summary line. For colour/hole-fidelity
checks, compare a render against any reference image before trusting the output.

## Branch & PR workflow (do this for every task)

**Start every new piece of work from an up-to-date `main`.** Before touching anything:

```bash
git checkout main && git pull --ff-only
```

Then cut a fresh branch for the task and do the work there — **never commit directly to
`main`**, and don't resume work on some pre-existing branch unless there's a specific reason to
(e.g. the user names it, or you're explicitly continuing that exact PR). A stale feature branch
can be behind `main`; starting from freshly-pulled `main` avoids building on old state.

```bash
git checkout -b <short-kebab-branch-name>
# ...make the change, rebuild, commit the SVG/data + generated files...
git push -u origin <short-kebab-branch-name>
gh pr create   # every task ends with a PR, not a direct push to main
```

So the shape of any task is: **main (pulled) → branch → commit → PR**. Only skip the branch/PR
for throwaway inspection that changes nothing.

## Contributing flow

See `CONTRIBUTING.md`. In short: from an up-to-date `main`, cut a branch, add an SVG in the
right folder, run `python3 tools/build.py`, commit the SVG + generated files, and open a PR
crediting the original creator.
