from awbuild.core import *


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


