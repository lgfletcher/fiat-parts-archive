#!/usr/bin/env python3
"""
Export wiring diagrams to the static site (phase 1: the raster layer).

    python3 pipeline/export_wiring.py --db fiat.db \
        --sheets archive/derived/wiring --out docs

Produces:
    docs/wiring.html                  the wiring viewer (one file, all diagrams)
    docs/wiringdata/<slug>.js         sheets + overlay payload for one diagram
    docs/wiringimg/<slug>/sNN.webp    sheet images
    docs/wiring_index.js              list of wiring diagrams

The overlay arrays (components / wires / circuits) are exported here too. They
are empty until the phase-2 editor fills wd_component / wd_wire / wd_circuit,
but the viewer already draws whatever is in them, so tracing work shows up on
the site the moment it lands in fiat.db.

docs/wiring_ref.js (colour codes, fuse lore) is hand-maintained, not generated.
"""
import argparse, json, shutil, sqlite3
from pathlib import Path


def fetch_overlay(db, diagram_id, sheet_ids):
    """Components / wires / circuits for one diagram, keyed by sheet number."""
    comps, wires = [], []
    for sheet_no, sid in sheet_ids.items():
        for c in db.execute("""SELECT code,name,name_en,x,y,w,h,location_on_car,
                                      terminals,part_no,notes,conf,verified
                               FROM wd_component WHERE sheet_id=? ORDER BY code""", (sid,)):
            comps.append({"s": sheet_no, "code": c["code"], "name": c["name"],
                          "en": c["name_en"], "x": c["x"], "y": c["y"],
                          "w": c["w"], "h": c["h"], "loc": c["location_on_car"],
                          "pins": json.loads(c["terminals"]) if c["terminals"] else [],
                          "pn": c["part_no"], "notes": c["notes"],
                          "conf": c["conf"], "v": c["verified"]})
        for w in db.execute("""SELECT label,colour_code,gauge,from_component,from_pin,
                                      to_component,to_pin,path,circuit_ids,conf,
                                      verified,notes
                               FROM wd_wire WHERE sheet_id=? ORDER BY id""", (sid,)):
            wires.append({"s": sheet_no, "label": w["label"], "col": w["colour_code"],
                          "gauge": w["gauge"], "from": w["from_component"],
                          "fpin": w["from_pin"], "to": w["to_component"],
                          "tpin": w["to_pin"],
                          "path": json.loads(w["path"]) if w["path"] else [],
                          "circuits": [x for x in (w["circuit_ids"] or "").split(",") if x],
                          "conf": w["conf"], "v": w["verified"], "notes": w["notes"]})
    circuits = [{"code": c["code"], "name": c["name"], "grp": c["grp"],
                 "desc": c["descr"],
                 "symptoms": [s for s in (c["symptoms"] or "").split("\n") if s],
                 "tests": [t for t in (c["tests"] or "").split("\n") if t],
                 "conf": c["conf"]}
                for c in db.execute("""SELECT code,name,grp,descr,symptoms,tests,conf
                                       FROM wd_circuit WHERE diagram_id=?
                                       ORDER BY grp,name""", (diagram_id,))]
    return comps, wires, circuits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--sheets", default="archive/derived/wiring")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "wiringdata").mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    index = []
    for d in db.execute("""SELECT id,slug,title,year_from,year_to,market,variant_note,
                                  credit,pilot,notes
                           FROM wiring_diagram ORDER BY sort_order, slug"""):
        rows = db.execute("""SELECT id,sheet_no,kind,label,file_path,width_px,height_px,
                                    native_w,native_h,ocr_text
                             FROM wd_sheet WHERE diagram_id=? ORDER BY sheet_no""",
                          (d["id"],)).fetchall()
        if not rows:
            print(f"  {d['slug']}: no sheets — skipped")
            continue

        imgdir = out / "wiringimg" / d["slug"]
        imgdir.mkdir(parents=True, exist_ok=True)
        sheets, sheet_ids = [], {}
        for r in rows:
            src = Path(args.sheets) / r["file_path"]
            dst = imgdir / Path(r["file_path"]).name
            if src.exists() and (not dst.exists()
                                 or src.stat().st_mtime > dst.stat().st_mtime):
                shutil.copy2(src, dst)
            sheet_ids[r["sheet_no"]] = r["id"]
            sheets.append({"n": r["sheet_no"], "kind": r["kind"], "label": r["label"],
                           "img": f"wiringimg/{d['slug']}/{Path(r['file_path']).name}",
                           "w": r["width_px"], "h": r["height_px"],
                           "nw": r["native_w"], "nh": r["native_h"],
                           "txt": (r["ocr_text"] or "")[:6000]})

        comps, wires, circuits = fetch_overlay(db, d["id"], sheet_ids)
        payload = {"slug": d["slug"], "title": d["title"],
                   "years": [d["year_from"], d["year_to"]], "market": d["market"],
                   "variant": d["variant_note"],
                   "pilot": bool(d["pilot"]), "notes": d["notes"],
                   "sheets": sheets, "components": comps, "wires": wires,
                   "circuits": circuits}
        (out / "wiringdata" / f"{d['slug']}.js").write_text(
            "window.WIRINGDATA=window.WIRINGDATA||{};window.WIRINGDATA["
            + json.dumps(d["slug"]) + "]=" + json.dumps(payload) + ";")

        index.append({"slug": d["slug"], "title": d["title"],
                      "years": [d["year_from"], d["year_to"]], "market": d["market"],
                      "pilot": bool(d["pilot"]), "nsheets": len(sheets),
                      "nmaster": sum(1 for s in sheets if s["kind"] == "master"),
                      "traced": len(wires)})
        print(f"exported {d['slug']}: {len(sheets)} sheets, "
              f"{len(comps)} components, {len(wires)} wires")

    (out / "wiring_index.js").write_text("window.WIRING_INDEX=" + json.dumps(index) + ";")
    (out / "wiring.html").write_text(TEMPLATE)
    print(f"wiring_index: {len(index)} diagrams")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wiring diagrams — Fiat Classic Parts Archive</title>
<style>
 :root{--bg:#1c1f26;--panel:#252932;--panel2:#2c313c;--line:#3a4150;--txt:#e8e6df;
   --dim:#9aa0ac;--accent:#e8b84b;--accent2:#7fb4d8;--ok:#8fc98f}
 *{box-sizing:border-box;margin:0;padding:0}html,body{height:100%}
 body{font-family:"Avenir Next","Segoe UI",system-ui,sans-serif;background:var(--bg);
   color:var(--txt);display:flex;flex-direction:column;overflow:hidden}
 header{display:flex;align-items:center;gap:12px;padding:10px 18px;background:var(--panel);
   border-bottom:1px solid var(--line);flex-wrap:wrap}
 h1{font-size:14px;font-weight:600;letter-spacing:.03em;white-space:nowrap;overflow:hidden;
   text-overflow:ellipsis;max-width:38vw}
 header a{color:var(--accent);text-decoration:none;font-size:12.5px;border:1px solid var(--line);
   border-radius:6px;padding:5px 10px;white-space:nowrap}
 .pgnav{display:flex;gap:6px;align-items:center}
 .pgnav button{background:var(--panel2);color:var(--txt);border:1px solid var(--line);
   border-radius:6px;padding:5px 12px;cursor:pointer}
 .pgnav .of{color:var(--dim);font-size:12px;white-space:nowrap}
 #q{margin-left:auto;background:var(--panel2);border:1px solid var(--line);color:var(--txt);
   border-radius:6px;padding:6px 12px;font-size:13px;width:230px}
 #app{display:flex;flex:1;min-height:0}
 nav#sheets{width:250px;background:var(--panel);border-right:1px solid var(--line);
   overflow-y:auto;padding:6px 0 30px}
 #sheets .blk{padding:10px 14px 4px;font-size:10.5px;letter-spacing:.12em;color:var(--dim);
   text-transform:uppercase}
 #sheets .dg{padding:7px 14px;font-size:12.5px;cursor:pointer;display:flex;
   justify-content:space-between;gap:8px;align-items:baseline}
 #sheets .dg:hover{background:var(--panel2)}
 #sheets .dg.active{background:var(--panel2);color:var(--accent);border-left:3px solid var(--accent);
   padding-left:11px}
 #sheets .dg .meta{color:var(--dim);font-size:10.5px;white-space:nowrap}
 #sheets .sh{padding:5px 14px 5px 24px;font-size:11.8px;color:var(--dim);cursor:pointer;
   display:flex;justify-content:space-between;gap:6px}
 #sheets .sh:hover{color:var(--txt)}
 #sheets .sh.active{color:var(--accent)}
 #sheets .sh .kd{font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;
   border:1px solid var(--line);border-radius:4px;padding:0 5px;white-space:nowrap}
 #sheets .sh .kd.master{border-color:var(--accent);color:var(--accent)}
 #viewer{flex:1;position:relative;overflow:hidden;background:#14161b;cursor:grab}
 #viewer.dragging{cursor:grabbing}
 #stage{position:absolute;top:0;left:0;transform-origin:0 0}
 #stage img{display:block;background:#fff;box-shadow:0 6px 30px rgba(0,0,0,.5)}
 #ovl{position:absolute;top:0;left:0;overflow:visible}
 .zoomctl{position:absolute;right:14px;top:14px;display:flex;flex-direction:column;gap:6px;z-index:5}
 .zoomctl button{width:34px;height:34px;border-radius:6px;border:1px solid var(--line);
   background:var(--panel);color:var(--txt);font-size:16px;cursor:pointer}
 #layers{position:absolute;left:14px;bottom:14px;z-index:5;background:rgba(37,41,50,.94);
   border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:11.5px;
   color:var(--dim);min-width:210px}
 #layers .row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
 #layers .row:last-child{margin-bottom:0}
 #layers label{flex:1;color:var(--txt);font-size:11.5px}
 #layers input[type=range]{width:88px;accent-color:var(--accent)}
 #layers .hint{color:var(--dim);font-size:10.5px;line-height:1.45;margin-top:6px;
   border-top:1px solid var(--line);padding-top:6px}
 aside{width:340px;background:var(--panel);border-left:1px solid var(--line);display:flex;
   flex-direction:column;min-height:0}
 .tabs{display:flex;border-bottom:1px solid var(--line);padding:0 4px}
 .tab{flex:1;background:none;border:0;border-bottom:2px solid transparent;color:var(--dim);
   padding:9px 2px;cursor:pointer;font-size:11.5px;letter-spacing:.03em}
 .tab.on{color:var(--accent);border-bottom-color:var(--accent)}
 #panel{flex:1;overflow-y:auto;padding:0 0 40px}
 .sec{padding:13px 16px;border-bottom:1px solid var(--line)}
 .sec h3{font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
   margin-bottom:8px;font-weight:600}
 .sec p{font-size:12.8px;color:var(--dim);line-height:1.6}
 table.kv{width:100%;border-collapse:collapse;font-size:12.5px}
 table.kv td{padding:4px 0;vertical-align:top;color:var(--txt)}
 table.kv td:first-child{width:104px;color:var(--dim);padding-right:10px}
 table.ctab{width:100%;border-collapse:collapse;font-size:12.5px}
 table.ctab td{padding:5px 6px;border-bottom:1px solid var(--line)}
 td.cit{color:var(--dim);font-style:italic;width:78px}
 .sw{display:inline-flex;align-items:center;justify-content:center;min-width:34px;height:23px;
   border-radius:5px;font-size:11px;font-weight:700;font-family:ui-monospace,monospace;
   border:1px solid rgba(255,255,255,.18);letter-spacing:.03em}
 .sw-unknown{background:repeating-linear-gradient(45deg,#2a323d 0 5px,#222932 5px 10px);color:var(--dim)}
 .note{font-size:12.2px;color:var(--dim);line-height:1.55;padding:8px 10px;background:#20242c;
   border-left:2px solid var(--line);border-radius:0 6px 6px 0;margin-bottom:6px}
 .note.warn{border-left-color:var(--accent)}
 .fusegrid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}
 .fuse{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px 4px;
   color:var(--txt);position:relative;overflow:hidden;text-align:center}
 .fuse:before{content:"";position:absolute;inset:0 0 auto 0;height:3px}
 .fuse.f-v:before{background:var(--ok)}.fuse.f-t:before{background:var(--accent)}
 .fuse.f-u:before{background:#4b5462}
 .fuse .fl{font-size:18px;font-weight:700;font-family:ui-monospace,monospace}
 .fuse .fa{font-size:10.5px;color:var(--dim);margin-top:2px}
 .hit{padding:8px 16px;border-bottom:1px solid #2e3340;font-size:12.5px;cursor:pointer}
 .hit:hover{background:var(--panel2)}
 .hit .pno{color:var(--accent);font-weight:600}
 .hit .snip{color:var(--dim);font-size:11.5px;margin-top:2px}
 .hit .snip b{color:var(--accent2);font-weight:600}
 .none{padding:14px 16px;color:var(--dim);font-size:12.5px;line-height:1.6}
 .badge{display:inline-block;font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;
   padding:2px 7px;border-radius:20px;font-weight:700}
 .b-pilot{background:rgba(232,184,75,.16);color:var(--accent)}
 .b-verified{background:rgba(143,201,143,.16);color:var(--ok)}
 .b-typical{background:rgba(232,184,75,.16);color:var(--accent)}
 .b-unknown{background:rgba(120,132,148,.18);color:var(--dim)}
 .credit{padding:10px 16px;font-size:11px;color:var(--dim);border-top:1px solid var(--line)}
 .credit a{color:var(--accent2)}
 /* overlay elements — phase 2 fills these in */
 .wire-hit{fill:none;stroke:transparent;stroke-width:18;cursor:pointer}
 .wire-line{fill:none;stroke-linejoin:round;stroke-linecap:round;pointer-events:none}
 .wire.dim{opacity:.12}
 .wire.sel .wire-line{stroke-width:7}
 .comp rect{fill:rgba(232,184,75,.08);stroke:var(--accent);stroke-width:2;cursor:pointer}
 .comp.dim{opacity:.12}
 .comp.sel rect{fill:rgba(232,184,75,.24);stroke-width:3.5}
</style></head><body>
<header>
  <a href="library.html">← Library</a><a href="index.html">Parts viewer</a>
  <h1 id="title">…</h1>
  <div class="pgnav">
    <button id="prev">‹</button>
    <span class="of" id="of">sheet ? / ?</span>
    <button id="next">›</button>
  </div>
  <input id="q" type="search" placeholder="Search text on these sheets…" autocomplete="off">
</header>
<div id="app">
  <nav id="sheets"></nav>
  <div id="viewer">
    <div class="zoomctl"><button id="z-in">+</button><button id="z-out">−</button>
      <button id="z-fit" style="font-size:12px">fit</button></div>
    <div id="stage"><img id="base" alt=""><svg id="ovl"></svg></div>
    <div id="layers">
      <div class="row"><label for="baseop">Factory scan</label>
        <input id="baseop" type="range" min="0" max="100" value="100"></div>
      <div class="row"><label for="ovlop">Traced overlay</label>
        <input id="ovlop" type="range" min="0" max="100" value="100"></div>
      <div class="hint" id="ovlhint"></div>
    </div>
  </div>
  <aside>
    <div class="tabs">
      <button class="tab on" data-tab="sheet">Sheet</button>
      <button class="tab" data-tab="circuits">Circuits</button>
      <button class="tab" data-tab="colours">Colours</button>
      <button class="tab" data-tab="fuses">Fuses</button>
      <button class="tab" data-tab="search">Search</button>
    </div>
    <div id="panel"></div>
  </aside>
</div>
<script src="wiring_index.js"></script>
<script src="wiring_ref.js"></script>
<script>
const params=new URLSearchParams(location.search);
const IDX=window.WIRING_INDEX||[];
const pilot=IDX.find(d=>d.pilot)||IDX[0]||{};
let slug=params.get('d')||pilot.slug;
let dg=null,cur=0,tab='sheet',view={x:0,y:0,s:1},sel=null;
const stage=document.getElementById('stage'),viewer=document.getElementById('viewer'),
      base=document.getElementById('base'),ovl=document.getElementById('ovl'),
      panel=document.getElementById('panel');

function load(s,sheetNo){
  slug=s;
  if(window.WIRINGDATA&&window.WIRINGDATA[s]){init(sheetNo);return;}
  const el=document.createElement('script');
  el.src='wiringdata/'+s+'.js';el.onload=()=>init(sheetNo);document.head.appendChild(el);
}
function init(sheetNo){
  dg=window.WIRINGDATA[slug];
  document.getElementById('title').textContent=dg.title;
  document.title=dg.title+' — Fiat Archive';
  buildNav();
  let i=0;
  if(sheetNo){const k=dg.sheets.findIndex(s=>s.n===+sheetNo);if(k>=0)i=k;}
  else {const k=dg.sheets.findIndex(s=>s.kind==='master');if(k>=0)i=k;}
  show(i);
  renderPanel();
}
function buildNav(){
  const nav=document.getElementById('sheets');nav.innerHTML='';
  const b=document.createElement('div');b.className='blk';b.textContent='Wiring diagrams';
  nav.appendChild(b);
  IDX.forEach(d=>{
    const row=document.createElement('div');
    row.className='dg'+(d.slug===slug?' active':'');
    const yrs=d.years[0]===d.years[1]?d.years[0]:d.years[0]+'–'+d.years[1];
    row.innerHTML=`<span>${d.title.replace(/^Wiring diagram — /,'')}`+
      (d.pilot?' <span class="badge b-pilot">pilot</span>':'')+`</span>`+
      `<span class="meta">${d.nsheets} sh</span>`;
    row.title=yrs+' · '+(d.market||'')+' · '+d.nmaster+' fold-out sheet(s)';
    row.onclick=()=>{if(d.slug!==slug)load(d.slug);};
    nav.appendChild(row);
    if(d.slug===slug&&dg){
      dg.sheets.forEach((s,i)=>{
        const e=document.createElement('div');
        e.className='sh'+(i===cur?' active':'');
        e.innerHTML=`<span>${s.label||('Sheet '+s.n)}</span>`+
          (s.kind==='master'?'<span class="kd master">fold-out</span>':'');
        e.onclick=()=>show(i);
        nav.appendChild(e);
      });
    }
  });
}
function show(i){
  if(!dg)return;
  cur=Math.max(0,Math.min(dg.sheets.length-1,i));
  const s=dg.sheets[cur];
  document.getElementById('of').textContent=`sheet ${cur+1} / ${dg.sheets.length}`;
  base.src=s.img;base.width=s.w;base.height=s.h;
  ovl.setAttribute('width',s.w);ovl.setAttribute('height',s.h);
  ovl.setAttribute('viewBox',`0 0 ${s.w} ${s.h}`);
  sel=null;
  drawOverlay();
  fit();
  buildNav();
  if(tab==='sheet')renderPanel();
  history.replaceState(null,'','?d='+slug+'&s='+s.n);
}
/* ---- overlay (empty until phase 2 tracing lands in fiat.db) ---- */
function colourHex(code){
  if(!code||code==='?')return '#7f8896';
  const c=(window.WIRE_COLOURS||{})[code[0]];return c?c.hex:'#7f8896';
}
function drawOverlay(){
  const s=dg.sheets[cur];
  ovl.innerHTML='';
  const wires=(dg.wires||[]).filter(w=>w.s===s.n);
  const comps=(dg.components||[]).filter(c=>c.s===s.n);
  wires.forEach((w,i)=>{
    (w.path||[]).forEach(seg=>{
      if(!seg||seg.length<2)return;
      const d='M'+seg.map(p=>`${(p[0]*s.w).toFixed(1)},${(p[1]*s.h).toFixed(1)}`).join('L');
      const g=document.createElementNS('http://www.w3.org/2000/svg','g');
      g.setAttribute('class','wire');g.dataset.i=i;
      const hit=document.createElementNS('http://www.w3.org/2000/svg','path');
      hit.setAttribute('d',d);hit.setAttribute('class','wire-hit');
      const ln=document.createElementNS('http://www.w3.org/2000/svg','path');
      ln.setAttribute('d',d);ln.setAttribute('class','wire-line');
      ln.setAttribute('stroke',colourHex(w.col));
      ln.setAttribute('stroke-width',w.gauge==='heavy'?7:w.gauge==='med'?5:3.5);
      g.appendChild(hit);g.appendChild(ln);
      g.onclick=e=>{e.stopPropagation();sel={kind:'wire',data:w};tab='sheet';renderPanel();};
      ovl.appendChild(g);
    });
  });
  comps.forEach(c=>{
    if(c.x==null)return;
    const g=document.createElementNS('http://www.w3.org/2000/svg','g');
    g.setAttribute('class','comp');
    const r=document.createElementNS('http://www.w3.org/2000/svg','rect');
    r.setAttribute('x',c.x*s.w);r.setAttribute('y',c.y*s.h);
    r.setAttribute('width',(c.w||0.02)*s.w);r.setAttribute('height',(c.h||0.02)*s.h);
    r.setAttribute('rx',4);
    g.appendChild(r);
    g.onclick=e=>{e.stopPropagation();sel={kind:'comp',data:c};tab='sheet';renderPanel();};
    ovl.appendChild(g);
  });
  const n=wires.length+comps.length;
  document.getElementById('ovlhint').textContent = n
    ? `${comps.length} components, ${wires.length} wires traced on this sheet.`
    : 'Nothing traced on this sheet yet — the overlay layer arrives in phase 2.';
  ovl.style.display=n?'block':'none';
}
/* ---- pan / zoom ---- */
function apply(){stage.style.transform=`translate(${view.x}px,${view.y}px) scale(${view.s})`;}
function fit(){const s=dg.sheets[cur],r=viewer.getBoundingClientRect();
  view.s=Math.min(r.width/s.w,r.height/s.h)*.97;
  view.x=(r.width-s.w*view.s)/2;view.y=(r.height-s.h*view.s)/2;apply();}
viewer.addEventListener('wheel',e=>{e.preventDefault();
  const r=viewer.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=e.deltaY<0?1.18:1/1.18,s2=Math.min(14,Math.max(.03,view.s*f));
  view.x=mx-(mx-view.x)*(s2/view.s);view.y=my-(my-view.y)*(s2/view.s);view.s=s2;apply();
},{passive:false});
let drag=null;
viewer.addEventListener('mousedown',e=>{
  if(e.target.closest('.zoomctl')||e.target.closest('#layers'))return;
  drag={mx:e.clientX,my:e.clientY,x:view.x,y:view.y};viewer.classList.add('dragging');});
window.addEventListener('mousemove',e=>{if(!drag)return;
  view.x=drag.x+(e.clientX-drag.mx);view.y=drag.y+(e.clientY-drag.my);apply();});
window.addEventListener('mouseup',()=>{drag=null;viewer.classList.remove('dragging');});
document.getElementById('z-in').onclick=()=>{view.s=Math.min(14,view.s*1.35);apply();};
document.getElementById('z-out').onclick=()=>{view.s=Math.max(.03,view.s/1.35);apply();};
document.getElementById('z-fit').onclick=fit;
window.addEventListener('resize',()=>{if(dg)fit();});
document.getElementById('prev').onclick=()=>show(cur-1);
document.getElementById('next').onclick=()=>show(cur+1);
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT')return;
  if(e.key==='ArrowLeft')show(cur-1);
  if(e.key==='ArrowRight')show(cur+1);});
document.getElementById('baseop').oninput=e=>{base.style.opacity=e.target.value/100;};
document.getElementById('ovlop').oninput=e=>{ovl.style.opacity=e.target.value/100;};
/* ---- side panel ---- */
function esc(t){return (t||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function swatch(code){
  const C=window.WIRE_COLOURS||{};
  if(!code||code==='?')return '<span class="sw sw-unknown">?</span>';
  const b=C[code[0]],t=code[1]?C[code[1]]:null;
  if(!b)return '<span class="sw sw-unknown">'+esc(code)+'</span>';
  const bg=t?`background:${b.hex};background-image:repeating-linear-gradient(115deg,transparent 0 5px,${t.hex} 5px 9px)`
            :`background:${b.hex}`;
  return `<span class="sw" style="${bg};color:${b.ink}" title="${esc(colourName(code))}">${esc(code)}</span>`;
}
function colourName(code){
  const C=window.WIRE_COLOURS||{};
  if(!code||code==='?')return 'Unknown';
  const b=C[code[0]],t=code[1]?C[code[1]]:null;
  if(!b)return code;
  return t?`${b.en} with ${t.en.toLowerCase()} tracer (${b.it}/${t.it})`:`${b.en} (${b.it})`;
}
function renderPanel(){
  if(!dg){panel.innerHTML='';return;}
  if(tab==='sheet')return renderSheet();
  if(tab==='circuits')return renderCircuits();
  if(tab==='colours')return renderColours();
  if(tab==='fuses')return renderFuses();
  if(tab==='search')return runSearch();
}
function renderSheet(){
  const s=dg.sheets[cur];
  if(sel&&sel.kind==='wire'){
    const w=sel.data;
    panel.innerHTML=`<div class="sec"><h3>Wire</h3>
      <p>${swatch(w.col)} &nbsp; ${esc(colourName(w.col))}</p></div>
      <div class="sec"><table class="kv">
      <tr><td>Function</td><td>${esc(w.label)||'—'}</td></tr>
      <tr><td>Gauge</td><td>${esc(w.gauge)||'—'}</td></tr>
      <tr><td>From</td><td>${esc(w.from)||'—'} ${esc(w.fpin)||''}</td></tr>
      <tr><td>To</td><td>${esc(w.to)||'—'} ${esc(w.tpin)||''}</td></tr>
      <tr><td>Confidence</td><td>${esc(w.conf)}</td></tr></table></div>
      <div class="sec"><p><a href="#" id="clr">← back to sheet details</a></p></div>`;
    document.getElementById('clr').onclick=e=>{e.preventDefault();sel=null;renderPanel();};
    return;
  }
  if(sel&&sel.kind==='comp'){
    const c=sel.data;
    panel.innerHTML=`<div class="sec"><h3>Component ${esc(c.code)}</h3>
      <p>${esc(c.en||c.name||'')}</p></div>
      <div class="sec"><table class="kv">
      <tr><td>On the car</td><td>${esc(c.loc)||'—'}</td></tr>
      <tr><td>Part no.</td><td>${esc(c.pn)||'—'}</td></tr>
      <tr><td>Confidence</td><td>${esc(c.conf)}</td></tr></table></div>
      ${c.notes?`<div class="sec"><h3>Notes</h3><p class="note">${esc(c.notes)}</p></div>`:''}
      <div class="sec"><p><a href="#" id="clr">← back to sheet details</a></p></div>`;
    document.getElementById('clr').onclick=e=>{e.preventDefault();sel=null;renderPanel();};
    return;
  }
  const yrs=dg.years[0]===dg.years[1]?dg.years[0]:dg.years[0]+'–'+dg.years[1];
  panel.innerHTML=`
    <div class="sec"><h3>Diagram</h3><table class="kv">
      <tr><td>Years</td><td>${yrs}</td></tr>
      <tr><td>Market</td><td>${esc(dg.market)||'—'}</td></tr>
      <tr><td>Sheets</td><td>${dg.sheets.length}</td></tr>
    </table>${dg.variant?`<p class="note" style="margin-top:8px">${esc(dg.variant)}</p>`:''}</div>
    <div class="sec"><h3>This sheet</h3><table class="kv">
      <tr><td>Label</td><td>${esc(s.label)||'—'}</td></tr>
      <tr><td>Type</td><td>${s.kind==='master'?'Fold-out schematic':'Page'}</td></tr>
      <tr><td>Image</td><td>${s.w} × ${s.h} px</td></tr>
      <tr><td>Original</td><td>${s.nw} × ${s.nh} px in the PDF</td></tr>
    </table></div>
    <div class="sec"><h3>Overlay</h3><p>${
      (dg.wires||[]).length
        ? (dg.wires||[]).length+' wires traced on this diagram.'
        : 'No wires traced yet. Phase 1 publishes the scan itself; the traced, '+
          'clickable overlay is built on top of these exact images in phase 2, '+
          'so nothing here gets thrown away.'}</p></div>`;
}
function renderCircuits(){
  const cs=dg.circuits||[];
  if(!cs.length){
    panel.innerHTML='<div class="none">No circuit notes recorded for this diagram yet. '+
      'The 1978 Australian sheet carries the seeded set — pick it in the list on the left.</div>';
    return;}
  let h='',lastG=null;
  cs.forEach((c,i)=>{
    if(c.grp!==lastG){lastG=c.grp;h+=`<div class="sec" style="padding-bottom:2px">`+
      `<h3 style="margin:0">${esc(c.grp)}</h3></div>`;}
    h+=`<div class="sec"><div style="display:flex;justify-content:space-between;gap:8px;`+
       `align-items:baseline;cursor:pointer" data-c="${i}">`+
       `<b style="font-size:13px">${esc(c.name)}</b>`+
       `<span class="badge b-${esc(c.conf)}">${esc(c.conf)}</span></div>`+
       `<div class="cbody" id="cb${i}" style="display:none;margin-top:8px">`+
       `<p>${esc(c.desc)}</p>`+
       (c.symptoms.length?'<h3 style="margin-top:10px">Symptoms → likely cause</h3>'+
         c.symptoms.map(s=>`<p class="note">${esc(s)}</p>`).join(''):'')+
       (c.tests.length?'<h3 style="margin-top:10px">How to test</h3>'+
         c.tests.map(t=>`<p class="note warn">${esc(t)}</p>`).join(''):'')+
       `</div></div>`;
  });
  panel.innerHTML=h;
  panel.querySelectorAll('[data-c]').forEach(e=>{
    e.onclick=()=>{const b=document.getElementById('cb'+e.dataset.c);
      b.style.display=b.style.display==='none'?'block':'none';};});
}
function renderColours(){
  const C=window.WIRE_COLOURS||{};
  let h='<div class="sec"><h3>Fiat / Italian colour codes</h3><table class="ctab">';
  Object.keys(C).forEach(k=>{h+=`<tr><td>${swatch(k)}</td><td class="cit">${esc(C[k].it)}</td>`+
    `<td>${esc(C[k].en)}</td></tr>`;});
  h+='</table></div><div class="sec"><h3>Read these carefully</h3>';
  (window.WIRE_GOTCHAS||[]).forEach(t=>{h+=`<p class="note warn">${esc(t)}</p>`;});
  h+='</div><div class="sec"><h3>Confirmed on the 1978 Australian car</h3>';
  (window.WIRE_KNOWN_COLOURS||[]).forEach(k=>{
    h+=`<p class="note">${swatch(k.code)} <b>${esc(k.circuit)}</b> — ${esc(k.desc)}</p>`;});
  panel.innerHTML=h+'</div>';
}
function renderFuses(){
  const series1=(dg.years[0]||0)<1982;
  let h='';
  if(!series1) h+='<div class="sec"><p class="note warn">This diagram is a Bertone-era '+
    'car, which uses a NUMBERED blade fuse panel. The lettered A–N panel below belongs '+
    'to the Series 1 cars (1974–1982) and does not apply here — read the fuse layout off '+
    'this diagram\'s own fuse-panel sheet.</p></div>';
  h+='<div class="sec"><h3>Series 1 fuse panel (A–N)</h3><div class="fusegrid">';
  (window.WIRE_FUSES||[]).forEach(f=>{
    h+=`<div class="fuse f-${f.conf}" title="${esc(f.feeds)}"><div class="fl">${esc(f.id)}</div>`+
       `<div class="fa">${esc(f.amps)}</div></div>`;});
  h+='</div></div><div class="sec">';
  (window.WIRE_FUSE_NOTES||[]).forEach(t=>{h+=`<p class="note warn">${esc(t)}</p>`;});
  panel.innerHTML=h+'</div>';
}
function runSearch(){
  const term=(document.getElementById('q').value||'').trim().toLowerCase();
  if(term.length<3){
    panel.innerHTML='<div class="none">Type at least 3 characters in the search box. '+
      'Searches the OCR text of every sheet in this diagram — legend pages read well, '+
      'fold-out schematics much less so.</div>';return;}
  const out=[];
  dg.sheets.forEach((s,i)=>{
    const t=(s.txt||'').toLowerCase(),k=t.indexOf(term);
    if(k>=0){
      const raw=s.txt.substring(Math.max(0,k-60),k+term.length+60).replace(/\s+/g,' ');
      out.push({i,n:s.n,snip:esc(raw).replace(
        new RegExp('('+term.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig'),'<b>$1</b>')});
    }});
  panel.innerHTML=out.length
    ?out.map(h=>`<div class="hit" data-i="${h.i}"><span class="pno">sheet ${h.n}</span>`+
      `<div class="snip">…${h.snip}…</div></div>`).join('')
    :'<div class="none">No sheets match. OCR on a wiring sheet is rough — try a shorter word.</div>';
  panel.querySelectorAll('.hit').forEach(e=>{e.onclick=()=>{show(+e.dataset.i);};});
}
document.querySelectorAll('.tab').forEach(t=>{
  t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
    t.classList.add('on');tab=t.dataset.tab;renderPanel();};});
let deb=null;
document.getElementById('q').addEventListener('input',()=>{
  clearTimeout(deb);deb=setTimeout(()=>{
    tab='search';
    document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x.dataset.tab==='search'));
    renderPanel();},250);});
viewer.addEventListener('click',e=>{
  if(e.target===viewer||e.target===base){sel=null;if(tab==='sheet')renderPanel();}});
if(slug)load(slug,params.get('s'));
else document.getElementById('title').textContent='No wiring diagrams ingested yet';
</script></body></html>"""


if __name__ == "__main__":
    main()
