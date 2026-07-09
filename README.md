# awesome-wipeout

> A curated, non-commercial hub of WipEout-universe **art and design** — logos, emblems and
> marks, fonts, in-game reference and links.

**awesome-wipeout** is a community-maintained, normalised library of art and design from the
**WipEout** anti-gravity racing universe: racing teams, sponsors, tracks, speed classes, game
modes, weapons, pilots and series title logos — plus referenced fonts, an in-game reference
gallery, and a curated set of links to the best WipEout design resources across the web.

It started as reference-gathering for a set of [LEGO WipEout ship builds](https://andre.lackmann.net/tags/lego/)
and turned into an attempt to collate, in one place, the major WipEout design & art references
that are otherwise scattered across Reddit, DeviantArt and page 10 of Google. See the
[About page](https://awesome-wipeout.github.io/about.html) for the fuller story.

## 👉 Browse the site

**Live: https://awesome-wipeout.github.io/**

Or open [`index.html`](index.html) locally. The site is multi-page:

| Page | What's there |
| ---- | ------------ |
| **Marks** ([index.html](index.html)) | The vector logo/emblem/mark library — the main tear sheet |
| **Fonts** ([fonts.html](fonts.html)) | WipEout typefaces (referenced, never hosted; specimen sheets outlined at build) |
| **In-game reference** ([reference.html](reference.html)) | Screenshot reference, grouped by game & team |
| **Links** ([links.html](links.html)) | Fan sites, art & posters, articles, LEGO builds, tools |
| **About / Licensing / Credits** | The story, terms, and attribution |

## The marks: SVG + PNG

Every hosted mark is provided in two formats:

| Format | Use it for |
| ------ | ---------- |
| **SVG** | The source of truth. Fully scalable and editable in any vector tool (Illustrator, Figma, Inkscape, Affinity). Best for reusing in your own designs. |
| **PNG** | 1024&nbsp;px, transparent background. Drop-in raster for docs, slides, web and tools that don't take SVG. |

Some marks are **reference-only**: where a contributor's licence doesn't permit redistributing
the vector, only an indicative PNG is shown and the "get vector" link points to the artist's
source (see [LICENSING.md](LICENSING.md)).

📄 **Designers:** [`tearsheet.pdf`](tearsheet.pdf) is a multi-page, fully-vector version of the
mark library — open it in Illustrator, Affinity or Acrobat and copy/paste any logo straight into
your work.

## Library structure

```
marks/
├── titles/          Series & game wordmarks (WipEout … Omega Collection)
├── teams/
│   ├── wo1/         Racing teams — original WipEout (1995) styling
│   ├── 2097/        Racing teams — WipEout 2097 / XL styling
│   ├── wip3out/     Racing teams — Wip3out styling
│   ├── pure/        Racing teams — WipEout Pure styling
│   └── hd/          Racing teams — WipEout HD / 2048 styling
├── pilots/          Pilot emblems from the original WipEout
├── classes/         Speed-class badges (Venom, Flash, Rapier, Phantom)
├── game-modes/      Game-mode emblems (Zone Battle, Eliminator, Time Trial, …)
├── weapons/         Weapon pickup glyphs
├── sponsors/        In-universe sponsor / brand logos
├── tracks/          Circuit & venue logos
├── leagues/         League / series marks (F3600 … FX400)
├── misc/            Ship silhouettes, custom marks & other glyphs
└── manifest.json    Auto-generated index of every asset (do not edit by hand)

fonts/               Font specimen sheets + manifest.json (the Fonts section)
reference/           In-game screenshot reference (raster) + manifest.json
data/*.toml          Authored metadata (marks, fonts, pages, reference)
```

Each hosted mark exists as `name.svg` (vector source + download) and `name.png` (raster) side by
side; there are no per-asset PDFs — for print/vector use, grab the SVG or the
[tear sheet](tearsheet.pdf). Filenames are lowercase-kebab-case; team logos live under a per-era
subfolder so the same team can appear in each of its game generations
(e.g. `teams/2097/feisar.svg` vs `teams/pure/feisar.svg`).

Build = code, data = data: `tools/build.py` holds no authored metadata — it reads `data/*.toml`
and generates every manifest, HTML page and the tear sheet. Never hand-edit generated files.

## Using an asset

Just grab the file you want from `marks/…`. The SVGs have no external dependencies. The
single-colour marks (sponsors, tracks, classes, game modes) are solid black by default —
recolour them in your editor, or via CSS if you inline the SVG. Please stay within each
contributor's stated licence — check [LICENSING.md](LICENSING.md) first.

## Contributing

New or improved artwork, fonts, reference or links are all welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). In short: add or replace an **SVG** in the right folder, run
`python3 tools/build.py`, and the PNG derivative, manifests and tear sheet regenerate. Or open an
[issue](https://github.com/awesome-wipeout/awesome-wipeout.github.io/issues) if you'd rather just flag something.

## Provenance & credits

These assets were compiled and normalised from work generously shared by the WipEout community.
Full attribution and source links are in [CREDITS.md](CREDITS.md).

Contributors include: ollite20, Curtis Agnew (X_0rm), Liger-Inuzuka, toolboxio, and
djdrey909 / Andre Lackmann ([andre.lackmann.net](https://andre.lackmann.net)).

The `tools/` folder contains the extractors used to build this library, including custom parsers
for two awkward source formats:

* `ai_to_svg.py` — recovers artwork from CorelDRAW-exported `.ai` files whose PDF layer is empty
  and whose paths live in the native Illustrator private-data stream.
* `csh_to_svg.py` — decodes Adobe Photoshop Custom Shape (`.csh`) binaries into SVG.
* `build.py` — renders PNG derivatives and regenerates the manifests, every HTML page and the tear sheet.

## Legal

WipEout and all related names, logos and marks are trademarks of **Sony Interactive Entertainment
/ Studio Liverpool (formerly Psygnosis)**. This repository is a non-commercial, fan-made archive
created for preservation and community use. It is not affiliated with or endorsed by Sony. All
original creators retain credit for their work. See [LICENSE.md](LICENSE.md) and
[LICENSING.md](LICENSING.md).
