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
from skg.analyze.themes import THEMES, is_parent, label_of, parent_of, themes_in
from skg.database import make_repo

MIN_COOCCUR = 4
MAX_HEADLINES = 8  # per node / per edge kept for the panel
MAX_EDGES = 60     # shipped-edge cap (w desc) — every shipped edge carries a summary
# surge windows: 7d vs prior 28d (was 2d vs 7d). Poisson power analysis (감사 2026-07-05):
# 2d 창은 테마당 >=3.1건/일이 필요해 76개 중 8~11개만 통계가 섰음; 7d/28d면 요구선이
# ~0.86건/일로 내려가 40여 개 테마가 판별 가능해짐. 의미도 '오늘의 스파이크'가 아니라
# '이번 주의 부상'으로 더 강건.
SURGE_RECENT_D = 7
SURGE_BASE_D = 28
SURGE_MIN_RECENT = 5  # fewer recent stories -> surge null (표본 미달은 침묵이 정직)


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


def _load_summaries():
    p = cfg.ROOT / "data" / "theme_summaries.json"
    if not p.exists():
        return {"nodes": {}, "edges": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def compute_theme_data(repo) -> dict:
    """Assemble the {nodes, edges, summary_date} structure for BOTH the standalone HTML
    builder and the React artifact (artifact_views.build_theme_data). Single source of truth
    — previously the React path regex-scraped this JSON back out of themes.html, which drifted.
    Also persists :ThemeDay buckets as a side effect (additive temporal layer)."""
    summaries = _load_summaries()
    # claim headline + the entity it's about (for per-theme top entities = "sub-bubbles").
    # Join the source so we can exclude automated-content factory outlets from display.
    from skg.sources.news import is_quality_outlet
    rows = repo._read(
        "MATCH (cl:Claim)-[:FROM_SOURCE]->(src:Source) WHERE cl.source_id STARTS WITH 'news::' "
        "OPTIONAL MATCH (cl)-[:ABOUT]->(e) WHERE e:Issuer OR e:MacroIndicator "
        "RETURN cl.source_span AS h, cl.event_time AS t, "
        "coalesce(e.name, e.indicator_id) AS ent, src.name AS outlet")
    from skg.analyze.headline_dedup import clean_headline, collapse_groups
    recs = [{"text": clean_headline(r["h"], r["outlet"]), "date": (r["t"] or "")[:10],
             "ent": r["ent"]}
            for r in rows if r["h"] and is_quality_outlet(r["outlet"])]  # vetted press only
    # one story syndicated by N outlets = ONE story everywhere downstream (freq, heat,
    # entity n, edge w, ThemeDay, heads); its distinct entities all keep attribution
    groups = collapse_groups(recs)
    print(f"[view] {len(recs)} headlines -> {len(groups)} unique stories (near-dups collapsed)")
    theme_entities = defaultdict(Counter)
    entity_total = Counter()  # overall story count per entity (for LIFT ranking)

    freq = Counter()
    wfreq = defaultdict(float)         # DECAY-weighted theme freq ("지금 열기")
    wstance = defaultdict(lambda: defaultdict(float))  # decay-weighted stance
    cooc = Counter()
    node_heads = defaultdict(list)     # theme -> [(date, headline, stance)]
    edge_heads = defaultdict(list)     # (a,b) -> [(date, headline, stance)]
    node_stance = defaultdict(Counter)
    edge_stance = defaultdict(Counter)
    te_heads = defaultdict(list)       # (theme, entity) -> headlines (drill level 3)
    edge_entities = defaultdict(Counter)  # (a,b) -> entity story counts (auto-summary input)
    # per-day buckets: (theme, day) -> {count, bull, bear, neut}. Persisted as :ThemeDay nodes
    # (additive temporal layer for decay/trend/accumulation).
    theme_day = defaultdict(lambda: {"count": 0, "bull": 0, "bear": 0, "neut": 0})

    for g in groups:
        full, date, ents = g["text"], g["date"], g["ents"]
        for ent in ents:
            entity_total[ent] += 1
        ts = themes_in(full)  # parents AND child sub-themes (post-clean: outlet names can't match)
        if not ts:
            continue
        st = lexicon.stance_of(full)
        ch = " ".join(full.split())[:120]
        w = _decay_weight(date)   # recent story ~1.0, old ~0
        sday = date[:10] if date else ""
        for t in sorted(ts):   # set order is hash-randomized — sort for deterministic dicts
            freq[t] += 1
            wfreq[t] += w
            node_stance[t][st] += 1
            wstance[t][st] += w
            if sday:
                b = theme_day[(t, sday)]
                b["count"] += 1
                b["bull" if st == "bullish" else "bear" if st == "bearish" else "neut"] += 1
            for ent in ents:
                theme_entities[t][ent] += 1
                if len(te_heads[(t, ent)]) < 30:
                    te_heads[(t, ent)].append((date, ch, st))
            if len(node_heads[t]) < 400:
                node_heads[t].append((date, ch, st))
        # co-occurrence edges among PARENTS only (the macro association web). Children attach
        # to their parent via hierarchy (CHILD_OF), not via this co-occurrence graph.
        parents = sorted(t for t in ts if is_parent(t))
        for a, b in combinations(parents, 2):
            cooc[(a, b)] += 1
            edge_stance[(a, b)][st] += 1
            for ent in ents:
                edge_entities[(a, b)][ent] += 1
            if len(edge_heads[(a, b)]) < 200:
                edge_heads[(a, b)].append((date, ch, st))

    # keep top headlines for the panel: PRIORITIZE stance-bearing ones (돌파/우려 are the
    # informative development-vs-bubble signals), then fill with recent neutral ones.
    # diverse() drops near-repeats of an already-shown story (multi-day re-coverage).
    from skg.analyze.headline_dedup import diverse

    def top(hs):
        stanced, neutral = [], []
        for d, t, s in sorted(hs, reverse=True):
            (neutral if s == "neutral" else stanced).append({"d": d, "t": t, "s": s})
        return diverse(stanced + neutral, MAX_HEADLINES)

    # 급상승 (surge): 최근 7일 스토리율 vs 직전 28일 기준율, additive smoothing.
    # Anchored on the LATEST story date in the corpus (not as_of): a morning run before the
    # day's news pull would otherwise see a half-empty recent window and deflate every theme.
    # Pure function of the corpus + as_of (deterministic); null under the volume floor so a
    # quiet weekend can't fabricate a riser. OBSERVATION of news volume, not a signal.
    import datetime as _dt
    _cap = cfg.AS_OF_NOW[:10]
    _days_with_news = [d for (_t, d) in theme_day if d and d <= _cap]
    _anchor = max(_days_with_news) if _days_with_news else _cap
    _d0 = _dt.date.fromisoformat(_anchor)
    _recent_days = {(_d0 - _dt.timedelta(days=k)).isoformat() for k in range(SURGE_RECENT_D)}
    _base_days = {(_d0 - _dt.timedelta(days=k)).isoformat()
                  for k in range(SURGE_RECENT_D, SURGE_RECENT_D + SURGE_BASE_D)}
    _per_theme_day = defaultdict(dict)
    for (tt, d), b in theme_day.items():
        _per_theme_day[tt][d] = b["count"]

    def _surge_of(t):
        days = _per_theme_day.get(t, {})
        rec = sum(c for d, c in days.items() if d in _recent_days)
        base = sum(c for d, c in days.items() if d in _base_days)
        if rec < SURGE_MIN_RECENT:
            return None, rec
        return round((rec / SURGE_RECENT_D + 0.5) / (base / SURGE_BASE_D + 0.5), 2), rec

    # shipped children per parent (hierarchy payload for the frontend)
    kids = defaultdict(list)
    for t in freq:
        p = parent_of(t)
        if p:
            kids[p].append(t)

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
        # co-occurring PARENT themes (clickable -> opens that edge panel; drill level 2 sideways).
        # only parents have co-occurrence edges; restrict candidates so children don't show here.
        linked = sorted(
            [(cooc.get((min(t, o), max(t, o)), 0), o) for o in freq
             if o != t and is_parent(o) and is_parent(t)],
            reverse=True)
        related = [{"id": o, "label": label_of(o), "w": w} for w, o in linked if w >= MIN_COOCCUR][:6]
        ws = wstance[t]
        # daily volume series (last ~21 days) for the trend sparkline in the panel
        # 달력일 기준 최근 21일, 0 포함 — '스토리 있는 날'만 이으면 얇은 테마의 x축이
        # 수개월을 '최근 21일'로 압축해 왜곡 (감사 표시-유효성 결함 수정)
        days_map = _per_theme_day.get(t, {})
        trend = [days_map.get((_d0 - _dt.timedelta(days=k)).isoformat(), 0)
                 for k in range(20, -1, -1)]
        surge, recent_n = _surge_of(t)
        nodes.append({
            "id": t, "label": label_of(t), "freq": f,
            "parent": parent_of(t),            # None for parents; parent_id for children
            "level": 0 if is_parent(t) else 1,
            "children": sorted(kids.get(t, [])),
            "heat": round(wf, 1),  # decay-weighted "지금 열기"
            "surge": surge,        # 급상승 배율 (최근2일 vs 직전7일; null = 볼륨 미달)
            "recent_n": recent_n,  # 최근 2일 스토리 수
            "size": 18 + 42 * (wf / maxwf),  # SIZE reflects recent heat, not raw count
            "summary": summaries.get("nodes", {}).get(t, ""),
            # stance bar uses DECAY-weighted counts -> reflects the CURRENT framing
            "stance": {"bull": round(ws["bullish"], 1), "bear": round(ws["bearish"], 1),
                       "neut": round(ws["neutral"], 1)},
            "trend": trend,
            "entities": ents,
            "related": related,
            "heads": top(node_heads[t]),
        })
    # lift = 관측 동시등장 / 독립 기대 (fa·fb/N) — 감사 발견: raw w 기준은 "둘 다 큰 테마라
    # 우연히 같이 나온" 볼륨성 엣지 11개를 진짜 연관과 구분 없이 실었음. lift<1.5는 정직하게
    # '볼륨성'으로 표시(제거하지 않음 — 연결 자체는 사실이므로 해석만 붙임).
    n_stories = max(1, len(groups))

    def _mk_edge(a, b, w, weak=False):
        sc = edge_stance[(a, b)]
        expected = (freq[a] * freq[b]) / n_stories
        lift = round(w / expected, 1) if expected > 0 else 0.0
        volume_only = (not weak) and lift < 1.5
        curated = summaries.get("edges", {}).get(f"{a}|{b}", "")
        if curated:
            summary, kind = curated, "curated"
        else:
            # deterministic templated fallback from counted data — every shipped edge
            # explains itself ("함께 N건"만 있는 엣지 금지); curation upgrades it later
            ents3 = [e for e, _ in edge_entities[(a, b)].most_common(3)
                     if e and not str(e).startswith("MACRO:")][:3]
            ent_part = f" · 주요 관련: {', '.join(ents3)}" if ents3 else ""
            weak_part = " · 표본 적음(약한 연결)" if weak else ""
            vol_part = (" · 두 이슈 모두 뉴스량이 많아 함께 등장한 성격이 큼(특이 연관 약함)"
                        if volume_only else "")
            summary = (f"{label_of(a)}·{label_of(b)} — 최근 뉴스 {w}건에서 함께 등장"
                       f" (우연 기대 대비 {lift}배){ent_part}"
                       f" · 논조 긍정 {sc['bullish']}·부정 {sc['bearish']}·중립 {sc['neutral']}"
                       f"{weak_part}{vol_part}")
            kind = "auto"
        e = {"a": a, "b": b, "w": w, "lift": lift,
             "summary": summary, "summary_kind": kind,
             "stance": {"bull": sc["bullish"], "bear": sc["bearish"], "neut": sc["neutral"]},
             "heads": top(edge_heads[(a, b)])}
        if weak:
            e["weak"] = True
        if volume_only:
            e["volume_only"] = True
        return e

    edges = [_mk_edge(a, b, w) for (a, b), w in cooc.items() if w >= MIN_COOCCUR]
    edges.sort(key=lambda e: (-e["w"], e["a"], e["b"]))
    edges = edges[:MAX_EDGES]

    # 부모 최소 1엣지 보장: 임계(4) 미달로 고립된 부모는 최강 동시등장 1개를 '약한 연결'로
    # 편입 (w>=2 — 1건짜리는 일화라 제외). 측정(2026-07-05): 고립 9개 중 7개가 w=2~3의
    # 실제 연결을 갖고 있었음 (조선-유가 3, 조선-방산 3, 트럼프-지정학 2 …). 그래도 남는
    # 고립(gold, trade)은 노드에 isolated 표시 — 강제 연결보다 정직한 공백.
    linked = {e["a"] for e in edges} | {e["b"] for e in edges}
    for p in sorted(set(freq) & set(THEMES)):
        if p in linked:
            continue
        cands = sorted(((w, a, b) for (a, b), w in cooc.items()
                        if w >= 2 and p in (a, b)), reverse=True)
        if cands:
            w, a, b = cands[0]
            edges.append(_mk_edge(a, b, w, weak=True))
            linked |= {a, b}
    for n in nodes:
        if n["level"] == 0 and n["id"] not in linked:
            n["isolated"] = True   # 코퍼스 표본 부족 — UI가 흐리게 + 패널에 사유 표시
    nodes.sort(key=lambda n: n["id"])   # byte-identical artifact across runs

    # 이슈→종목→가격: real daily move + 52w position per related entity (export-time join;
    # PriceSeries is refreshed every cron so this costs no new fetches)
    from skg.analyze.headline_dedup import day_change_from_closes
    ent_names = sorted({e["name"] for n in nodes for e in n["entities"]})
    if ent_names and hasattr(repo, "_read"):
        px = {r["n"]: r for r in repo._read(
            "MATCH (i:Issuer)-[:HAS_PRICE]->(p:PriceSeries) WHERE i.name IN $names "
            "RETURN i.name AS n, i.pos_52w AS pos, p.recent_closes_json AS c, "
            "p.window_end AS we", names=ent_names)}
        for n in nodes:
            for e in n["entities"]:
                r = px.get(e["name"])
                e["chg"] = day_change_from_closes(r["c"], r["we"], cfg.AS_OF_NOW) if r else None
                e["pos"] = r.get("pos") if r else None

    # 급상승 랭킹: 실제 상승(>=1.2배)만 자격 — 데이터가 조용하면 빈 목록이 정직한 답
    # (child가 오르면 그 child가 구체적 인사이트 — frontend가 부모 생략)
    risers = sorted([n for n in nodes if n.get("surge") and n["surge"] >= 1.2],
                    key=lambda n: (-n["surge"], -n["recent_n"], n["id"]))[:8]
    rising = [{"id": n["id"], "label": n["label"], "surge": n["surge"],
               "recent_n": n["recent_n"], "parent": n["parent"],
               "why": (max(n["heads"], key=lambda h: h["d"])["t"] if n["heads"] else "")}
              for n in risers]

    print(f"[view] {len(nodes)} themes, {len(edges)} edges "
          f"(summaries: {sum(1 for e in edges if e['summary_kind'] == 'curated')} curated / "
          f"{sum(1 for e in edges if e['summary_kind'] == 'auto')} auto), "
          f"{len(rising)} risers")

    # persist per-day buckets (:ThemeDay) — additive temporal layer for decay/trend/accumulation
    if hasattr(repo, "write_theme_days"):
        day_rows = [{"theme_id": t, "day": d, "count": b["count"],
                     "w_bull": b["bull"], "w_bear": b["bear"], "w_neut": b["neut"]}
                    for (t, d), b in theme_day.items()]
        repo.write_theme_days(day_rows)
        print(f"[view] persisted {len(day_rows)} :ThemeDay buckets")

    return {"nodes": nodes, "edges": edges, "rising": rising,
            "summary_date": summaries.get("knowledge_time", "")[:10]}


def main() -> None:
    repo = make_repo(cfg)
    data = compute_theme_data(repo)
    out = cfg.OUT / "themes.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render(data["nodes"], data["edges"]), encoding="utf-8")
    print(f"[view] -> {out}")
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
function trendChart(trend){
  if(!trend||trend.length<2)return "";
  const w=320,h=46,mx=Math.max(...trend)||1;
  const pts=trend.map((v,i)=>`${(i/(trend.length-1)*w).toFixed(1)},${(h-v/mx*h).toFixed(1)}`).join(" ");
  const up=trend[trend.length-1]>=trend[0];
  return `<div class=seclabel>이슈 열기 추이 (최근 ${trend.length}일 · 뉴스량)</div>`+
    `<svg width="${w}" height="${h}" style="background:#0e131c;border-radius:6px;margin-top:4px">`+
    `<polyline points="${pts}" fill="none" stroke="${up?'#6BCB77':'#FF6B6B'}" stroke-width="2"/></svg>`;
}
let curNode=null;
function render(html){document.getElementById('panel').innerHTML=crumb()+html; bindChips();}
function showNode(n,push=true){
  curNode=n;
  if(push)trail.push({kind:'node',id:n.id,name:n.label});
  render(`<h2>${n.label}</h2><div class=sub>뉴스 ${n.freq}건 · <span style="color:#FFD93D">지금 열기 ${n.heat}</span> <span style="color:#667">(최근 가중)</span></div>`
   + summaryBox(n.summary) + stanceBar(n.stance) + trendChart(n.trend)
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
