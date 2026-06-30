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
// expand once the user zooms to ~1.3x the resting (fit) scale — i.e. a small, deliberate zoom-in.
const ZOOM_OPEN_MULT = 1.3;

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

    // build all nodes (parents + children); children carry their parent's color
    const visNodes = data.nodes.map((n) => {
      const col = n.level === 0 ? (parentColor[n.id] || "#789") : (parentColor[n.parent] || "#789");
      return {
        id: n.id, label: n.label, value: n.heat ?? n.freq, level: n.level, parent: n.parent,
        color: col, shape: "dot",
        font: { size: n.level === 0 ? 20 : 15, color: "#fff", strokeWidth: 3, strokeColor: "#0b0f1a" },
        scaling: { min: n.level === 0 ? 16 : 10, max: n.level === 0 ? 60 : 34 },
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
      width: 1 + 9 * (e.w / eMax), color: { color: "#8899bb55", highlight: "#5AC8FA" },
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
        parents.forEach((par) => {
          const cid = CLUSTER_PREFIX + par.id;
          if (net.isCluster(cid)) { try { net.openCluster(cid); } catch (e) { /* none */ } }
        });
      } else if (p.scale < openAt && !collapsed) {
        collapsed = true;
        collapseAll();
      }
    });

    net.on("click", (p) => {
      if (p.nodes.length) {
        let id = p.nodes[0];
        if (typeof id === "string" && id.startsWith(CLUSTER_PREFIX)) {
          // clicking a collapsed blob opens it AND shows the parent panel
          const pid = id.slice(CLUSTER_PREFIX.length);
          if (net.isCluster(id)) net.openCluster(id);
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

  // resolve current selection into panel content
  let panel = null;
  if (!sel) {
    panel = (
      <>
        <h2>이슈 덩어리를 클릭하세요</h2>
        <div className="sub">큰 점=상위 이슈(AI·반도체…) · 줌인하면 세부 이슈로 갈라짐</div>
        <div className="legend">휠로 <b>확대</b>하면 큰 덩어리(예: AI/인공지능)가 <b>AI 인프라·AI 로봇·AI 거품</b> 같은 세부 이슈로 펼쳐집니다. 점을 클릭하면 그 이슈가 뉴스에서 <b>무슨 말을 하는지</b> — 긍정/부정·헤드라인·추세가 나옵니다.</div>
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
            <div className="seclabel">관련 기업 (클릭 → 이 기업 뉴스)</div>
            <div className="chips">{n.entities.map((e, i) => <span key={i} className="chip" onClick={() => goEnt(e)}>{e.name} <span style={{ color: "#8ab" }}>{e.n}</span></span>)}</div>
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
        <div className="sub">같은 기사에 {e?.w}건 함께 등장</div>
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
