from awbuild.core import *


from awbuild.pages.reference import build_reference_page
from awbuild.pages.teams import build_teams_page
from awbuild.pages.leagues import build_leagues_page
from awbuild.pages.prose import build_prose_page


def build_pages(manifest, font_manifest, ref_manifest=None):
    """Render every registered page. Marks + fonts share the intermediate build
    below (cards, credits, lightbox); the two are written as separate documents.
    Reference pages render the screenshot gallery; anything else is a prose page.
    manifest / font_manifest / ref_manifest are the in-memory indexes (not read from
    disk) — the Leagues page resolves its marks + fonts from the first two."""
    # Reverse-usage index: which Leagues / Teams reference each mark (by id = path minus ext)
    # and each font (by slug). Surfaced as "featured in" back-links inside the marks/fonts
    # lightboxes (leagues.html#<slug> and teams.html#<team>--<series> deep-links).
    def _mid(f):
        return f.rsplit(".", 1)[0]
    mark_use, font_use = {}, {}
    try:
        _lg = _load_toml("leagues.toml").get("league", [])
    except Exception:
        _lg = []
    for lg in _lg:
        ref = {"kind": "league", "slug": lg["slug"], "label": lg["name"]}
        seen = set()
        for f in [lg["logo"]] + [m["file"] for m in lg.get("marks", [])]:
            mid = _mid(f)
            if mid not in seen:
                seen.add(mid)
                mark_use.setdefault(mid, []).append(ref)
        for fo in lg.get("fonts", []):
            font_use.setdefault(fo["slug"], []).append(ref)
    try:
        _tm = _load_toml("teams.toml")
    except Exception:
        _tm = {}
    _tn = {t["slug"]: t.get("name", t["slug"]) for t in _tm.get("team", [])}
    _sn = {s["slug"]: s.get("name", s["slug"]) for s in _tm.get("series", [])}
    for b in _tm.get("brand", []):
        mark_use.setdefault(_mid(b["logo"]), []).append(
            {"kind": "team", "slug": b["team"] + "--" + b["series"],
             "label": _tn.get(b["team"], b["team"]) + " · " + _sn.get(b["series"], b["series"])})
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
            _aid = (a["svg"] or a["png"])[len("marks/"):].rsplit(".", 1)[0]
            lb_entry = {"name": a["name"], "svg": a["svg"], "png": a["png"], "id": _aid,
                        "use": mark_use.get(_aid, [])}
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
        # Include a link to the contributor's main page (profile / repo root), not just
        # the specific asset packs they contributed.
        link_html = "".join(
            f'<a class="contrib-link" data-contrib="{esc(c["id"])}" '
            f'href="{esc(u)}" target="_blank" rel="noopener">{esc(t)}</a>'
            for t, u in _with_home_link(c["links"]))
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
        links = _with_home_link(([(_host(url), url)] if url else []) + FONT_CREDIT_EXTRA.get(des, []))
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
                        "link": link, "getlabel": link_label, "shot": src,
                        "use": font_use.get(slug, [])})
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
    # The "get" link points at the repo's main page, not the individual .ttf file.
    fan_cards = ([fcard(fam, era, FONTS_REPO,
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
  <div class="lb-used" id="lbUsed"></div>
</div>"""
    lb_script = """<script>
(function(){
  var ASSETS = __ASSETS__;
  var lb=document.getElementById('lightbox'), img=document.getElementById('lbImg'),
      stage=document.getElementById('lbStage'), nameEl=document.getElementById('lbName'),
      dl=document.getElementById('lbDl'), used=document.getElementById('lbUsed'); var i=0, bg='transparent';
  function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function useHTML(u){ if(!u||!u.length) return '';
    return '<span class="use-k">Featured in</span>'+u.map(function(x){
      var href=(x.kind==='league'?'leagues.html#':'teams.html#')+x.slug;
      return '<a href="'+href+'">'+esc(x.label)+'</a>'; }).join(''); }
  try{ bg = localStorage.getItem('wo-lb-bg') || 'transparent'; }catch(e){}
  function applyBg(){ stage.className='lb-stage bg-'+bg;
    lb.querySelectorAll('.lb-toggle button').forEach(function(b){
      b.classList.toggle('on', b.getAttribute('data-bg')===bg); }); }
  var BYID={}; ASSETS.forEach(function(a,idx){ BYID[a.id]=idx; });
  function render(n){ i=(n+ASSETS.length)%ASSETS.length; var a=ASSETS[i];
    img.setAttribute('src', a.svg || a.png); img.setAttribute('alt', a.name); nameEl.textContent=a.name;
    used.innerHTML = useHTML(a.use);
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
  <div class="lb-used fbox-used" id="fbUsed"></div>
</div>"""
    fonts_script = """<script>
(function(){
  var FONTS = __FONTS__;
  var fb=document.getElementById('fbox'), img=document.getElementById('fbImg'),
      nm=document.getElementById('fbName'), era=document.getElementById('fbEra'),
      note=document.getElementById('fbNote'), get=document.getElementById('fbGet'),
      used=document.getElementById('fbUsed');
  var i=0;
  var BYSLUG={}; FONTS.forEach(function(f,idx){ BYSLUG[f.slug]=idx; });
  function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function useHTML(u){ if(!u||!u.length) return '';
    return '<span class="use-k">Featured in</span>'+u.map(function(x){
      var href=(x.kind==='league'?'leagues.html#':'teams.html#')+x.slug;
      return '<a href="'+href+'">'+esc(x.label)+'</a>'; }).join(''); }
  function render(n){
    i=(n+FONTS.length)%FONTS.length; var f=FONTS[i];
    nm.textContent=f.name; era.textContent=f.meta; used.innerHTML=useHTML(f.use);
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
            build_leagues_page(p, manifest, font_manifest)
        else:
            build_prose_page(p)


