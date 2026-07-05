import React, { useEffect, useRef, useState } from "react";
import { Network } from "vis-network/standalone";

const PALETTE = ["#4D96FF","#FF6B6B","#6BCB77","#FFD93D","#9D4EDD","#00C2A8","#FF9F45",
  "#5AC8FA","#F26430","#E84855","#14B8A6","#F59E0B","#7B61FF","#22C55E","#EC4899",
  "#A0A0A0","#94A3B8","#F97316","#10B981","#D946EF"];

function StanceBar({ stance }) {
  const tot = (stance.bull + stance.bear + stance.neut) || 1;
  const pb = Math.round((100 * stance.bull) / tot);
  const pr = Math.round((100 * stance.bear) / tot);
  const pn = 100 - pb - pr;
  return (
    <>
      <div className="stance">
        {pb > 0 && <span className="bull" style={{ width: `${pb}%` }}>{pb > 8 ? pb + "%" : ""}</span>}
        {pr > 0 && <span className="bear" style={{ width: `${pr}%` }}>{pr > 8 ? pr + "%" : ""}</span>}
        {pn > 0 && <span className="neut" style={{ width: `${pn}%` }}>{pn > 12 ? pn + "%" : ""}</span>}
      </div>
      <div className="legend">🟢 긍정 {stance.bull} · 🔴 부정 {stance.bear} · ⚪ 중립 {stance.neut}</div>
    </>
  );
}

function Heads({ heads }) {
  if (!heads || !heads.length) return <div className="legend">(헤드라인 없음)</div>;
  return heads.map((h, i) => (
    <div key={i} className={"hd " + (h.s === "bullish" ? "b" : h.s === "bearish" ? "r" : "")}>
      <span className="dt">{h.d}</span><br />{h.t}
    </div>
  ));
}

function TrendChart({ trend }) {
  if (!trend || trend.length < 2) return null;
  const w = 320, h = 46, mx = Math.max(...trend) || 1;
  const pts = trend.map((v, i) => `${((i / (trend.length - 1)) * w).toFixed(1)},${(h - (v / mx) * h).toFixed(1)}`).join(" ");
  const up = trend[trend.length - 1] >= trend[0];
  return (
    <>
      <div className="seclabel">이슈 열기 추이 (최근 {trend.length}일 · 뉴스량)</div>
      <svg width={w} height={h} style={{ background: "#0e131c", borderRadius: 6, marginTop: 4 }}>
        <polyline points={pts} fill="none" stroke={up ? "#6BCB77" : "#FF6B6B"} strokeWidth="2" />
      </svg>
    </>
  );
}

const CLUSTER_PREFIX = "cl::";
// fallback open-threshold (used only until the post-fit scale is measured). The live threshold
// is set RELATIVE to the fit scale (see ZOOM_OPEN_MULT) so it's always reachable in a few ticks.
const ZOOM_OPEN = 0.35;
// expand at ~1.6x the resting scale — with 75+ nodes a casual wheel tick must not detonate
// all clusters at once (was 1.3 at 51 nodes).
const ZOOM_OPEN_MULT = 1.6;

export default function ThemesView({ useArtifact }) {
  const data = useArtifact("themes");
  const canvasRef = useRef(null);
  const netRef = useRef(null);
  const [sel, setSel] = useState(null); // {kind:'node'|'edge'|'ent', ...}
  const [trail, setTrail] = useState([]);

  const byId = data ? Object.fromEntries(data.nodes.map((n) => [n.id, n])) : {};
  const edgeBetween = (a, b) => data?.edges.find((e) => (e.a === a && e.b === b) || (e.a === b && e.b === a));
  // parent_id -> palette color, so a parent and its children share a hue
  const parentColor = {};
  if (data) data.nodes.filter((n) => n.level === 0).forEach((n, i) => { parentColor[n.id] = PALETTE[i % PALETTE.length]; });

  useEffect(() => {
    if (!data || !canvasRef.current) return;
    const parents = data.nodes.filter((n) => n.level === 0);
    const children = data.nodes.filter((n) => n.level === 1);
    const maxHeat = Math.max(...data.nodes.map((n) => n.heat ?? n.freq), 1);

    // 급상승 상위 3 노드는 그래프에서도 금색 링 + ▲ 라벨 (인사이트 우선 시각 위계)
    const riserIds = new Set((data.rising || []).slice(0, 3).map((r) => r.id));
    // build all nodes (parents + children); children carry their parent's color
    const visNodes = data.nodes.map((n) => {
      const col = n.level === 0 ? (parentColor[n.id] || "#789") : (parentColor[n.parent] || "#789");
      const hot = riserIds.has(n.id);
      const dim = n.isolated;   // 코퍼스 표본 부족으로 연결 없는 이슈 — 흐리게
      return {
        id: n.id, label: n.label + (hot ? " ▲" : ""), value: n.heat ?? n.freq, level: n.level, parent: n.parent,
        color: hot ? { background: col, border: "#FFD93D" }
             : dim ? { background: "#3a4252", border: "#2a3344" } : col,
        shape: "dot",
        opacity: dim ? 0.55 : 1,
        borderWidth: hot ? 3 : 1,
        font: { size: n.level === 0 ? 18 : 13, color: dim ? "#99a" : "#fff", strokeWidth: 3, strokeColor: "#0b0f1a" },
        scaling: { min: n.level === 0 ? 16 : 10, max: n.level === 0 ? (dim ? 24 : 60) : 26 },
      };
    });
    // child -> parent containment edges (hierarchy), + parent-parent co-occurrence (the macro web)
    const containment = children
      .filter((c) => byId[c.parent])
      .map((c) => ({ id: "h::" + c.id, from: c.parent, to: c.id, dashes: true,
        color: { color: "#44556699" }, width: 1, smooth: false }));
    const eMax = Math.max(...data.edges.map((e) => e.w), 1);
    const coocc = data.edges.map((e, i) => ({
      id: "e" + i, from: e.a, to: e.b, value: e.w,
      // 볼륨성(기대 대비 <1.5배) 엣지는 가늘게 — 큰 테마끼리의 우연 동시등장과
      // 진짜 특이 연관(lift 높음)을 시각적으로 구분
      width: e.weak ? 1 : e.volume_only ? 1.5 : 1 + 9 * (e.w / eMax),
      dashes: e.weak ? [4, 6] : false,   // 약한 연결(표본 적음)은 점선
      color: { color: e.weak ? "#66779955" : e.volume_only ? "#66779944" : "#8899bb55", highlight: "#5AC8FA" },
      title: e.summary ? e.summary.slice(0, 60) + (e.summary.length > 60 ? "…" : "") : undefined,
    }));

    const net = new Network(canvasRef.current, { nodes: visNodes, edges: [...containment, ...coocc] }, {
      physics: { barnesHut: { gravitationalConstant: -16000, centralGravity: 0.3, springLength: 150 }, stabilization: { iterations: 250 } },
      interaction: { hover: true },
      nodes: { shape: "dot" },
    });
    netRef.current = net;

    // collapse each parent + its children into ONE blob (zoom out = 큰 덩어리)
    const clusterParent = (pid) => {
      const cid = CLUSTER_PREFIX + pid;
      if (net.isCluster(cid)) return;     // already collapsed -> skip (avoids "Node does not exist")
      const p = byId[pid];
      net.cluster({
        joinCondition: (opt) => opt.id === pid || opt.parent === pid,
        clusterNodeProperties: {
          id: CLUSTER_PREFIX + pid, label: p.label, shape: "dot",
          color: parentColor[pid] || "#789", value: p.heat ?? p.freq,
          scaling: { min: 18, max: 64 },
          font: { size: 22, color: "#fff", strokeWidth: 3, strokeColor: "#0b0f1a" },
        },
      });
    };
    const collapseAll = () => parents.forEach((p) => clusterParent(p.id));

    // 물리 동결 후에도 잔잔하게 열리도록: 자식들을 부모 주위 결정론적 링으로 배치
    // (물리 재가동 없음 — "클릭하면 미친듯이 튀는" 문제의 해결책)
    const openCalm = (cid) => {
      if (!net.isCluster(cid)) return;
      let cpos = { x: 0, y: 0 };
      try { cpos = net.getPositions([cid])[cid] || cpos; } catch (e) { /* none */ }
      try {
        net.openCluster(cid, {
          releaseFunction: (clusterPos, contained) => {
            const p = clusterPos || cpos;
            const ids = Object.keys(contained).sort();
            const pid = ids.find((i) => byId[i]?.level === 0);
            const kids = ids.filter((i) => i !== pid);
            const R = 90 + kids.length * 7;
            const out = {};
            if (pid) out[pid] = { x: p.x, y: p.y };
            kids.forEach((i, k) => {
              const ang = (2 * Math.PI * k) / Math.max(1, kids.length);
              out[i] = { x: p.x + R * Math.cos(ang), y: p.y + R * Math.sin(ang) };
            });
            return out;
          },
        });
      } catch (e) { /* none */ }
    };

    let collapsed = true;       // current LOD state; only act on threshold CROSSINGS
    // open-threshold is set RELATIVE to the actual post-fit scale, not a fixed constant: the
    // fit scale depends on graph size + viewport, and a fixed 0.75 was unreachable in a few
    // wheel ticks (graph fit at ~0.26, so it looked frozen). openAt = fitScale * ZOOM_OPEN_MULT
    // always sits a few ticks above the start, so a small zoom-in expands. Falls back to a
    // constant until the fit lands.
    let openAt = ZOOM_OPEN;     // sensible default until we measure the fit
    net.once("stabilizationIterationsDone", () => {
      collapseAll();            // start collapsed: 부모 blob만 보임
      collapsed = true;
      // 초기 배치가 끝나면 물리를 영구 동결 — 이후의 모든 이동은 결정론적 배치(openCalm)만.
      // (물리가 계속 켜져 있으면 클러스터 개폐·클릭 때마다 그래프 전체가 요동)
      net.setOptions({ physics: false });
      // 급상승 top-3가 속한 부모만 자동 펼침 — 오늘의 변화가 접힌 채 숨지 않게
      const hotParents = new Set([...riserIds].map((id) => byId[id]?.parent || id));
      hotParents.forEach((pid) => openCalm(CLUSTER_PREFIX + pid));
      net.fit({ animation: true });
    });
    // after the fit animation settles, anchor the threshold just above the resting scale
    net.on("animationFinished", () => {
      if (collapsed) openAt = net.getScale() * ZOOM_OPEN_MULT;
    });

    // zoom-driven level of detail: cross openAt going up -> expand ALL blobs to children;
    // cross going down -> re-collapse. Act once per crossing (not every wheel tick) to avoid
    // open/close fighting itself. (the user's "줌아웃=blob, 줌인=세부 노드")
    net.on("zoom", (p) => {
      if (p.scale >= openAt && collapsed) {
        collapsed = false;
        parents.forEach((par) => openCalm(CLUSTER_PREFIX + par.id));
      } else if (p.scale < openAt && !collapsed) {
        collapsed = true;
        collapseAll();
      }
    });

    net._openCalm = openCalm;   // focusNode (컴포넌트 스코프) 가 재사용

    net.on("click", (p) => {
      if (p.nodes.length) {
        let id = p.nodes[0];
        if (typeof id === "string" && id.startsWith(CLUSTER_PREFIX)) {
          // clicking a collapsed blob opens it (calmly) AND shows the parent panel
          const pid = id.slice(CLUSTER_PREFIX.length);
          openCalm(id);
          setTrail([]); setSel({ kind: "node", id: pid });
          return;
        }
        setTrail([]); setSel({ kind: "node", id });
      } else if (p.edges.length) {
        const eid = p.edges[0];
        if (typeof eid === "string" && eid.startsWith("e")) {
          const idx = parseInt(eid.slice(1));
          const e = data.edges[idx];
          if (e) { setTrail([]); setSel({ kind: "edge", a: e.a, b: e.b }); }
        }
      }
    });
    return () => net.destroy();
  }, [data]);

  if (!data) return <div className="loading">불러오는 중…</div>;

  // riser 클릭 → 해당 클러스터 열고 노드 포커스 + 패널 열기
  const focusNode = (id) => {
    const net = netRef.current;
    const n = byId[id];
    if (!net || !n) return;
    const cid = CLUSTER_PREFIX + (n.level === 1 ? n.parent : id);
    try { if (net._openCalm) net._openCalm(cid); } catch (e) { /* none */ }
    try { net.focus(id, { scale: 0.9, animation: true }); } catch (e) { /* none */ }
    setTrail([]); setSel({ kind: "node", id });
  };

  // 랜딩 = 급상승 랭킹 (인사이트 우선). rising이 비면 열기(heat) 상위로 폴백 + 정직한 라벨.
  const risingRows = (data.rising || []).map((r) => ({ ...r, fallback: false }));
  const fallbackRows = risingRows.length ? [] :
    [...data.nodes].sort((a, b) => (b.heat || 0) - (a.heat || 0)).slice(0, 8)
      .map((n) => ({ id: n.id, label: n.label, surge: null, recent_n: n.recent_n,
                     why: n.heads?.[0]?.t || "", fallback: true }));

  // resolve current selection into panel content
  let panel = null;
  if (!sel) {
    const rows = risingRows.length ? risingRows : fallbackRows;
    panel = (
      <>
        <h2>{risingRows.length ? "🔥 지금 뜨는 이슈" : "이슈 열기 순위"}</h2>
        <div className="sub">
          {risingRows.length
            ? "최근 2일 뉴스량이 직전 1주 대비 급증한 이슈 (관측 · 신호 아님)"
            : "급상승 이슈 없음(뉴스량 안정) — 최근 가중 열기 순위를 표시"}
        </div>
        {rows.map((r, k) => (
          <div key={r.id} className="riser" onClick={() => focusNode(r.id)}>
            <span className="rank">#{k + 1}</span>
            <div className="body">
              <span style={{ fontWeight: 600 }}>{r.label}</span>
              {r.surge != null && <span className="burst">▲ ×{r.surge}</span>}
              {r.recent_n != null && <span style={{ color: "#667", fontSize: 12 }}> · 최근 {r.recent_n}건</span>}
              {r.why && <div className="why">{r.why}</div>}
            </div>
          </div>
        ))}
        <div className="legend" style={{ marginTop: 12 }}>
          왼쪽 그래프: 휠로 <b>확대</b>하면 큰 덩어리가 세부 이슈로 펼쳐집니다. 점 클릭 →
          그 이슈의 요약·긍부정·관련 종목(오늘 등락 포함)·헤드라인.
        </div>
      </>
    );
  } else if (sel.kind === "node") {
    const n = byId[sel.id];
    if (!n) { panel = <div className="legend">…</div>; }
    else {
      const kids = data.nodes.filter((c) => c.level === 1 && c.parent === n.id);
      const goEdge = (otherId) => { setTrail([...trail, { label: n.label }]); const e = edgeBetween(n.id, otherId); if (e) setSel({ kind: "edge", a: e.a, b: e.b }); };
      const goEnt = (ent) => { setTrail([...trail, { label: n.label }]); setSel({ kind: "ent", ent, themeLabel: n.label }); };
      const goChild = (cid) => { setTrail([...trail, { label: n.label }]); setSel({ kind: "node", id: cid }); };
      panel = (
        <>
          <Crumbs trail={trail} />
          <h2>{n.label}{n.level === 1 && n.parent && byId[n.parent] && <span style={{ fontSize: 13, color: "#789" }}> · {byId[n.parent].label}</span>}</h2>
          <div className="sub">뉴스 {n.freq}건 · <span style={{ color: "#FFD93D" }}>지금 열기 {n.heat}</span> <span style={{ color: "#667" }}>(최근 가중)</span></div>
          {n.isolated && <div className="legend">⚪ 이 이슈는 현재 코퍼스에서 다른 이슈와의 동시등장 표본이 부족해 연결선이 없습니다 (강제 연결 대신 정직한 공백).</div>}
          {n.summary && <div className="summary"><span className="tag">📝 무슨 얘기인가 ({data.summary_date || "최근"} 기준)</span>{n.summary}</div>}
          <StanceBar stance={n.stance} />
          <TrendChart trend={n.trend} />
          {kids.length > 0 && <>
            <div className="seclabel">세부 이슈 (클릭 → 들어가기)</div>
            <div className="chips">{kids.sort((a, b) => b.heat - a.heat).map((c) => <span key={c.id} className="chip" onClick={() => goChild(c.id)}>{c.label} <span style={{ color: "#8ab" }}>{Math.round(c.heat)}</span></span>)}</div>
          </>}
          {n.related?.length > 0 && <>
            <div className="seclabel">자주 엮이는 이슈 (클릭 → 연결 의미)</div>
            <div className="chips">{n.related.map((r) => <span key={r.id} className="chip" onClick={() => goEdge(r.id)}>{r.label} <span style={{ color: "#8ab" }}>{r.w}</span></span>)}</div>
          </>}
          {n.entities?.length > 0 && <>
            <div className="seclabel">이슈 → 종목 → 가격 (오늘 등락 · 클릭 → 이 기업 뉴스)</div>
            <div className="chips">
              {[...n.entities].sort((a, b) => Math.abs(b.chg ?? 0) - Math.abs(a.chg ?? 0)).map((e, i) => (
                <span key={i} className="chip" onClick={() => goEnt(e)}>
                  {e.name} <span style={{ color: "#8ab" }}>{e.n}</span>
                  {e.chg != null && (
                    <b className={e.chg >= 0 ? "pos" : "neg"} style={{ marginLeft: 4 }}>
                      {(e.chg >= 0 ? "+" : "") + (e.chg * 100).toFixed(1)}%
                    </b>
                  )}
                </span>
              ))}
            </div>
          </>}
          <div className="seclabel">근거 헤드라인</div>
          <Heads heads={n.heads} />
        </>
      );
    }
  } else if (sel.kind === "edge") {
    const e = edgeBetween(sel.a, sel.b);
    panel = (
      <>
        <Crumbs trail={trail} />
        <h2>{byId[sel.a]?.label} ↔ {byId[sel.b]?.label}</h2>
        <div className="sub">
          같은 기사에 {e?.w}건 함께 등장
          {e?.lift != null && <> · 우연 기대 대비 <b style={{ color: e.lift >= 3 ? "#FFD93D" : e.lift >= 1.5 ? "#9fd" : "#889" }}>{e.lift}배</b></>}
          {e?.volume_only && <span style={{ color: "#889" }}> (볼륨성 — 특이 연관 약함)</span>}
        </div>
        {e?.summary && <div className="summary"><span className="tag">📝 어떻게 엮이나</span>{e.summary}</div>}
        {e && <StanceBar stance={e.stance} />}
        <div className="seclabel">함께 다룬 헤드라인</div>
        <Heads heads={e?.heads} />
      </>
    );
  } else if (sel.kind === "ent") {
    panel = (
      <>
        <Crumbs trail={trail} />
        <h2>{sel.ent.name}</h2>
        <div className="sub">{sel.themeLabel} 맥락의 뉴스 {sel.ent.n}건</div>
        <div className="seclabel">이 기업 헤드라인</div>
        <Heads heads={sel.ent.heads} />
      </>
    );
  }

  return (
    <div className="split">
      <div className="canvas" ref={canvasRef} style={{ position: "relative" }}>
        <div style={{ position: "absolute", top: 12, left: 16, zIndex: 1, color: "#99a", fontSize: 13, background: "#11161fcc", padding: "8px 12px", borderRadius: 8, pointerEvents: "none" }}>
          🔍 휠로 확대 → 큰 이슈가 세부 이슈로 펼쳐집니다 · 점 클릭 → 뉴스
        </div>
      </div>
      <div className="panel">{panel}</div>
    </div>
  );
}

function Crumbs({ trail }) {
  if (trail.length < 1) return null;
  return <div className="crumbs">{trail.map((t, i) => <span key={i}>{t.label} ▸ </span>)}</div>;
}
