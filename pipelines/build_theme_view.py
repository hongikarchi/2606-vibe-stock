"""build_theme_view.py — themes.html with MEANING (headlines + stance per node & edge).

The user's #1 ask: a theme node/edge shouldn't just say "AI, 1294 news" — it should show WHAT
the news actually says, so they can tell 개발 vs 거품. This builds a self-contained interactive
page where clicking a theme or an edge opens a side panel with:
  - stance breakdown (bullish 돌파/수주 vs bearish 우려/거품)  <- answers development-vs-bubble
  - the actual recent headlines behind it

All data (themes, edges, headlines, stance) is embedded in the HTML as JSON, so clicks are
instant and the file is portable. Observation only — we show headlines + stance, we do NOT
write a causal narrative (that's the human's step).

    SKG_STORAGE_BACKEND=neo4j python build_theme_view.py
"""
from __future__ import annotations

# repo root on sys.path so `import config` / `import skg` work when run as pipelines/<x>.py
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import html
import json
import sys
from collections import Counter, defaultdict
from itertools import combinations

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.analyze import lexicon
from skg.analyze.themes import THEMES, label_of, themes_in
from skg.store import make_repo

MIN_COOCCUR = 4
MAX_HEADLINES = 8  # per node / per edge kept for the panel


def _decay_weight(date_str: str) -> float:
    """0.5 ** (age_days / half_life). Recent news ~1.0, a half-life old ~0.5, older fades.
    'now' = cfg.AS_OF_NOW (deterministic). Future/garbage dates clamp to weight 1.0."""
    import datetime
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        now = datetime.date.fromisoformat(cfg.AS_OF_NOW[:10])
        age = (now - d).days
        if age <= 0:
            return 1.0
        return 0.5 ** (age / cfg.DECAY_HALF_LIFE_DAYS)
    except Exception:  # noqa: BLE001
        return 0.3  # undated -> low but nonzero


def _clean(h: str) -> str:
    # drop the trailing " - 출처" Google News appends, collapse whitespace
    h = h.split(" - ")[0] if " - " in h[-40:] else h
    return " ".join(h.split())[:120]


def _load_summaries():
    p = cfg.ROOT / "data" / "theme_summaries.json"
    if not p.exists():
        return {"nodes": {}, "edges": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    repo = make_repo(cfg)
    summaries = _load_summaries()
    # claim headline + the entity it's about (for per-theme top entities = "sub-bubbles")
    rows = repo._read(
        "MATCH (cl:Claim) WHERE cl.source_id STARTS WITH 'news::' "
        "OPTIONAL MATCH (cl)-[:ABOUT]->(e) WHERE e:Issuer OR e:MacroIndicator "
        "RETURN cl.source_span AS h, cl.event_time AS t, "
        "coalesce(e.name, e.indicator_id) AS ent")
    items = [(r["h"], (r["t"] or "")[:10], r["ent"]) for r in rows if r["h"]]
    print(f"[view] {len(items)} headlines")
    theme_entities = defaultdict(Counter)
    entity_total = Counter()  # overall mentions per entity (for LIFT ranking)

    freq = Counter()
    wfreq = defaultdict(float)         # DECAY-weighted theme freq ("지금 열기")
    wstance = defaultdict(lambda: defaultdict(float))  # decay-weighted stance
    cooc = Counter()
    node_heads = defaultdict(list)     # theme -> [(date, headline, stance)]
    edge_heads = defaultdict(list)     # (a,b) -> [(date, headline, stance)]
    node_stance = defaultdict(Counter)
    edge_stance = defaultdict(Counter)
    te_heads = defaultdict(list)       # (theme, entity) -> headlines (drill level 3)
    # per-day buckets: (theme, day) -> {count, bull, bear, neut}. Persisted as :ThemeDay nodes
    # (additive temporal layer for decay/trend/accumulation).
    theme_day = defaultdict(lambda: {"count": 0, "bull": 0, "bear": 0, "neut": 0})

    for h, date, ent in items:
        if ent:
            entity_total[ent] += 1
        ts = themes_in(h)
        if not ts:
            continue
        st = lexicon.stance_of(h)
        ch = _clean(h)
        w = _decay_weight(date)   # recent headline ~1.0, old ~0
        sday = date[:10] if date else ""
        for t in ts:
            freq[t] += 1
            wfreq[t] += w
            node_stance[t][st] += 1
            wstance[t][st] += w
            if sday:
                b = theme_day[(t, sday)]
                b["count"] += 1
                b["bull" if st == "bullish" else "bear" if st == "bearish" else "neut"] += 1
            if ent:
                theme_entities[t][ent] += 1
                if len(te_heads[(t, ent)]) < 30:
                    te_heads[(t, ent)].append((date, ch, st))
            if len(node_heads[t]) < 400:
                node_heads[t].append((date, ch, st))
        for a, b in combinations(sorted(ts), 2):
            cooc[(a, b)] += 1
            edge_stance[(a, b)][st] += 1
            if len(edge_heads[(a, b)]) < 200:
                edge_heads[(a, b)].append((date, ch, st))

    # keep top headlines for the panel: PRIORITIZE stance-bearing ones (돌파/우려 are the
    # informative development-vs-bubble signals), then fill with recent neutral ones.
    def top(hs):
        seen = set()
        stanced, neutral = [], []
        for d, t, s in sorted(hs, reverse=True):
            if t in seen:
                continue
            seen.add(t)
            (neutral if s == "neutral" else stanced).append({"d": d, "t": t, "s": s})
        out = stanced[:MAX_HEADLINES]
        out += neutral[: max(0, MAX_HEADLINES - len(out))]
        return out

    nodes = []
    maxwf = max(wfreq.values()) if wfreq else 1
    for t, f in freq.items():
        sc = node_stance[t]
        wf = wfreq[t]  # decay-weighted "지금 열기" — drives size + ranking
        # top entities = "sub-bubbles" — ranked by LIFT (specificity), not raw count, so
        # AI surfaces 레인보우로보틱스/에스티팜, not 현대차 (which appears under every theme).
        # balance specificity (lift) with relevance (count): score = lift * log(count). A pure
        # AI-name microcap (high lift, low count) and 삼성전기 (mid lift, high count) both surface;
        # a conglomerate appearing under every theme (low lift) is demoted even at high count.
        import math
        cand = []
        for e, c in theme_entities[t].items():
            if not e or str(e).startswith("MACRO:") or c < 3:
                continue
            lift = c / (entity_total[e] or 1)
            cand.append((lift * math.log1p(c), c, e))
        cand.sort(reverse=True)
        ents = [{"name": e, "n": c, "heads": top(te_heads[(t, e)])} for _, c, e in cand[:8]]
        # co-occurring themes (clickable -> opens that edge panel; drill level 2 sideways)
        linked = sorted(
            [(cooc.get((min(t, o), max(t, o)), 0), o) for o in freq if o != t],
            reverse=True)
        related = [{"id": o, "label": label_of(o), "w": w} for w, o in linked if w >= MIN_COOCCUR][:6]
        ws = wstance[t]
        nodes.append({
            "id": t, "label": label_of(t), "freq": f,
            "heat": round(wf, 1),  # decay-weighted "지금 열기"
            "size": 18 + 42 * (wf / maxwf),  # SIZE reflects recent heat, not raw count
            "summary": summaries.get("nodes", {}).get(t, ""),
            # stance bar uses DECAY-weighted counts -> reflects the CURRENT framing
            "stance": {"bull": round(ws["bullish"], 1), "bear": round(ws["bearish"], 1),
                       "neut": round(ws["neutral"], 1)},
            "entities": ents,
            "related": related,
            "heads": top(node_heads[t]),
        })
    edges = []
    for (a, b), w in cooc.items():
        if w < MIN_COOCCUR:
            continue
        sc = edge_stance[(a, b)]
        edges.append({
            "a": a, "b": b, "w": w,
            "summary": summaries.get("edges", {}).get(f"{a}|{b}", ""),
            "stance": {"bull": sc["bullish"], "bear": sc["bearish"], "neut": sc["neutral"]},
            "heads": top(edge_heads[(a, b)]),
        })
    print(f"[view] {len(nodes)} themes, {len(edges)} edges with headlines+stance attached")

    out = cfg.OUT / "themes.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render(nodes, edges), encoding="utf-8")
    print(f"[view] -> {out}")

    # persist per-day buckets (:ThemeDay) — additive temporal layer for decay/trend/accumulation
    if hasattr(repo, "write_theme_days"):
        day_rows = [{"theme_id": t, "day": d, "count": b["count"],
                     "w_bull": b["bull"], "w_bear": b["bear"], "w_neut": b["neut"]}
                    for (t, d), b in theme_day.items()]
        repo.write_theme_days(day_rows)
        print(f"[view] persisted {len(day_rows)} :ThemeDay buckets")
    repo.close()


def _render(nodes, edges) -> str:
    data = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)
    sumdate = _load_summaries().get("knowledge_time", "")[:10] or "최근"
    # vis-network from CDN; side panel populated by click. Big fonts, fit-on-load.
    return _TEMPLATE.replace("__DATA__", data).replace("__SUMDATE__", sumdate)


_TEMPLATE = r"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
 html,body{margin:0;height:100%;background:#0b0f1a;color:#e8e8e8;font-family:'Noto Sans KR',system-ui,sans-serif}
 #wrap{display:flex;height:100vh}
 #net{flex:1;height:100%}
 #panel{width:380px;background:#11161f;border-left:1px solid #233;padding:16px 18px;overflow-y:auto}
 #panel h2{font-size:19px;margin:0 0 4px;color:#5AC8FA}
 #panel .sub{color:#889;font-size:13px;margin-bottom:14px}
 .stance{display:flex;height:22px;border-radius:5px;overflow:hidden;margin:10px 0 4px;font-size:12px}
 .bull{background:#2e7d4f}.bear{background:#a53a3a}.neut{background:#2a3344}
 .stance span{display:flex;align-items:center;justify-content:center;color:#fff}
 .legend{font-size:12px;color:#aaa;margin-bottom:14px}
 .hd{border-left:3px solid #2a3344;padding:6px 10px;margin:7px 0;background:#0e131c;border-radius:0 6px 6px 0;font-size:14px;line-height:1.5}
 .hd.b{border-color:#2e7d4f}.hd.r{border-color:#a53a3a}
 .hd .dt{color:#778;font-size:11px}
 .summary{background:#16202e;border:1px solid #2a3a52;border-radius:8px;padding:12px 14px;
   font-size:15px;line-height:1.65;margin:10px 0 4px;color:#dde7f2}
 .summary .tag{color:#5AC8FA;font-size:12px;font-weight:600;display:block;margin-bottom:5px}
 .chips{margin:8px 0}.chip{display:inline-block;background:#22304a;color:#cfe;border-radius:14px;
   padding:3px 11px;margin:3px 4px 3px 0;font-size:13px}
 .seclabel{margin-top:16px;font-weight:600;color:#9fb6d0;font-size:13px}
 .chip.ci{cursor:pointer}.chip.ci:hover{background:#3a4f74}
 .crumbs{font-size:12px;color:#88a;margin-bottom:10px}
 .crumb{cursor:pointer;color:#5AC8FA}.crumb:hover{text-decoration:underline}
 #hint{position:absolute;top:14px;left:18px;color:#99a;font-size:13px;background:#11161fcc;padding:8px 12px;border-radius:8px}
</style></head><body>
<div id=wrap><div id=net></div>
 <div id=panel><h2>테마를 클릭하세요</h2>
  <div class=sub>점=이슈 · 선=같은 기사에 함께 등장</div>
  <div class=legend>클릭하면 그 이슈(또는 두 이슈의 연결)가 뉴스에서<br><b>무슨 말을 하는지</b> — 긍정(돌파·수주)/부정(우려·거품) 비율과 실제 헤드라인이 여기 나옵니다.</div>
 </div></div>
<div id=hint>🖱️ 점/선 클릭 → 오른쪽에 실제 뉴스 · 휠로 확대/축소 · 드래그로 이동</div>
<script>
const DATA = __DATA__;
const palette = ["#4D96FF","#FF6B6B","#6BCB77","#FFD93D","#9D4EDD","#00C2A8","#FF9F45","#5AC8FA","#F26430","#E84855","#14B8A6","#F59E0B","#7B61FF","#22C55E","#EC4899","#A0A0A0","#94A3B8","#F97316","#10B981"];
const nodes = DATA.nodes.map((n,i)=>({id:n.id,label:n.label,value:n.heat,
   font:{size:20,color:"#fff",strokeWidth:3,strokeColor:"#0b0f1a"},color:palette[i%palette.length],
   scaling:{min:14,max:60}}));
const eMax = Math.max(...DATA.edges.map(e=>e.w),1);
const edges = DATA.edges.map((e,i)=>({id:"e"+i,from:e.a,to:e.b,value:e.w,
   width:1+9*(e.w/eMax),color:{color:"#8899bb55",highlight:"#5AC8FA"},title:`함께 ${e.w}건`}));
const nodeById={}; DATA.nodes.forEach(n=>nodeById[n.id]=n);
const edgeByKey={}; DATA.edges.forEach((e,i)=>edgeByKey["e"+i]=e);

const container=document.getElementById('net');
const net=new vis.Network(container,{nodes:new vis.DataSet(nodes),edges:new vis.DataSet(edges)},{
  physics:{barnesHut:{gravitationalConstant:-14000,centralGravity:0.35,springLength:170},stabilization:{iterations:200}},
  interaction:{hover:true,tooltipDelay:120},nodes:{shape:"dot"}});
net.once("stabilizationIterationsDone",()=>net.fit({animation:true}));

function stanceBar(s){
  const tot=(s.bull+s.bear+s.neut)||1;
  const pb=Math.round(100*s.bull/tot),pr=Math.round(100*s.bear/tot),pn=100-pb-pr;
  let html=`<div class=stance>`;
  if(pb)html+=`<span class=bull style="width:${pb}%">${pb>8?pb+'%':''}</span>`;
  if(pr)html+=`<span class=bear style="width:${pr}%">${pr>8?pr+'%':''}</span>`;
  if(pn)html+=`<span class=neut style="width:${pn}%">${pn>12?pn+'%':''}</span>`;
  html+=`</div><div class=legend>🟢 긍정(돌파·수주·호재) ${s.bull} · 🔴 부정(우려·거품·악재) ${s.bear} · ⚪ 중립 ${s.neut}</div>`;
  return html;
}
function heads(hs){
  if(!hs.length)return "<div class=legend>(표시할 헤드라인 없음)</div>";
  return hs.map(h=>`<div class="hd ${h.s=='bullish'?'b':h.s=='bearish'?'r':''}"><span class=dt>${h.d}</span><br>${esc(h.t)}</div>`).join("");
}
function esc(s){return s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
const SUMMARY_DATE = "__SUMDATE__";
function summaryBox(text){
  if(!text)return "";
  return `<div class=summary><span class=tag>📝 무슨 얘기인가 (${SUMMARY_DATE} 기준 종합 · 숫자는 최신 가중이라 요약과 시점이 다를 수 있음)</span>${esc(text)}</div>`;
}
// drill-down: panel contents are CLICKABLE -> open the next panel (book→castle→room)
const trail=[];  // breadcrumb stack
function crumb(){
  if(trail.length<2)return "";
  return `<div class=crumbs>`+trail.map((s,i)=>
    `<span class=crumb data-i="${i}">${esc(s.name)}</span>`).join(" ▸ ")+`</div>`;
}
function relChips(rel){
  if(!rel||!rel.length)return "";
  return `<div class=seclabel>이 이슈와 자주 엮이는 이슈 (클릭 → 연결 의미)</div><div class=chips>`+
    rel.map(r=>`<span class="chip ci" data-kind=edge data-a="${esc(r.id)}" data-b="">${esc(r.label)} <span style="color:#8ab">${r.w}</span></span>`).join("")+`</div>`;
}
function entChips(ents){
  if(!ents||!ents.length)return "";
  return `<div class=seclabel>관련 기업·대상 (작은 버블 · 클릭 → 이 기업 뉴스)</div><div class=chips>`+
    ents.map((e,i)=>`<span class="chip ci" data-kind=ent data-ei="${i}">${esc(e.name)} <span style="color:#8ab">${e.n}</span></span>`).join("")+`</div>`;
}
let curNode=null;
function render(html){document.getElementById('panel').innerHTML=crumb()+html; bindChips();}
function showNode(n,push=true){
  curNode=n;
  if(push)trail.push({kind:'node',id:n.id,name:n.label});
  render(`<h2>${n.label}</h2><div class=sub>뉴스 ${n.freq}건 · <span style="color:#FFD93D">지금 열기 ${n.heat}</span> <span style="color:#667">(최근 가중)</span></div>`
   + summaryBox(n.summary) + stanceBar(n.stance)
   + relChips(n.related) + entChips(n.entities)
   + `<div class=seclabel>근거 헤드라인 (긍정/부정 우선)</div>` + heads(n.heads));
}
function showEdge(e,push=true){
  const A=nodeById[e.a].label,B=nodeById[e.b].label;
  if(push)trail.push({kind:'edge',id:e.a+'|'+e.b,name:A+'↔'+B});
  render(`<h2>${A} ↔ ${B}</h2><div class=sub>같은 기사에 ${e.w}건 함께 등장</div>`
   + summaryBox(e.summary) + stanceBar(e.stance)
   + `<div class=seclabel>함께 다룬 헤드라인 (근거)</div>` + heads(e.heads));
}
function showEntity(ent,themeLabel){
  trail.push({kind:'ent',id:ent.name,name:ent.name});
  render(`<h2>${esc(ent.name)}</h2><div class=sub>${esc(themeLabel)} 맥락의 뉴스 ${ent.n}건</div>`
   + `<div class=seclabel>이 기업 헤드라인</div>` + heads(ent.heads||[]));
}
function edgeBetween(a,b){
  return DATA.edges.find(e=>(e.a==a&&e.b==b)||(e.a==b&&e.b==a));
}
function bindChips(){
  document.querySelectorAll('.crumb').forEach(c=>c.onclick=()=>{
    const i=+c.dataset.i; const s=trail[i]; trail.length=i;
    if(s.kind=='node')showNode(nodeById[s.id]);
    else if(s.kind=='edge'){const e=edgeByKey2(s.id);if(e)showEdge(e);}
  });
  document.querySelectorAll('.chip.ci').forEach(c=>c.onclick=()=>{
    if(c.dataset.kind=='edge'){
      const e=edgeBetween(curNode.id,c.dataset.a); if(e)showEdge(e);
    }else if(c.dataset.kind=='ent'){
      showEntity(curNode.entities[+c.dataset.ei], curNode.label);
    }
  });
}
function edgeByKey2(key){const [a,b]=key.split('|');return edgeBetween(a,b);}
net.on("click",p=>{
  if(p.nodes.length){trail.length=0;showNode(nodeById[p.nodes[0]]);}
  else if(p.edges.length){const e=edgeByKey[p.edges[0]];if(e){trail.length=0;showEdge(e);}}
});
</script></body></html>"""


if __name__ == "__main__":
    main()
