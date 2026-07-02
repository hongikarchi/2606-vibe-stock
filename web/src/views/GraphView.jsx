import React, { useEffect, useRef, useState } from "react";
import { Network } from "vis-network/standalone";
import { BridgeRow, divColor, IssuerPanel } from "./shared.jsx";

// NOTE: this force-graph view is no longer wired to a tab (replaced by MarketMapView —
// deterministic treemap, mktcap sizing, bridges overlaid). File kept for cheap rollback,
// same pattern as the retired emergent view. Shared panel pieces live in shared.jsx.
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
    // 검증된 연결: 뉴스 bridge를 가격 동조(residual co-movement)로 확인한 쌍 (점선 금색)
    for (const b of d.bridges || []) {
      if (!b.verified) continue;
      const ka = "I::" + b.a, kb = "I::" + b.b;
      if (!byName[b.a] || !byName[b.b]) continue;
      edges.push({ from: ka, to: kb, dashes: [6, 6], width: 2.5, color: { color: "#FFD93D" },
        title: `검증된 연결: ${b.label}\nresidual r=${b.r} · z=${b.z}σ (섹터 기준선 대비)\n뉴스 연결을 가격 동조로 교차 검증 · 관측이지 신호 아님` });
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
      <div className="sub">점=기업(색=업종, 크기=중요도) · 네모=업종 · ★=거시지표 · <span style={{ color: "#FFD93D" }}>금색 점선=검증된 연결</span></div>
      <div className="legend">기업을 클릭하면 그 기업의 <b>뉴스·긍부정·관련 이슈·같은 업종 기업</b>이 여기 나옵니다.</div>
      {(d.bridges || []).length > 0 && <>
        <div className="seclabel">검증된 연결 (뉴스 × 가격 교차 검증)</div>
        {(d.bridges || []).map((b, k) => (
          <BridgeRow key={k} b={b} onSelect={setSel} canSelect={(n) => !!byName[n]} />
        ))}
      </>}
    </>
  ) : (
    <IssuerPanel i={i} bridges={d.bridges} onSelect={setSel} canSelect={(n) => !!byName[n]} />
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
