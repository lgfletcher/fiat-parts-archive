#!/usr/bin/env python3
"""
Generate docs/paint.html — the paint codes & colour chart gallery.

    python3 pipeline/export_paint.py \
        --src archive/raw/x19/colour_charts \
        --manifest pipeline/paint_charts_manifest.txt --out docs

Pairs each '-chips' image with its '-codes' sibling (same filename stem)
so swatches sit beside their code tables. Everything else lists as a
single card. Images are copied to docs/paint/ as-is (webp originals).
"""
import argparse, html, re, shutil
from pathlib import Path

def load_captions(manifest):
    caps = {}
    if manifest and Path(manifest).exists():
        for ln in Path(manifest).read_text().splitlines():
            if "|" in ln and not ln.startswith("#"):
                url, cap = ln.split("|", 1)
                caps[Path(url.strip()).name] = cap.strip()
    return caps

def pretty(name):
    s = re.sub(r"\.(webp|jpg|jpeg|png)$", "", name, flags=re.I)
    s = re.sub(r"[-_]+", " ", s)
    return s.title().replace("Ppg", "PPG").replace("X19", "X1/9")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--manifest", default="pipeline/paint_charts_manifest.txt")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out); (out / "paint").mkdir(parents=True, exist_ok=True)
    caps = load_captions(args.manifest)

    files = sorted(p for p in src.glob("*")
                   if p.suffix.lower() in (".webp", ".jpg", ".jpeg", ".png")
                   and not p.name.startswith("."))
    if not files:
        print(f"no images found in {src} — fetch the charts first"); return
    for f in files:
        dst = out / "paint" / f.name
        if not dst.exists():
            shutil.copy2(f, dst)

    names = {f.name for f in files}
    used, pairs, singles = set(), [], []
    for f in files:
        if f.name in used:
            continue
        m = re.match(r"(.+)-chips(\.\w+)$", f.name)
        if m:
            codes = None
            for cand in (f"{m.group(1)}-codes{m.group(2)}",):
                if cand in names:
                    codes = cand
            pairs.append((f.name, codes))
            used.add(f.name)
            if codes: used.add(codes)
        else:
            singles.append(f.name)
            used.add(f.name)
    # move '-codes' without a chips partner into singles (already handled), keep order by year
    def year_key(n):
        m = re.match(r"(\d{4})", n); return (m.group(1) if m else "9999", n)
    pairs.sort(key=lambda p: year_key(p[0]))
    singles.sort(key=year_key)

    def card(img, label, wide=False):
        cap = caps.get(img, pretty(img))
        return f"""<figure class="{'wide' if wide else ''}">
          <img src="paint/{img}" loading="lazy" alt="{html.escape(cap)}" data-cap="{html.escape(cap)}">
          <figcaption>{html.escape(cap)}</figcaption></figure>"""

    rows = ["<h2>PPG chips &amp; codes by year</h2>"]
    for chips, codes in pairs:
        rows.append('<div class="pair">')
        rows.append(card(chips, chips))
        if codes: rows.append(card(codes, codes))
        rows.append('</div>')
    if singles:
        rows.append("<h2>Other colour references</h2><div class='grid'>")
        rows.extend(card(s, s) for s in singles)
        rows.append("</div>")

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Paint codes &amp; colour charts — Fiat Classic Parts Archive</title>
<style>
 :root{{--bg:#1c1f26;--panel:#252932;--line:#3a4150;--txt:#e8e6df;--dim:#9aa0ac;--accent:#e8b84b;--accent2:#7fb4d8}}
 *{{box-sizing:border-box}}
 body{{font-family:"Avenir Next","Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--txt);margin:0}}
 header{{display:flex;align-items:center;gap:12px;padding:12px 22px;background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}}
 header h1{{font-size:15px;letter-spacing:.04em;margin:0}}
 header a{{color:var(--accent);text-decoration:none;font-size:12.5px;border:1px solid var(--line);border-radius:6px;padding:5px 10px}}
 main{{max-width:1200px;margin:0 auto;padding:24px 22px 70px}}
 h2{{color:var(--accent);font-size:16px;border-bottom:1px solid var(--line);padding-bottom:6px;margin:30px 0 16px}}
 .pair{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:22px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}}
 figure{{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px;cursor:zoom-in}}
 figure img{{width:100%;height:auto;border-radius:6px;display:block;background:#fff}}
 figcaption{{font-size:12.5px;color:var(--dim);padding:8px 4px 2px}}
 @media(max-width:760px){{.pair{{grid-template-columns:1fr}}}}
 /* lightbox */
 #lb{{position:fixed;inset:0;background:rgba(10,12,16,.94);display:none;z-index:50;cursor:grab}}
 #lb.on{{display:block}}
 #lb.dragging{{cursor:grabbing}}
 #lbimg{{position:absolute;transform-origin:0 0;user-select:none;background:#fff}}
 #lbcap{{position:fixed;left:0;right:0;bottom:0;text-align:center;padding:10px;font-size:13px;color:var(--txt);background:rgba(28,31,38,.85)}}
 #lbx{{position:fixed;top:14px;right:18px;font-size:26px;color:var(--txt);cursor:pointer;z-index:51;background:var(--panel);border:1px solid var(--line);border-radius:8px;width:40px;height:40px;line-height:36px;text-align:center}}
 .hint{{color:var(--dim);font-size:12px;margin-top:6px}}
</style></head><body>
<header><a href="library.html">← Library</a><a href="index.html">Parts viewer</a><a href="wiring.html">Wiring</a>
<h1>PAINT CODES &amp; COLOUR CHARTS — FIAT X1/9</h1></header>
<main>
<p class="hint">Chips (swatches) are shown beside their matching code tables. Click any chart to zoom —
scroll to magnify, drag to pan.
Screen colours are indicative only — always confirm against a physical chip or code before mixing.</p>
{chr(10).join(rows)}
</main>
<div id="lb"><img id="lbimg"><div id="lbcap"></div><div id="lbx">✕</div></div>
<script>
const lb=document.getElementById('lb'),im=document.getElementById('lbimg'),cap=document.getElementById('lbcap');
let v={{x:0,y:0,s:1}};
function ap(){{im.style.transform=`translate(${{v.x}}px,${{v.y}}px) scale(${{v.s}})`;}}
document.querySelectorAll('main figure img').forEach(el=>{{
  el.parentElement.onclick=()=>{{
    im.src=el.src;cap.textContent=el.dataset.cap;lb.classList.add('on');
    im.onload=()=>{{const s=Math.min(innerWidth/im.naturalWidth,(innerHeight-50)/im.naturalHeight)*.96;
      v={{s:s,x:(innerWidth-im.naturalWidth*s)/2,y:(innerHeight-50-im.naturalHeight*s)/2}};ap();}};
  }};
}});
document.getElementById('lbx').onclick=()=>lb.classList.remove('on');
lb.addEventListener('click',e=>{{if(e.target===lb)lb.classList.remove('on');}});
document.addEventListener('keydown',e=>{{if(e.key==='Escape')lb.classList.remove('on');}});
lb.addEventListener('wheel',e=>{{e.preventDefault();
  const f=e.deltaY<0?1.2:1/1.2,s2=Math.min(10,Math.max(.1,v.s*f));
  v.x=e.clientX-(e.clientX-v.x)*(s2/v.s);v.y=e.clientY-(e.clientY-v.y)*(s2/v.s);v.s=s2;ap();
}},{{passive:false}});
let dr=null;
lb.addEventListener('mousedown',e=>{{if(e.target.id==='lbx')return;dr={{mx:e.clientX,my:e.clientY,x:v.x,y:v.y}};lb.classList.add('dragging');e.preventDefault();}});
window.addEventListener('mousemove',e=>{{if(!dr)return;v.x=dr.x+e.clientX-dr.mx;v.y=dr.y+e.clientY-dr.my;ap();}});
window.addEventListener('mouseup',()=>{{dr=null;lb.classList.remove('dragging');}});
</script>
</body></html>"""
    (out / "paint.html").write_text(page)
    print(f"paint.html: {len(pairs)} chip/code pairs + {len(singles)} singles from {len(files)} images")

if __name__ == "__main__":
    main()
