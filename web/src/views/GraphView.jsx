import React, { useEffect, useRef } from "react";
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

export default function GraphView({ useArtifact }) {
  const d = useArtifact("graph");
  const ref = useRef(null);
  useEffect(() => {
    if (!d || !ref.current) return;
    const nodes = [], edges = [], sectorsSeen = new Set();
    const maxppr = Math.max(...d.issuers.map((i) => i.ppr || 0), 0.0001);
    for (const i of d.issuers) {
      const color = divColor(i.sic);
      nodes.push({ id: "I::" + i.name, label: i.name.slice(0, 22), color, value: i.ppr || 0,
        title: `${i.name}\n업종: ${i.sector || "?"}\nPPR=${(i.ppr || 0).toFixed(4)}`,
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
    return () => net.destroy();
  }, [d]);
  if (!d) return <div className="loading">불러오는 중…</div>;
  return (
    <div style={{ height: "100%", position: "relative" }}>
      <div style={{ position: "absolute", top: 12, left: 16, zIndex: 1, color: "#99a", fontSize: 13, background: "#11161fcc", padding: "8px 12px", borderRadius: 8 }}>
        상위 {d.issuers.length} 기업 (PageRank 순) · 색=업종 · 크기=중요도 · ★=거시지표
      </div>
      <div style={{ height: "100%" }} ref={ref} />
    </div>
  );
}
