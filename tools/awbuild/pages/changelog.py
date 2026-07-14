from awbuild.core import *


VERSIONS_MAX_SHOWN = 20   # most-recent entries rendered; older ones link out to GitHub
RELEASES_API = "https://api.github.com/repos/awesome-wipeout/awesome-wipeout.github.io/releases?per_page=100"


def _versions_data():
    """Fetch the changelog from the repository's GitHub Releases — the *authored* release
    notes, not raw commit/tag messages (so no "Merge pull request …" subjects leak in).
    Returns a list of dicts (newest first) with version, date, title, body and url.

    Network-dependent: returns None when the Releases API can't be reached (offline build,
    rate limit) so the caller keeps the committed changelog.html rather than blanking it;
    returns [] only when the repo genuinely has no published releases."""
    import urllib.request, ssl
    # Prefer certifi's CA bundle when present — the python.org macOS build ships without
    # system roots, so the default context otherwise fails CERTIFICATE_VERIFY_FAILED.
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    try:
        req = urllib.request.Request(RELEASES_API, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "awesome-wipeout-build",
        })
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            releases = json.load(r)
    except Exception as e:
        print(f"  !! changelog: GitHub Releases unreachable ({e}); keeping committed changelog.html")
        return None
    out = []
    for rel in releases:
        if rel.get("draft"):
            continue                                   # unpublished drafts aren't public history
        tag = rel.get("tag_name") or ""
        out.append({
            "version": tag,
            "title": (rel.get("name") or "").strip() or (f"Version {tag}" if tag else "Release"),
            "date": (rel.get("published_at") or rel.get("created_at") or "")[:10],
            "body": (rel.get("body") or "").strip(),
            "url": rel.get("html_url") or "",
        })
    out.sort(key=lambda v: v["date"], reverse=True)    # newest first (API order, made explicit)
    return out


def build_versions_page(page):
    """Build the Changelog page from the repo's GitHub Releases (newest first). Each
    release's notes are rendered as Markdown so bullet lists format properly. Capped at
    VERSIONS_MAX_SHOWN entries, with a link to the full release history on GitHub for
    anything older. If the Releases API is offline the committed page is left untouched."""
    releases = _versions_data()
    if releases is None:
        return  # API unreachable — keep the committed changelog.html rather than blank it
    parts = []
    if page.get("intro"):
        parts.append(f'<p class="lead">{_md_inline(page["intro"])}</p>')
    if not releases:
        parts.append("<p>No releases published yet.</p>")
    else:
        parts.append('<div class="versions-list">')
        for v in releases[:VERSIONS_MAX_SHOWN]:
            body_html = md_to_html(v["body"]) if v["body"] else ""
            date_span = f' <span class="version-date">{esc(v["date"])}</span>' if v.get("date") else ""
            parts.append(
                f'<div class="version-entry">'
                f'<h2 class="version-head">{esc(v["title"])}{date_span}</h2>'
                f'<div class="version-body">{body_html}</div>'
                f'</div>'
            )
        parts.append('</div>')
        if len(releases) > VERSIONS_MAX_SHOWN:
            parts.append(
                f'<p class="versions-more">Showing the {VERSIONS_MAX_SHOWN} most recent '
                f'releases. <a href="{GITHUB}/releases" target="_blank" rel="noopener">'
                f'See the full release history on GitHub &rarr;</a></p>'
            )
    body = (f'<div class="prose"><h1>{esc(page["title"])}</h1>\n'
            + "\n".join(parts) + "\n</div>")
    _write(page["file"], _document(page["slug"], page["title"], "", body))
