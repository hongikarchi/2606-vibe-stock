import React, { useEffect, useRef } from "react";
import { Network } from "vis-network/standalone";

const PALETTE = ["#4D96FF","#FF6B6B","#6BCB77","#FFD93D","#9D4EDD","#00C2A8","#FF9F45",
  "#5AC8FA","#F26430","#E84855","#14B8A6","#F59E0B","#7B61FF","#22C55E","#EC4899",
  "#A0A0A0","#94A3B8","#F97316","#10B981","#D946EF","#FBBF24"];

export default function EmergentView({ useArtifact }) {
  const d = useArtifact("emergent");
  const ref = useRef(null);
  useEffect(() => {
    if (!d || !ref.current) return;
    const maxdeg = Math.max(...d.terms.map((t) => t.deg || 1), 1);
    const nodes = d.terms.map((t) => ({
      id: t.term, label: t.term, value: t.deg,
      color: PALETTE[(t.cluster ?? 0) % PALETTE.length],
      title: `${t.term}\n연결 ${t.deg} · 뉴스 ${t.df}\n${t.spark || ""}`,
      font: { size: 16, color: "#fff", strokeWidth: 2, strokeColor: "#0b0f1a" },
      scaling: { min: 12, max: 50 },
    }));
    const maxw = Math.max(...d.edges.map((e) => e.w), 1);
    const edges = d.edges.map((e) => ({ from: e.a, to: e.b, value: e.w, width: 1 + 7 * (e.w / maxw), color: { color: "#8899bb44" } }));
    const net = new Network(ref.current, { nodes, edges }, {
      physics: { barnesHut: { gravitationalConstant: -14000, centralGravity: 0.35, springLength: 160 }, stabilization: { iterations: 200 } },
      interaction: { hover: true },
    });
    net.once("stabilizationIterationsDone", () => net.fit({ animation: true }));
    return () => net.destroy();
  }, [d]);
  if (!d) return <div className="loading">불러오는 중…</div>;
  return (
    <div style={{ height: "100%", position: "relative" }}>
      <div style={{ position: "absolute", top: 12, left: 16, zIndex: 1, color: "#99a", fontSize: 13, background: "#11161fcc", padding: "8px 12px", borderRadius: 8 }}>
        데이터에서 자동 추출한 키워드 · 색=클러스터 · 크기=연결 수 ({d.terms.length} 단어, {d.clusters} 클러스터)
      </div>
      <div style={{ height: "100%" }} ref={ref} />
    </div>
  );
}
