from awbuild.core import *


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
function showCell(id){
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
  // Mark credit, underneath everything else — links to the marks-page credits like the
  // marks grid's "source:" link (index.html#credit-<id>). Only shown once there's a mark.
  let credit="";
  if(c.state!=="gap"){
    credit = c.credit
      ? '<a class="src" href="index.html#credit-'+encodeURIComponent(c.credit)+'" title="Source — jump to credits">source: '+esc(c.credit_name)+'</a>'
      : '<span class="src src-none">source: needed</span>';
    credit='<div class="dcredit">'+credit+'</div>';
  }
  dInner.innerHTML=head+logoBlock+'<div class="dbody">'+body+credit+'</div>';
  document.body.classList.add("drawer-open"); drawer.setAttribute("aria-hidden","false"); dInner.scrollTop=0;
}
function hideDrawer(){ document.body.classList.remove("drawer-open"); drawer.setAttribute("aria-hidden","true"); }
function closeDrawer(){ if(location.hash){ history.replaceState(null,"",location.pathname+location.search); } hideDrawer(); }
// deep-linkable: teams.html#<team>--<series> opens that cell's drawer (used by marks-lightbox back-links)
var SLUGMAP={};
Object.keys(REC).forEach(function(id){ var c=REC[id]; if(c.tslug) SLUGMAP[c.tslug+"--"+c.sslug]=id; });
function openCell(id){ var c=REC[id]; if(c&&c.tslug){ location.hash=c.tslug+"--"+c.sslug; } else { showCell(id); } }
function handleHash(){ var id=SLUGMAP[(location.hash||"").replace(/^#/,"")]; if(id){ showCell(id); } else { hideDrawer(); } }
window.addEventListener("hashchange", handleHash);
function copy(t){ if(navigator.clipboard&&navigator.clipboard.writeText) return navigator.clipboard.writeText(t); var a=document.createElement("textarea");a.value=t;a.style.position="fixed";a.style.opacity="0";document.body.appendChild(a);a.select();try{document.execCommand("copy");}catch(e){}document.body.removeChild(a);return Promise.resolve(); }
document.addEventListener("click", function(e){
  var cell=e.target.closest("[data-id]"); if(cell){ openCell(cell.getAttribute("data-id")); return; }
  var sw=e.target.closest(".sw"); if(sw){ var hex=sw.getAttribute("data-hex"); copy(hex).then(function(){ sw.classList.add("copied"); sw.querySelector(".copy").textContent="Copied"; showToast('Copied <code>'+hex+'</code>'); setTimeout(function(){ sw.classList.remove("copied"); sw.querySelector(".copy").textContent="Copy"; },1100); }); }
});
document.addEventListener("keydown", function(e){ if(e.key==="Escape") closeDrawer(); });
handleHash();  // open the deep-linked cell (teams.html#<team>--<series>) on load
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

    def _sig(b):  # two adjacent cells merge only if the mark is identical in every shown respect
        return (b["logo"], json.dumps(b.get("colors", []), sort_keys=True),
                b.get("state") or "unknown", b.get("notes", ""))

    def _span_meta(run_series):  # label / year / league for a run of series sharing one mark
        names = [s["name"] for s in run_series]
        shorts = [n[8:] if n.startswith("WipEout ") else n for n in names]
        if len(names) == 1:
            label = names[0]
        elif len(names) == 2:
            label = f"{names[0]} & {shorts[1]}"
        else:
            label = names[0] + ", " + ", ".join(shorts[1:-1]) + " & " + shorts[-1]
        years = [s["year"] for s in run_series]
        yr = years[0] if min(years) == max(years) else f"{min(years)}–{max(years)}"
        lgs = []
        for s in run_series:
            lg = s.get("league", "")
            if lg and lg not in lgs:
                lgs.append(lg)
        return label, yr, "/".join(lgs)

    rec = {}
    for ti, t in enumerate(teams):
        txt = "#12151a" if _lum(t["bar"]) > .6 else "#fff"
        cells.append(f'<div class="cell rowhead"><span class="bar" style="background:{esc(t["bar"])}"></span>'
                     f'<span class="rh-body"><span class="tname">{esc(t["name"])}</span>'
                     f'<span class="tsub">{esc(t.get("sub",""))}</span></span></div>')
        si = 0
        while si < len(series):
            s = series[si]
            b = brands.get((t["slug"], s["slug"]))
            cid = f"{ti}_{si}"
            if b:
                state = b.get("state") or "unknown"
                # Series that share one set of emblems (same `cobrand` group) and show the
                # identical mark get merged: render it once, spanning + centred over those
                # columns, instead of replicating the logo cell-by-cell. Only co-branded
                # series merge — a coincidental file reuse in an unrelated era does not.
                sig = _sig(b)
                cob = s.get("cobrand")
                run = [si]
                sj = si + 1
                while cob and sj < len(series):
                    s2 = series[sj]
                    b2 = brands.get((t["slug"], s2["slug"]))
                    if s2.get("cobrand") == cob and b2 and _sig(b2) == sig:
                        run.append(sj)
                        sj += 1
                    else:
                        break
                run_series = [series[k] for k in run]
                label, yr, league = _span_meta(run_series)
                span = len(run)
                # span the columns (drops the internal dividers → one merged cell) but keep the
                # mark itself no wider than a single column so wide logos don't balloon.
                style = (f' style="grid-column:span {span}"') if span > 1 else ''
                imgstyle = f' style="max-width:calc(100%/{span})"' if span > 1 else ''
                cells.append(f'<div class="cell"{style}><div class="mk" data-id="{cid}">'
                             f'<div class="logo"><img src="{png(b["logo"])}"{imgstyle} '
                             f'alt="{esc(t["name"])} — {esc(label)}" loading="lazy"></div></div></div>')
                # credit for the underlying mark (from data/marks.toml) — shown in the drawer,
                # linked to the marks-page credits like the marks grid's "source:" link.
                lcid = ASSETS_META.get(b["logo"], {}).get("credit", "")
                merged = {"team": t["name"], "sub": t.get("sub", ""), "bar": t["bar"], "txt": txt,
                          "series": label, "yr": yr, "league": league, "tslug": t["slug"],
                          "state": state, "png": png(b["logo"]), "svg": "marks/" + b["logo"],
                          "colors": b.get("colors", []), "notes": b.get("notes", ""),
                          "credit": lcid, "credit_name": CREDIT_NAME.get(lcid, lcid) if lcid else ""}
                # one record per covered series so deep-links (teams.html#<team>--<series>) still resolve
                for k in run:
                    rec[f"{ti}_{k}"] = {**merged, "sslug": series[k]["slug"]}
                si = sj
                continue
            base = {"team": t["name"], "sub": t.get("sub", ""), "bar": t["bar"], "txt": txt,
                    "series": s["name"], "yr": s["year"], "league": s.get("league", ""),
                    "tslug": t["slug"], "sslug": s["slug"]}
            if t["slug"] in s.get("roster", []):
                cells.append(f'<div class="cell"><div class="gapcell" data-id="{cid}">'
                             f'<span><span class="plus">+</span>logo&nbsp;needed</span></div></div>')
                rec[cid] = {**base, "state": "gap", "sser": s["slug"], "steam": t["slug"]}
            else:
                cells.append(f'<div class="cell na" title="{esc(t["name"])} didn’t race in {esc(s["name"])}"></div>')
            si += 1

    ncols = len(series)
    grid_style = f"grid-template-columns:var(--first,168px) repeat({ncols}, minmax(var(--colmin,0px),1fr))"
    matrix = (f'<div class="matrixwrap"><div class="matrix" style="{grid_style}">\n'
              + "\n".join(cells) + "\n</div></div>")

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
