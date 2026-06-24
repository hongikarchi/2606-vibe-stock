import React, { useState, useEffect } from "react";
import ThemesView from "./views/ThemesView.jsx";
import DashboardView from "./views/DashboardView.jsx";
import GraphView from "./views/GraphView.jsx";

// 키워드망(emergent) tab removed — it answered the same question as 이슈 연관망 (issue
// associations) but auto-derived & noisier; the curated theme view won. The emergent
// pipeline (build_emergent.py) is kept as a keyword-discovery builder tool, not a view.
const TABS = [
  { id: "themes", label: "🧩 이슈 연관망", comp: ThemesView },
  { id: "dashboard", label: "📊 시장 상태", comp: DashboardView },
  { id: "graph", label: "🏢 기업 그래프", comp: GraphView },
];

// load a JSON artifact once and cache it
function useArtifact(name) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    fetch(`${import.meta.env.BASE_URL}data/${name}.json`)
      .then((r) => r.json())
      .then((d) => alive && setData(d))
      .catch((e) => console.error("load failed", name, e));
    return () => { alive = false; };
  }, [name]);
  return data;
}

export default function App() {
  const [tab, setTab] = useState("themes");
  const meta = useArtifact("meta");
  const Active = TABS.find((t) => t.id === tab).comp;

  return (
    <>
      <nav className="nav">
        <span className="brand">주식 지식그래프</span>
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
        {meta && (
          <span className="meta">
            {meta.nodes.toLocaleString()} 노드 · {meta.rels.toLocaleString()} 관계 · {meta.as_of?.slice(0, 10)} 기준
          </span>
        )}
      </nav>
      <div className="view">
        <Active useArtifact={useArtifact} />
      </div>
    </>
  );
}
