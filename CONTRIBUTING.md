# Contributing

Thanks for helping grow **awesome-wipeout**! Whether you've made WipEout art, found a great asset,
or spotted something wrong, contributions are very welcome. There are **two ways** to do it — pick
whichever suits you.

## The easy way — just open an issue

**No GitHub skills or command line needed.** If you've got something to add (a logo, a font, a
screenshot, a link) or a correction to make, just
[open an issue](https://github.com/awesome-wipeout/awesome-wipeout.github.io/issues) and tell us
about it. The more of this you can include, the faster it goes in:

- **What it is** — e.g. "AG-Systems team logo, WipEout HD era".
- **A link to the source** — where it comes from (a DeviantArt page, the creator's site, a forum
  post, wherever you found it).
- **Who made it** — the original creator's name or handle, so they get credited.
- **The licence**, if you know it — or just link the page where the terms are stated.
- **The file itself** — you can drag an SVG or PNG straight into the issue.

A maintainer takes it from there. This is also the way to **flag a wrong credit, a licensing
concern, or ask for your own work to be removed** — it'll be actioned promptly.

## The hands-on way — open a pull request

If you're comfortable with git and GitHub, you can add the asset yourself. Everything is
data-driven: the authored metadata lives in **`data/*.toml`**, and `tools/build.py` regenerates
all the rest — the PNGs, the HTML pages and the tear sheet. **Never hand-edit the
generated files.**

The shape is always the same: **register the contributor → add the asset → open a PR.**

### 1. Register the contributor (if new)

Every asset is credited to a **contributor** — the person who created it. That might be you, or
the original artist whose work you're adding. If they're not already in
`data/contributors.toml`, add a block:

```toml
[[contributor]]
id = "handle"                         # stable slug used to credit their work
name = "Their Name (handle)"
blurb = "What they contributed"
license = { name = "CC BY-NC 4.0", url = "https://creativecommons.org/licenses/by-nc/4.0/" }
links = [ { label = "their source page", url = "https://…" } ]
```

The `license` matters — tracking provenance is the whole point (see [LICENSING.md](LICENSING.md)).
It has a `name`, an optional `url` (a link to the licence itself — e.g. the Creative Commons page),
and an optional `note`: a short plain-English description of the terms, for when the licence is
informal and has no standard link — e.g. `note = "Used with credit; artist asks for a link back."`

> **Only add work you have the right to.** Either you are the original author, **or** the licence /
> permission must be **clearly stated at the creator's linked source**. If the provenance or terms
> aren't clear, don't add it — [open an issue](https://github.com/awesome-wipeout/awesome-wipeout.github.io/issues)
> so it can be checked first.

### 2. Add your asset

Pick the one that matches what you're contributing.

#### A vector logo — hosted as SVG

1. Drop a clean **SVG** into the right `marks/<section>/` folder (`titles`, `teams/<era>`, `classes`, `game-modes`, `sponsors`, `tracks`, `leagues`, `misc`, …), named lowercase-kebab-case: `ag-systems.svg`. Vector paths only — **no embedded bitmaps**, a tightly cropped `viewBox`, and single-colour marks in solid black (`#000000`).
2. Register it in `data/marks.toml` (one entry per file). `python3 tools/scaffold.py --write` writes the stub for you — just fill in the `credit` (the contributor's `id`).

#### A reference-only mark — PNG only

For art whose licence won't let us redistribute the vector, add just a **PNG** — *no* SVG (that absence is what marks it reference-only). This is a **vector library**, so the `source` link **must** lead to where the actual **vector** can be obtained (the creator's own page or pack) — not merely an image or a mention. If there's no vector available anywhere, it isn't a fit for the library. Add the `data/marks.toml` entry with that `source`.

#### A font — referenced, never hosted

Add an entry to `data/fonts.toml` in the right group, with a "get" `url`. If the designer isn't already a contributor, add them in step 1 first.

*The exact fields are documented in comments at the top of each `data/*.toml` file.*

### 3. Open the pull request

Describe the asset, link its source, and confirm the licence. That's it — thank you! 🏁

**No need to build anything.** Just commit your file(s) and your `data/*.toml` edit — the generated
site (PNGs, HTML pages and the tear sheet) is rebuilt from your source before it goes
live.

*(Want to preview locally first? `pip install cairosvg pymupdf fonttools lxml pillow` then
`python3 tools/build.py` — but it's entirely optional.)*
