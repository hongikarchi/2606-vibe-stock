import React, { useEffect, useRef, useState } from "react";
import { Network } from "vis-network/standalone";

// US SIC 2-digit division -> color (mirror of the Python _division)
const DIV = [
  [1, 9, "농림어업", "#6BCB77"], [10, 14, "광업", "#B5651D"], [15, 17, "건설", "#C19A6B"],
  [20, 39, "제조업", "#4D96FF"], [40, 49, "운수·통신·전기", "#9D4EDD"], [50, 51, "도매", "#00C2A8"],
  [52, 59, "소매", "#FF6B6B"], [60, 67, "금융·보험·부동산", "#FFD93D"], [70, 89, "서비스", "#FF9F45"],
  [90, 99, "공공행정", "#A0A0A0"],
];
function divColor(sic) {
  const mg = parseInt(String(sic || "").slice(0, 2));
  for (const [lo, hi, , c] of DIV) if (mg >= lo && mg <= hi) return c;
  return "#777";
}

function StanceBar({ stance }) {
  const tot = (stance.bull + stance.bear + stance.neut) || 1;
  const pb = Math.round((100 * stance.bull) / tot), pr = Math.round((100 * stance.bear) / tot);
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

export default function GraphView({ useArtifact }) {
  const d = useArtifact("graph");
  const ref = useRef(null);
  const [sel, setSel] = useState(null); // issuer name

  const byName = d ? Object.fromEntries(d.issuers.map((i) => [i.name, i])) : {};

  useEffect(() => {
    if (!d || !ref.current) return;
    const nodes = [], edges = [], sectorsSeen = new Set();
    for (const i of d.issuers) {
      const color = divColor(i.sic);
      nodes.push({ id: "I::" + i.name, label: i.name.slice(0, 22), color, value: i.ppr || 0,
        title: `${i.name}\n업종: ${i.sector || "?"}\n뉴스 ${i.news_count || 0}건`,
        scaling: { min: 8, max: 50 }, font: { size: 13, color: "#ddd" } });
      if (i.sector) {
        const sid = "S::" + i.sector;
        if (!sectorsSeen.has(sid)) {
          sectorsSeen.add(sid);
          nodes.push({ id: sid, label: i.sector.slice(0, 24), color: divColor(i.sic), shape: "square", size: 16, font: { size: 12, color: "#bbb" } });
        }
        edges.push({ from: "I::" + i.name, to: sid, color: { color: "#33415544" } });
      }
    }
    for (const m of d.macros) {
      nodes.push({ id: "M::" + m.id, label: m.name, color: "#fff", shape: "star", size: 18 + Math.min(m.news || 0, 40) * 0.5,
        title: `거시지표: ${m.name}\n뉴스 ${m.news}건` });
    }
    const net = new Network(ref.current, { nodes, edges }, {
      physics: { barnesHut: { gravitationalConstant: -8000, centralGravity: 0.3, springLength: 120 }, stabilization: { iterations: 250 } },
      interaction: { hover: true },
    });
    net.once("stabilizationIterationsDone", () => net.fit({ animation: true }));
    net.on("click", (p) => {
      if (p.nodes.length && p.nodes[0].startsWith("I::")) setSel(p.nodes[0].slice(3));
      else setSel(null);
    });
    return () => net.destroy();
  }, [d]);

  if (!d) return <div className="loading">불러오는 중…</div>;

  const i = sel ? byName[sel] : null;
  const panel = !i ? (
    <>
      <h2>기업을 클릭하세요</h2>
      <div className="sub">점=기업(색=업종, 크기=중요도) · 네모=업종 · ★=거시지표</div>
      <div className="legend">기업을 클릭하면 그 기업의 <b>뉴스·긍부정·관련 이슈·같은 업종 기업</b>이 여기 나옵니다. (이슈연관망이 '이슈 렌즈'라면 이건 '기업 렌즈')</div>
    </>
  ) : (
    <>
      <h2>{i.name}</h2>
      <div className="sub">
        {i.sector || "?"} · PPR #{i.rank}
        {i.pos != null && <> · 52주 위치 <b style={{ color: i.pos >= 70 ? "#6BCB77" : i.pos <= 30 ? "#FF6B6B" : "#aaa" }}>{Math.round(i.pos)}%</b></>}
      </div>
      <div className="sub">뉴스 {i.news_count || 0}건</div>
      {i.news_count > 0 && <StanceBar stance={i.stance} />}
      {i.ratings?.consensus?.n_analysts > 0 && (
        <div className="summary" style={{ borderColor: "#3a4a2a" }}>
          <span className="tag" style={{ color: "#9fd" }}>🏦 기관 동향 (관측 · 우리 추천 아님)</span>
          목표가 평균 <b>{Math.round(i.ratings.consensus.target_mean)}</b>
          {" "}(범위 {Math.round(i.ratings.consensus.target_low)}~{Math.round(i.ratings.consensus.target_high)})
          {" · "}애널리스트 {i.ratings.consensus.n_analysts}명{" · "}
          <span style={{ color: "#bcd" }}>{i.ratings.consensus.rating}</span>
          {i.ratings.changes?.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 13 }}>
              {i.ratings.changes.slice(0, 4).map((c, k) => (
                <div key={k} style={{ color: "#aab", marginTop: 3 }}>
                  <span style={{ color: "#778" }}>{c.date}</span> {c.firm} → <b>{c.to}</b>
                  {c.target ? ` ($${Math.round(c.target)})` : ""}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {i.themes?.length > 0 && <>
        <div className="seclabel">관련 이슈</div>
        <div className="chips">{i.themes.map((t) => <span key={t.id} className="chip">{t.label} <span style={{ color: "#8ab" }}>{t.n}</span></span>)}</div>
      </>}
      {i.peers?.length > 0 && <>
        <div className="seclabel">같은 업종 기업</div>
        <div className="chips">{i.peers.map((p, k) => <span key={k} className="chip" onClick={() => byName[p] && setSel(p)}>{p}</span>)}</div>
      </>}
      {i.heads?.length > 0 && <>
        <div className="seclabel">뉴스 헤드라인</div>
        {i.heads.map((h, k) => (
          <div key={k} className={"hd " + (h.s === "bullish" ? "b" : h.s === "bearish" ? "r" : "")}>
            <span className="dt">{h.d}</span><br />{h.t}
          </div>
        ))}
      </>}
    </>
  );

  return (
    <div className="split">
      <div className="canvas" ref={ref} style={{ position: "relative" }}>
        <div style={{ position: "absolute", top: 12, left: 16, zIndex: 1, color: "#99a", fontSize: 13, background: "#11161fcc", padding: "8px 12px", borderRadius: 8, pointerEvents: "none" }}>
          상위 {d.issuers.length} 기업 (PageRank 순) · 색=업종 · 크기=중요도 · ★=거시지표
        </div>
      </div>
      <div className="panel">{panel}</div>
    </div>
  );
}
