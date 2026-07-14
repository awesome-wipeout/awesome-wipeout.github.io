from awbuild.core import *


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


