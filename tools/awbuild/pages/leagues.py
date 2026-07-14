from awbuild.core import *


_LEAGUES_SCRIPT = r"""<script>
const LREC = __LREC_JSON__;
const llb = document.getElementById("llb");
const llbPanel = document.getElementById("llbPanel");
function esc(s){ return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function markCard(m){
  var view='<a class="llb-view" href="index.html#m/'+esc(m.id)+'">View on Marks page ↗</a>';
  return '<div class="llb-mcard"><div class="llb-mthumb"><img src="'+esc(m.png)+'" alt="'+esc(m.name)+'" loading="lazy"></div><div class="llb-mmeta"><div class="llb-mnote">'+esc(m.note)+'</div>'+view+'</div></div>';
}
function fontCard(f){
  var shot = f.specimen ? '<div class="llb-fshot"><img src="'+esc(f.specimen)+'" alt="'+esc(f.name)+' specimen"></div>' : '<div class="llb-fshot llb-fshot-none">'+esc(f.name)+'</div>';
  var view='<a class="llb-view" href="fonts.html#f/'+esc(f.slug)+'">View on Fonts page ↗</a>';
  return '<div class="llb-fcard">'+shot+'<div class="llb-fmeta"><div class="llb-fname">'+esc(f.name)+'</div><div class="llb-fnote">'+esc(f.note)+'</div>'+view+'</div></div>';
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
    +(c.launchbox?'<li><span class="k">LaunchBox DB</span><span class="v"><a class="llb-extlink" href="'+esc(c.launchbox)+'" target="_blank" rel="noopener">images ↗</a></span></li>':'')
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
  if(e.target.closest(".llb-view")) return;  // let the "View on Marks/Fonts page" links navigate
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


def build_leagues_page(page, mman, fman):
    """The Leagues page: a sortable table of every anti-gravity racing league (rows) from
    data/leagues.toml, each row opening a full-screen lightbox with the league's marks, fonts
    and lore. Marks and fonts are resolved from the in-memory manifests (passed in) so their
    names, downloads and specimens stay 1:1 with the collections (reference-only marks — a .png
    with no sibling vector — link out to where the artist hosts the SVG instead of downloading)."""
    data = _load_toml("leagues.toml")
    leagues = data.get("league", [])

    MK = {}
    for s in mman["sections"]:
        for a in s["assets"]:
            MK[(a["svg"] or a["png"])[len("marks/"):]] = a

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
            marks_out.append({
                "name": a["name"] if a else m["file"],
                "note": m.get("note", ""),
                "png": png(m["file"]),
                # deep-link to the mark's full-screen view on the Marks page (index.html#m/<id>)
                "id": m["file"].rsplit(".", 1)[0],
            })
        fonts_out = [{
            "name": font_name(fo["slug"]),
            "note": fo.get("note", ""),
            "specimen": (FT.get(fo["slug"]) or {}).get("specimen"),
            # deep-link to the font's full-screen view on the Fonts page (fonts.html#f/<slug>)
            "slug": fo["slug"],
        } for fo in lg.get("fonts", [])]
        rec[slug] = {
            "name": lg["name"], "game": lg["game"], "released": lg["released"],
            "game_year": lg["game_year"], "blurb": " ".join(lg["blurb"].split()),
            "logo": png(lg["logo"]), "marks": marks_out, "fonts": fonts_out,
            "metascore": lg.get("metascore"), "metacritic": lg.get("metacritic"),
            "platforms": lg.get("platforms", []), "launchbox": lg.get("launchbox"),
        }
        mchips = "".join(
            f'<span class="mchip"><img src="{esc(png(m["file"]))}" alt="" '
            f'title="{esc(m.get("note",""))}" loading="lazy"></span>'
            for m in lg.get("marks", []))
        fchips = ""
        for fo in lg.get("fonts", []):
            spec = (FT.get(fo["slug"]) or {}).get("specimen")
            nm, fnote = font_name(fo["slug"]), fo.get("note", "")
            if spec:
                fchips += (f'<span class="fchip"><img src="{esc(spec)}" alt="{esc(nm)}" '
                           f'title="{esc(fnote)}" loading="lazy"></span>')
            else:  # commercial faces with no committed specimen — show the name pill
                fchips += f'<span class="fpill" title="{esc(fnote)}">{esc(nm)}</span>'
        rows.append(
            f'<tr class="lrow" data-id="{esc(slug)}" data-released="{lg["released"]}" '
            f'data-ingame="{lg["game_year_sort"]}">'
            f'<td class="l-logo"><img src="{esc(png(lg["logo"]))}" alt="{esc(lg["name"])} emblem" loading="lazy"></td>'
            f'<td class="l-name">{esc(lg["name"])}</td>'
            f'<td class="l-game">{esc(lg["game"])}</td>'
            f'<td class="l-yr">{lg["released"]}</td>'
            f'<td class="l-yr">{esc(lg["game_year"])}</td>'
            f'<td class="l-marks">{mchips}</td>'
            f'<td class="l-fonts">{fchips}</td>'
            f'</tr>')

    thead = ('<thead><tr>'
             '<th></th><th>League</th><th>Game</th>'
             '<th class="sortable" data-sort="released">Released<span class="arw">▲▼</span></th>'
             '<th class="sortable sorted-asc" data-sort="ingame">In-game year<span class="arw">▲▼</span></th>'
             '<th>Marks</th><th>Fonts</th>'
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



