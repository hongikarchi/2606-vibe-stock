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

export default function ThemesView({ useArtifact }) {
  const data = useArtifact("themes");
  const canvasRef = useRef(null);
  const netRef = useRef(null);
  const [sel, setSel] = useState(null); // {kind:'node'|'edge'|'ent', ...}
  const [trail, setTrail] = useState([]);

  const byId = data ? Object.fromEntries(data.nodes.map((n) => [n.id, n])) : {};
  const edgeBetween = (a, b) => data?.edges.find((e) => (e.a === a && e.b === b) || (e.a === b && e.b === a));

  useEffect(() => {
    if (!data || !canvasRef.current) return;
    const nodes = data.nodes.map((n, i) => ({
      id: n.id, label: n.label, value: n.heat ?? n.freq,
      color: PALETTE[i % PALETTE.length], shape: "dot",
      font: { size: 20, color: "#fff", strokeWidth: 3, strokeColor: "#0b0f1a" },
      scaling: { min: 14, max: 60 },
    }));
    const eMax = Math.max(...data.edges.map((e) => e.w), 1);
    const edges = data.edges.map((e, i) => ({
      id: "e" + i, from: e.a, to: e.b, value: e.w,
      width: 1 + 9 * (e.w / eMax), color: { color: "#8899bb55", highlight: "#5AC8FA" },
    }));
    const net = new Network(canvasRef.current, { nodes, edges }, {
      physics: { barnesHut: { gravitationalConstant: -14000, centralGravity: 0.35, springLength: 170 }, stabilization: { iterations: 200 } },
      interaction: { hover: true },
      nodes: { shape: "dot" },
    });
    netRef.current = net;
    net.once("stabilizationIterationsDone", () => net.fit({ animation: true }));
    net.on("click", (p) => {
      if (p.nodes.length) { setTrail([]); setSel({ kind: "node", id: p.nodes[0] }); }
      else if (p.edges.length) {
        const idx = parseInt(p.edges[0].slice(1));
        const e = data.edges[idx];
        if (e) { setTrail([]); setSel({ kind: "edge", a: e.a, b: e.b }); }
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
        <h2>테마를 클릭하세요</h2>
        <div className="sub">점=이슈 · 선=같은 기사에 함께 등장</div>
        <div className="legend">클릭하면 그 이슈가 뉴스에서 <b>무슨 말을 하는지</b> — 긍정/부정 비율 + 실제 헤드라인 + 추세가 나옵니다.</div>
      </>
    );
  } else if (sel.kind === "node") {
    const n = byId[sel.id];
    const goEdge = (otherId) => { setTrail([...trail, { label: n.label }]); const e = edgeBetween(n.id, otherId); if (e) setSel({ kind: "edge", a: e.a, b: e.b }); };
    const goEnt = (ent) => { setTrail([...trail, { label: n.label }]); setSel({ kind: "ent", ent, themeLabel: n.label }); };
    panel = (
      <>
        <Crumbs trail={trail} setTrail={setTrail} setSel={setSel} />
        <h2>{n.label}</h2>
        <div className="sub">뉴스 {n.freq}건 · <span style={{ color: "#FFD93D" }}>지금 열기 {n.heat}</span> <span style={{ color: "#667" }}>(최근 가중)</span></div>
        {n.summary && <div className="summary"><span className="tag">📝 무슨 얘기인가 ({data.summary_date || "최근"} 기준)</span>{n.summary}</div>}
        <StanceBar stance={n.stance} />
        <TrendChart trend={n.trend} />
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
  } else if (sel.kind === "edge") {
    const e = edgeBetween(sel.a, sel.b);
    panel = (
      <>
        <Crumbs trail={trail} setTrail={setTrail} setSel={setSel} />
        <h2>{byId[sel.a].label} ↔ {byId[sel.b].label}</h2>
        <div className="sub">같은 기사에 {e.w}건 함께 등장</div>
        {e.summary && <div className="summary"><span className="tag">📝 어떻게 엮이나</span>{e.summary}</div>}
        <StanceBar stance={e.stance} />
        <div className="seclabel">함께 다룬 헤드라인</div>
        <Heads heads={e.heads} />
      </>
    );
  } else if (sel.kind === "ent") {
    panel = (
      <>
        <Crumbs trail={trail} setTrail={setTrail} setSel={setSel} />
        <h2>{sel.ent.name}</h2>
        <div className="sub">{sel.themeLabel} 맥락의 뉴스 {sel.ent.n}건</div>
        <div className="seclabel">이 기업 헤드라인</div>
        <Heads heads={sel.ent.heads} />
      </>
    );
  }

  return (
    <div className="split">
      <div className="canvas" ref={canvasRef} />
      <div className="panel">{panel}</div>
    </div>
  );
}

function Crumbs({ trail }) {
  if (trail.length < 1) return null;
  return <div className="crumbs">{trail.map((t, i) => <span key={i}>{t.label} ▸ </span>)}</div>;
}
