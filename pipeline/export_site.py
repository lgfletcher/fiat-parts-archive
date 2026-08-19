#!/usr/bin/env python3
"""
Stage 6: export the static browsable site from fiat.db.

    python3 pipeline/export_site.py --db fiat.db \
        --pages archive/derived/factory_catalog/pages --out site_build

Output is self-contained: index.html + data.js + plates/*.jpg.
Works from file:// (no fetch), any static host, or a zip.
"""
import argparse, json, sqlite3
from pathlib import Path
from PIL import Image

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="fiat.db")
    ap.add_argument("--pages", required=True)
    ap.add_argument("--out", default="site_build")
    ap.add_argument("--jpeg-quality", type=int, default=80)
    args = ap.parse_args()

    out = Path(args.out); (out / "plates").mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.db); db.row_factory = sqlite3.Row

    cats, plates = {}, {}
    has_en = any(r[1] == "title_en" for r in db.execute("PRAGMA table_info(plate)"))
    en_col = "pl.title_en" if has_en else "NULL AS title_en"
    for r in db.execute(f"""
        SELECT pl.id, pl.tav_code, pl.title, {en_col}, pl.width_px, pl.height_px, pl.dzi_path,
               c.slug AS cslug, c.name AS cname, c.gruppo_code
        FROM plate pl LEFT JOIN category c ON c.id = pl.category_id
        ORDER BY pl.tav_code"""):
        src = Path(args.pages) / Path(r["dzi_path"]).name
        jpg = f"plates/{Path(r['dzi_path']).stem}.jpg"
        if src.exists() and not (out / jpg).exists():
            Image.open(src).convert("L").save(out / jpg, quality=args.jpeg_quality, optimize=True)
        cslug = r["cslug"] or "other"
        cats.setdefault(cslug, {"slug": cslug,
                                "name": r["cname"] or f"Gruppo {r['tav_code'][:2]}",
                                "gruppo": r["gruppo_code"] or r["tav_code"][:2],
                                "plates": []})
        cats[cslug]["plates"].append(r["tav_code"])
        try:
            hs_rows = db.execute(
                "SELECT callout,x,y,r,w,h,verified FROM hotspot WHERE plate_id=?", (r["id"],)).fetchall()
        except sqlite3.OperationalError:   # pre-edit-era DB without w/h columns
            hs_rows = [dict(row) | {"w": None, "h": None, "verified": 0} for row in
                       db.execute("SELECT callout,x,y,r,0 AS verified FROM hotspot WHERE plate_id=?", (r["id"],))]
        parts = [{"pn": h["callout"], "x": h["x"], "y": h["y"], "r": h["r"],
                  "w": h["w"], "hh": h["h"], "v": h["verified"] or 0,
                  "conf": None} for h in hs_rows]
        confs = {u["callout"]: u["applicability"] for u in
                 db.execute("SELECT callout,applicability FROM part_usage WHERE plate_id=?", (r["id"],))}
        for p in parts:
            a = confs.get(p["pn"], "")
            if a and a.startswith("ocr_conf="):
                p["conf"] = float(a.split("=")[1])
        plates[r["tav_code"]] = {"tav": r["tav_code"], "title": r["title"],
                                 "title_en": r["title_en"],
                                 "img": jpg, "w": r["width_px"], "h": r["height_px"],
                                 "cat": cslug, "parts": parts}

    n_parts = db.execute("SELECT COUNT(*) FROM part").fetchone()[0]
    n_usage = db.execute("SELECT COUNT(*) FROM part_usage").fetchone()[0]
    shared = [dict(r) for r in db.execute(
        "SELECT part_no, n_vehicles, vehicles FROM v_shared_parts LIMIT 50")]
    multi = [dict(r) for r in db.execute("""
        SELECT p.part_no, COUNT(DISTINCT pu.plate_id) AS n
        FROM part p JOIN part_usage pu ON pu.part_id=p.id
        GROUP BY p.id HAVING n>1 ORDER BY n DESC LIMIT 200""")]

    data = {"categories": sorted(cats.values(), key=lambda c: c["gruppo"] or "99"),
            "plates": plates,
            "stats": {"plates": len(plates), "parts": n_parts, "usages": n_usage,
                      "multi_plate_parts": len(multi)},
            "generated": "by pipeline/export_site.py — all OCR data UNVERIFIED"}
    (out / "data.js").write_text("window.ARCHIVE=" + json.dumps(data) + ";")

    (out / "index.html").write_text(TEMPLATE)
    print("exported", len(plates), "plates →", out)

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fiat Classic Parts Archive — X1/9 Factory Catalog (v3)</title>
<style>
  :root{--bg:#1c1f26;--panel:#252932;--panel2:#2c313c;--line:#3a4150;--txt:#e8e6df;
    --dim:#9aa0ac;--accent:#e8b84b;--accent2:#7fb4d8;--ok:#8fc98f;--warn:#d89a7f;}
  *{box-sizing:border-box;margin:0;padding:0}html,body{height:100%}
  body{font-family:"Avenir Next","Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--txt);display:flex;flex-direction:column;overflow:hidden}
  header{display:flex;align-items:center;gap:16px;padding:10px 18px;background:var(--panel);border-bottom:1px solid var(--line);flex-wrap:wrap}
  h1{font-size:15px;font-weight:600;letter-spacing:.04em}
  h1 .v{color:var(--accent);font-size:11px;border:1px solid var(--accent);border-radius:4px;padding:1px 6px;margin-left:8px}
  #search{margin-left:auto;background:var(--panel2);border:1px solid var(--line);color:var(--txt);border-radius:6px;padding:6px 12px;font-size:13px;width:260px}
  #app{display:flex;flex:1;min-height:0}
  nav{width:250px;background:var(--panel);border-right:1px solid var(--line);overflow-y:auto;padding:8px 0}
  .cat{padding:8px 14px 4px;font-size:11px;letter-spacing:.1em;color:var(--accent);cursor:pointer}
  .cat .n{color:var(--dim);font-size:10px;letter-spacing:0}
  .pl{padding:4px 14px 4px 22px;font-size:12px;color:var(--txt);cursor:pointer;display:flex;gap:8px;justify-content:space-between}
  .pl:hover{background:var(--panel2)}
  .pl.active{background:var(--panel2);color:var(--accent);border-left:3px solid var(--accent);padding-left:19px}
  .pl .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .pl .np{color:var(--dim);font-size:10px}
  #viewerwrap{flex:1;display:flex;flex-direction:column;min-width:0}
  #platebar{display:flex;align-items:baseline;gap:10px;padding:8px 14px;border-bottom:1px solid var(--line);background:var(--panel);flex-wrap:wrap}
  #platebar .tav{color:var(--accent);font-weight:600;font-size:13px}
  #platebar .ti{font-size:13px}
  #platebar .src{margin-left:auto;font-size:11px;color:var(--dim)}
  #viewer{flex:1;position:relative;overflow:hidden;background:#14161b;cursor:grab}
  #viewer.dragging{cursor:grabbing}
  #stage{position:absolute;top:0;left:0;transform-origin:0 0}
  #stage img{display:block;box-shadow:0 6px 30px rgba(0,0,0,.5)}
  .hs{position:absolute;border:2.5px solid transparent;border-radius:8px;cursor:pointer;transition:border-color .12s, background .12s}
  .hs:hover{border-color:rgba(232,150,50,.85);background:rgba(232,184,75,.12)}
  .hs.sel{border-color:#e87a2e;background:rgba(232,150,50,.22);box-shadow:0 0 0 4px rgba(232,122,46,.25)}
  .zoomctl{position:absolute;right:14px;top:14px;display:flex;flex-direction:column;gap:6px;z-index:5}
  .zoomctl button{width:34px;height:34px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--txt);font-size:16px;cursor:pointer}
  .hint{position:absolute;left:14px;bottom:12px;font-size:11px;color:var(--dim);background:rgba(28,31,38,.8);padding:4px 10px;border-radius:6px;z-index:5}
  aside{width:330px;background:var(--panel);border-left:1px solid var(--line);display:flex;flex-direction:column;min-height:0}
  aside .pt{padding:10px 14px 6px;font-size:11px;letter-spacing:.12em;color:var(--dim)}
  #parts{flex:1;overflow-y:auto}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{position:sticky;top:0;background:var(--panel2);text-align:left;padding:6px 10px;font-size:10.5px;color:var(--dim)}
  td{padding:6px 10px;border-bottom:1px solid #2e3340}
  tbody tr{cursor:pointer}
  tbody tr:hover{background:#2c313c}
  tbody tr.sel{background:#39383043;outline:1px solid var(--accent)}
  td.pn{font-family:ui-monospace,Menlo,monospace;color:var(--accent2)}
  td.cf{color:var(--dim);font-size:11px}
  td.cf.lo{color:var(--warn)}
  .also{display:inline-block;margin-left:6px;font-size:10px;color:#1c1f26;background:var(--accent2);border-radius:4px;padding:0 5px;cursor:pointer}
  footer{padding:6px 16px;background:var(--panel);border-top:1px solid var(--line);font-size:11px;color:var(--dim);display:flex;gap:16px;flex-wrap:wrap}
  footer b{color:var(--txt)}
  #results{position:absolute;top:52px;right:18px;width:460px;max-height:65vh;overflow-y:auto;background:var(--panel);border:1px solid var(--accent);border-radius:8px;z-index:20;display:none;box-shadow:0 10px 40px rgba(0,0,0,.6)}
  #results .r{padding:8px 14px;border-bottom:1px solid var(--line);cursor:pointer;font-size:12.5px}
  #results .r:hover{background:var(--panel2)}
  #results .pn{font-family:ui-monospace,monospace;color:var(--accent2)}
  #results .where{color:var(--dim);font-size:11px;margin-top:2px}
  #results .none{padding:12px 14px;color:var(--dim)}
  /* ---- edit mode ---- */
  .ebtn{background:var(--panel2);color:var(--dim);border:1px solid var(--line);border-radius:6px;padding:5px 12px;font-size:12.5px;cursor:pointer}
  .ebtn.on{background:var(--accent);color:#1c1f26;border-color:var(--accent);font-weight:600}
  .ebtn.warn{color:var(--warn)}
  body.editing .hs{border-color:rgba(127,180,216,.5)}
  body.editing .hs:hover{border-color:var(--accent2)}
  .hs.verified{border-color:rgba(143,201,143,.55)}
  .hs .grip{display:none;position:absolute;right:-7px;bottom:-7px;width:14px;height:14px;background:var(--accent);border-radius:3px;cursor:nwse-resize}
  body.editing .hs.sel .grip{display:block}
  #edpop{position:absolute;z-index:30;background:#101216;border:1px solid var(--accent);border-radius:8px;padding:10px;display:none;box-shadow:0 10px 40px rgba(0,0,0,.6);width:230px}
  #edpop input[type=text]{width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--accent2);font-family:ui-monospace,monospace;font-size:14px;padding:5px 8px;border-radius:5px}
  #edpop .row{display:flex;gap:8px;margin-top:8px;align-items:center;font-size:12px;color:var(--dim)}
  #edpop button{flex:1;padding:5px 0;border-radius:5px;border:1px solid var(--line);background:var(--panel2);color:var(--txt);cursor:pointer;font-size:12px}
  #edpop button.pri{background:var(--accent);color:#1c1f26;border-color:var(--accent);font-weight:600}
  #edpop button.del{color:var(--warn)}
  #addrect{position:absolute;border:2px dashed var(--accent);background:rgba(232,184,75,.12);display:none;pointer-events:none}
  .rotnote{position:absolute;top:14px;left:14px;z-index:6;background:rgba(216,154,127,.15);border:1px solid var(--warn);color:var(--warn);font-size:11.5px;padding:5px 10px;border-radius:6px;display:none}
</style>
</head>
<body>
<header>
  <h1>FIAT CLASSIC PARTS ARCHIVE<span class="v">v3.2</span></h1>
  <a href="library.html" class="ebtn" style="text-decoration:none">📚 Library</a>
  <button class="ebtn" id="ed-toggle" title="Toggle edit mode">✎ Edit</button>
  <button class="ebtn" id="ed-add" style="display:none" title="Drag a box on the drawing, then type the part number">＋ Add box</button>
  <button class="ebtn" id="ed-rot" style="display:none" title="Flag this page as rotated; fixed permanently at next rebuild">↻ Rotate</button>
  <button class="ebtn" id="ed-export" style="display:none" title="Download your edits as edits.json">⬇ Export <span id="ed-count">0</span> edits</button>
  <input id="search" type="search" placeholder="Search part number across all plates…" autocomplete="off">
</header>
<div id="app">
  <nav id="nav"></nav>
  <div id="viewerwrap">
    <div id="platebar">
      <span class="tav" id="pb-tav"></span><span class="ti" id="pb-title"></span>
      <span class="src" id="pb-src"></span>
    </div>
    <div id="viewer">
      <div class="zoomctl"><button id="z-in">+</button><button id="z-out">−</button><button id="z-fit" style="font-size:12px">fit</button></div>
      <div id="stage"></div>
      <div class="rotnote" id="rotnote"></div>
      <div id="edpop"></div>
      <div class="hint" id="hint">drag to pan · scroll to zoom · click part numbers on the drawing</div>
    </div>
  </div>
  <aside>
    <div class="pt">PART NUMBERS FOUND ON THIS PLATE (OCR)</div>
    <div id="parts"></div>
  </aside>
</div>
<div id="results"></div>
<footer id="foot"></footer>
<script src="data.js"></script>
<script>
const D=window.ARCHIVE, plates=D.plates;
const stage=document.getElementById('stage'), viewer=document.getElementById('viewer');
let cur=null, view={x:0,y:0,s:1};

/* ---------- local edits (browser-persistent, exportable) ---------- */
let ED={};
try{ED=JSON.parse(localStorage.getItem('fiat_edits')||'{}');}catch(e){ED={};}
function edFor(tav){return ED[tav]=ED[tav]||{rotate:0,hs:{}};}
function edSave(){localStorage.setItem('fiat_edits',JSON.stringify(ED));edCount();}
function edCount(){
  let n=0;Object.values(ED).forEach(e=>{n+=Object.keys(e.hs||{}).length+(e.rotate?1:0);});
  const el=document.getElementById('ed-count');if(el)el.textContent=n;
  return n;
}
/* working hotspot list for a plate = base OCR data + local edits */
function workingParts(p){
  const e=ED[p.tav]||{hs:{}};
  const out=[];
  p.parts.forEach((h,i)=>{
    const id='b'+i, ov=e.hs[id];
    if(ov&&ov.del)return;
    out.push(Object.assign({id, pn:h.pn, x:h.x, y:h.y,
      w:h.w||Math.max(h.r*2,0.05), h:h.hh||0.028, conf:h.conf, verified:!!h.v}, ov||{}));
  });
  Object.entries(e.hs).forEach(([id,ov])=>{
    if(id.startsWith('n')&&!ov.del) out.push(Object.assign({id,conf:null,verified:false},ov));
  });
  return out;
}

/* index: part -> plates (cross-links, derived; includes local edits) */
const where={};
function rebuildWhere(){
  Object.keys(where).forEach(k=>delete where[k]);
  Object.values(plates).forEach(p=>workingParts(p).forEach(h=>{(where[h.pn]=where[h.pn]||[]).push(p.tav);}));
}
rebuildWhere();

/* nav */
const nav=document.getElementById('nav');
D.categories.forEach(c=>{
  const h=document.createElement('div');h.className='cat';
  h.innerHTML=`${c.name} <span class="n">· Gr.${c.gruppo} · ${c.plates.length} plates</span>`;
  nav.appendChild(h);
  const box=document.createElement('div');
  c.plates.forEach(tv=>{
    const p=plates[tv]; if(!p) return;
    const d=document.createElement('div');d.className='pl';d.dataset.tav=tv;
    const nm=p.title_en||p.title;
    d.innerHTML=`<span class="t">${tv}${nm?' — '+nm.toLowerCase():''}</span><span class="np">${p.parts.length}</span>`;
    d.onclick=()=>load(tv);
    box.appendChild(d);
  });
  nav.appendChild(box);
  h.onclick=()=>{box.style.display=box.style.display==='none'?'':'none';};
});

function apply(){stage.style.transform=`translate(${view.x}px,${view.y}px) scale(${view.s})`;}
function fit(){if(!cur)return;const r=viewer.getBoundingClientRect();
  view.s=Math.min(r.width/cur.w,r.height/cur.h)*.97;
  view.x=(r.width-cur.w*view.s)/2;view.y=(r.height-cur.h*view.s)/2;apply();}
function zoomTo(px,py,s){const r=viewer.getBoundingClientRect();view.s=s;view.x=r.width/2-px*s;view.y=r.height/2-py*s;apply();}

let curParts=[];
function load(tav,selPn){
  cur=plates[tav]; if(!cur) return;
  closePop();
  document.querySelectorAll('.pl').forEach(e=>e.classList.toggle('active',e.dataset.tav===tav));
  document.getElementById('pb-tav').textContent='SGR. '+tav;
  document.getElementById('pb-title').innerHTML=(cur.title_en||cur.title||'')+
    (cur.title_en&&cur.title?` <span style="color:var(--dim);font-style:italic;font-size:12px">· ${cur.title}</span>`:'');
  document.getElementById('pb-src').textContent='Factory parts catalog · '+cur.img.replace('plates/','');
  stage.style.width=cur.w+'px';stage.style.height=cur.h+'px';
  const rot=(ED[tav]&&ED[tav].rotate)||0;
  stage.innerHTML=`<img src="${cur.img}" width="${cur.w}" height="${cur.h}" style="${rot?`transform:rotate(${rot}deg)`:''}">`;
  const rn=document.getElementById('rotnote');
  rn.style.display=rot?'block':'none';
  rn.textContent=rot?`Flagged for ${rot}° rotation — image and hotspots are fixed permanently at the next rebuild; hotspots hidden meanwhile.`:'';
  curParts=workingParts(cur);
  if(!rot) curParts.forEach(h=>stage.appendChild(mkHs(h)));
  buildTable(tav);
  fit();
  if(selPn) setTimeout(()=>select(selPn,true),60);
}
function mkHs(h){
  const d=document.createElement('div');
  d.className='hs'+(h.verified?' verified':'');
  d.dataset.id=h.id; d.dataset.pn=h.pn;
  const w=Math.max(h.w*cur.w,90), ht=Math.max(h.h*cur.h,34);
  d.style.cssText=`left:${h.x*cur.w-w/2}px;top:${h.y*cur.h-ht/2}px;width:${w}px;height:${ht}px`;
  d.innerHTML='<div class="grip"></div>';
  d.onclick=(e)=>{ if(editing){select(h.pn,false,h.id);openPop(h.id);} else select(h.pn,false,h.id); };
  return d;
}
function buildTable(tav){
  const tbl=document.createElement('table');
  tbl.innerHTML='<thead><tr><th>PART NO.</th><th>ALSO ON</th><th>OCR CONF</th></tr></thead>';
  const tb=document.createElement('tbody');
  curParts.slice().sort((a,b)=>a.pn<b.pn?-1:1).forEach(h=>{
    const tr=document.createElement('tr');tr.dataset.pn=h.pn;tr.dataset.id=h.id;
    const others=(where[h.pn]||[]).filter(t=>t!==tav);
    const tag=h.id.startsWith('n')?'<span class="also" style="background:var(--ok)">added</span>'
             :h.verified?'<span class="also" style="background:var(--ok)">✓</span>':'';
    tr.innerHTML=`<td class="pn">${h.pn} ${tag}</td>
      <td>${others.slice(0,3).map(t=>`<span class="also" data-t="${t}">${t}</span>`).join('')}${others.length>3?'…':''}</td>
      <td class="cf ${h.conf&&h.conf<55?'lo':''}">${h.conf?Math.round(h.conf)+'%':''}</td>`;
    tr.onclick=e=>{
      const a=e.target.closest('.also[data-t]');
      if(a){load(a.dataset.t,h.pn);return;}
      select(h.pn,true,h.id);
      if(editing)openPop(h.id);
    };
    tb.appendChild(tr);
  });
  tbl.appendChild(tb);
  const pp=document.getElementById('parts');pp.innerHTML='';pp.appendChild(tbl);
}
function select(pn,zoom,id){
  document.querySelectorAll('.hs').forEach(h=>h.classList.toggle('sel',id?h.dataset.id===id:h.dataset.pn===pn));
  document.querySelectorAll('tbody tr').forEach(tr=>{
    const on=id?tr.dataset.id===id:tr.dataset.pn===pn;tr.classList.toggle('sel',on);
    if(on)tr.scrollIntoView({block:'nearest',behavior:'smooth'});
  });
  const h=curParts.find(x=>id?x.id===id:x.pn===pn);
  if(zoom&&h)zoomTo(h.x*cur.w,h.y*cur.h,Math.max(view.s,1.0));
}

/* pan/zoom */
viewer.addEventListener('wheel',e=>{e.preventDefault();
  const r=viewer.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=e.deltaY<0?1.18:1/1.18,s2=Math.min(6,Math.max(.06,view.s*f));
  view.x=mx-(mx-view.x)*(s2/view.s);view.y=my-(my-view.y)*(s2/view.s);view.s=s2;apply();
},{passive:false});
let drag=null;
viewer.addEventListener('mousedown',e=>{if(e.target.closest('.zoomctl'))return;
  drag={mx:e.clientX,my:e.clientY,x:view.x,y:view.y};viewer.classList.add('dragging');});
window.addEventListener('mousemove',e=>{if(!drag)return;
  view.x=drag.x+(e.clientX-drag.mx);view.y=drag.y+(e.clientY-drag.my);apply();});
window.addEventListener('mouseup',()=>{drag=null;viewer.classList.remove('dragging');});
document.getElementById('z-in').onclick=()=>{const r=viewer.getBoundingClientRect();zoomTo((r.width/2-view.x)/view.s,(r.height/2-view.y)/view.s,Math.min(6,view.s*1.35));};
document.getElementById('z-out').onclick=()=>{const r=viewer.getBoundingClientRect();zoomTo((r.width/2-view.x)/view.s,(r.height/2-view.y)/view.s,Math.max(.06,view.s/1.35));};
document.getElementById('z-fit').onclick=fit;
window.addEventListener('resize',fit);

/* search */
const searchEl=document.getElementById('search'),resultsEl=document.getElementById('results');
searchEl.addEventListener('input',()=>{
  const q=searchEl.value.trim();
  if(q.length<3){resultsEl.style.display='none';return;}
  const hits=Object.keys(where).filter(pn=>pn.includes(q)).slice(0,40);
  resultsEl.innerHTML=hits.length
    ?hits.map(pn=>`<div class="r" data-pn="${pn}" data-t="${where[pn][0]}">
        <span class="pn">${pn}</span>
        <div class="where">on ${where[pn].length} plate(s): ${where[pn].slice(0,6).join(', ')}${where[pn].length>6?'…':''}</div></div>`).join('')
    :'<div class="none">No part number matching. (OCR-only data — verification pending.)</div>';
  resultsEl.style.display='block';
});
resultsEl.addEventListener('click',e=>{
  const r=e.target.closest('.r');if(!r)return;
  resultsEl.style.display='none';searchEl.value='';
  load(r.dataset.t,r.dataset.pn);
});
document.addEventListener('click',e=>{if(!e.target.closest('#results')&&e.target!==searchEl)resultsEl.style.display='none';});

document.getElementById('foot').innerHTML=
  `<span><b>${D.stats.plates}</b> plates · <b>${D.stats.parts}</b> distinct part numbers · <b>${D.stats.usages}</b> placements · <b>${D.stats.multi_plate_parts}</b> parts appear on 2+ plates (auto cross-links)</span>
   <span style="color:var(--warn)">All data is raw OCR — unverified. Confidence shown per hotspot.</span>`;

/* ============== EDIT MODE ============== */
let editing=false, addMode=false;
const pop=document.getElementById('edpop');
const bT=document.getElementById('ed-toggle'),bA=document.getElementById('ed-add'),
      bR=document.getElementById('ed-rot'),bX=document.getElementById('ed-export');

bT.onclick=()=>{
  editing=!editing;document.body.classList.toggle('editing',editing);
  bT.classList.toggle('on',editing);
  [bA,bR,bX].forEach(b=>b.style.display=editing?'':'none');
  document.getElementById('hint').textContent=editing
    ?'EDIT MODE — click a box to fix its number · drag box to move · drag orange grip to resize · ＋ Add box for missed numbers'
    :'drag to pan · scroll to zoom · click part numbers on the drawing';
  if(!editing){addMode=false;bA.classList.remove('on');closePop();}
};

function stagePoint(e){
  const r=viewer.getBoundingClientRect();
  return {x:(e.clientX-r.left-view.x)/view.s, y:(e.clientY-r.top-view.y)/view.s};
}
function setEdit(id,patch){
  const e=edFor(cur.tav);
  const h=curParts.find(x=>x.id===id);
  const base=e.hs[id]||(id.startsWith('b')
      ?{pn:h.pn,x:h.x,y:h.y,w:h.w,h:h.h}
      :null);
  e.hs[id]=Object.assign({},base,e.hs[id]||{},patch);
  edSave();
}

/* popup editor */
function openPop(id){
  const h=curParts.find(x=>x.id===id); if(!h)return;
  pop.dataset.id=id;
  pop.innerHTML=`
    <input type="text" id="ep-pn" value="${h.pn}" spellcheck="false">
    <div class="row"><label><input type="checkbox" id="ep-ver" ${h.verified?'checked':''}> verified correct</label></div>
    <div class="row"><button class="pri" id="ep-save">Save</button><button class="del" id="ep-del">Delete box</button></div>
    <div class="row" style="color:var(--dim);font-size:11px">${h.conf?('OCR read this at '+Math.round(h.conf)+'% confidence'):'manually added box'}</div>`;
  const r=viewer.getBoundingClientRect();
  pop.style.left=Math.min(r.width-250,Math.max(8,(h.x*cur.w)*view.s+view.x+30))+'px';
  pop.style.top=Math.min(r.height-140,Math.max(8,(h.y*cur.h)*view.s+view.y-20))+'px';
  pop.style.display='block';
  document.getElementById('ep-save').onclick=()=>{
    setEdit(id,{pn:document.getElementById('ep-pn').value.trim(),
                verified:document.getElementById('ep-ver').checked});
    closePop();refresh(id);
  };
  document.getElementById('ep-del').onclick=()=>{setEdit(id,{del:true});closePop();refresh();};
  document.getElementById('ep-pn').focus();
}
function closePop(){pop.style.display='none';pop.dataset.id='';}
function refresh(selId){rebuildWhere();const t=cur.tav;load(t);if(selId)select(null,false,selId);}

/* move + resize (drag box / drag grip) */
let hsDrag=null;
stage.addEventListener('mousedown',e=>{
  if(!editing)return;
  const grip=e.target.closest('.grip'), box=e.target.closest('.hs');
  if(!box)return;
  e.stopPropagation();e.preventDefault();
  const h=curParts.find(x=>x.id===box.dataset.id);
  hsDrag={id:box.dataset.id,el:box,h,grip:!!grip,start:stagePoint(e),
          ox:h.x,oy:h.y,ow:h.w,oh:h.h,moved:false};
},true);
window.addEventListener('mousemove',e=>{
  if(!hsDrag)return;
  const p=stagePoint(e),dx=(p.x-hsDrag.start.x)/cur.w,dy=(p.y-hsDrag.start.y)/cur.h;
  if(Math.abs(dx)+Math.abs(dy)>0.0005)hsDrag.moved=true;
  const h=hsDrag.h;
  if(hsDrag.grip){h.w=Math.max(.01,hsDrag.ow+dx*2);h.h=Math.max(.008,hsDrag.oh+dy*2);}
  else{h.x=hsDrag.ox+dx;h.y=hsDrag.oy+dy;}
  const el=hsDrag.el,w=Math.max(h.w*cur.w,90),ht=Math.max(h.h*cur.h,34);
  el.style.left=(h.x*cur.w-w/2)+'px';el.style.top=(h.y*cur.h-ht/2)+'px';
  el.style.width=w+'px';el.style.height=ht+'px';
});
window.addEventListener('mouseup',()=>{
  if(hsDrag&&hsDrag.moved){
    const h=hsDrag.h;
    setEdit(hsDrag.id,{x:+h.x.toFixed(4),y:+h.y.toFixed(4),w:+h.w.toFixed(4),h:+h.h.toFixed(4)});
  }
  hsDrag=null;
});

/* add box */
bA.onclick=()=>{addMode=!addMode;bA.classList.toggle('on',addMode);};
let addDrag=null;
const addrect=document.createElement('div');addrect.id='addrect';stage.appendChild(addrect);
viewer.addEventListener('mousedown',e=>{
  if(!editing||!addMode||e.target.closest('.zoomctl')||e.target.closest('#edpop'))return;
  e.stopPropagation();e.preventDefault();
  addDrag=stagePoint(e);
  stage.appendChild(addrect);addrect.style.display='block';
},true);
window.addEventListener('mousemove',e=>{
  if(!addDrag)return;
  const p=stagePoint(e);
  addrect.style.left=Math.min(addDrag.x,p.x)+'px';addrect.style.top=Math.min(addDrag.y,p.y)+'px';
  addrect.style.width=Math.abs(p.x-addDrag.x)+'px';addrect.style.height=Math.abs(p.y-addDrag.y)+'px';
});
window.addEventListener('mouseup',e=>{
  if(!addDrag)return;
  const p=stagePoint(e),x1=Math.min(addDrag.x,p.x),y1=Math.min(addDrag.y,p.y),
        w=Math.abs(p.x-addDrag.x),h=Math.abs(p.y-addDrag.y);
  addDrag=null;addrect.style.display='none';
  if(w<20||h<12)return;
  const id='n'+Date.now();
  const ed=edFor(cur.tav);
  ed.hs[id]={pn:'',x:+((x1+w/2)/cur.w).toFixed(4),y:+((y1+h/2)/cur.h).toFixed(4),
             w:+(w/cur.w).toFixed(4),h:+(h/cur.h).toFixed(4),verified:true};
  edSave();refresh();setTimeout(()=>{select(null,false,id);openPop(id);},80);
  addMode=false;bA.classList.remove('on');
});

/* rotate flag */
bR.onclick=()=>{
  const e=edFor(cur.tav);
  e.rotate=((e.rotate||0)+90)%360;
  edSave();load(cur.tav);
};

/* export */
bX.onclick=()=>{
  const out={version:1,exported_for:'pipeline/apply_edits.py',edits:ED};
  const blob=new Blob([JSON.stringify(out,null,1)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='edits.json';a.click();
};
edCount();

/* start on the first brakes plate if present, else first plate */
load(plates['33125']?'33125':Object.keys(plates)[0]);
</script>
</body>
</html>"""

if __name__ == "__main__":
    main()
