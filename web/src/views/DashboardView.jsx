import React from "react";

function Spark({ series }) {
  if (!series || series.length < 2) return null;
  const w = 160, h = 30, lo = Math.min(...series), hi = Math.max(...series), rng = hi - lo || 1;
  const pts = series.map((v, i) => `${((i / (series.length - 1)) * w).toFixed(1)},${(h - ((v - lo) / rng) * h).toFixed(1)}`).join(" ");
  const up = series[series.length - 1] >= series[0];
  return <svg width={w} height={h} style={{ verticalAlign: "middle" }}><polyline points={pts} fill="none" stroke={up ? "#6BCB77" : "#FF6B6B"} strokeWidth="1.5" /></svg>;
}

function Breadth({ label, b, color }) {
  if (!b) return null;
  return (
    <div className="row">
      <span className="lbl">{label} (n={b.n})</span>
      고점근처 <b className="pos">{b.hi}%</b>{" "}
      <span className="barbg"><span className="barfg" style={{ width: `${b.hi * 2}px`, background: "#6BCB77" }} /></span>{" "}
      저점근처 <b className="neg">{b.lo}%</b> · 중앙값 {b.med}%
    </div>
  );
}

export default function DashboardView({ useArtifact }) {
  const d = useArtifact("dashboard");
  if (!d) return <div className="loading">불러오는 중…</div>;
  return (
    <div className="dash">
      <h1 style={{ fontSize: 22 }}>📊 시장 상태 <span className="muted">(관측 · {d.as_of?.slice(0, 10)})</span></h1>
      <p className="muted">전부 '지금 시장이 어떤 상태인가'의 객관적 관측입니다. 예측·신호 아님 — 해석은 사람이.</p>

      <h2>시장 폭 (52주 위치) — 고점 근처가 많을수록 과열</h2>
      <Breadth label="🇺🇸 미국" b={d.us} />
      <Breadth label="🇰🇷 한국" b={d.kr} />

      <h2>원자재 · 지표 · 메모리 — 현재값 + 최근 추세</h2>
      <p className="muted">선 모양으로 '어느 방향으로 움직이는 중'인지 보세요.</p>
      <table><tbody>
        {d.macros.map((m, i) => (
          <tr key={i}>
            <td className="lbl">{m.name}</td><td>{m.px}</td>
            <td className={m.chg >= 0 ? "pos" : "neg"}>{(m.chg * 100).toFixed(1)}%</td>
            <td><Spark series={m.series} /></td>
          </tr>
        ))}
      </tbody></table>

      <h2>업종 열기 (평균 52주 위치)</h2>
      <table><tbody>
        <tr><td><b className="pos">🔥 뜨거운 업종</b></td><td><b className="neg">❄️ 식은 업종</b></td></tr>
        {d.hot.map((hr, i) => (
          <tr key={i}>
            <td>{hr.sector} <span className="muted">{hr.heat}%</span></td>
            <td>{d.cold[i] && <>{d.cold[i].sector} <span className="muted">{d.cold[i].heat}%</span></>}</td>
          </tr>
        ))}
      </tbody></table>

      <h2>지금 도는 이슈 (뉴스 자동 추출)</h2>
      <table><tbody>
        {d.terms.map((t, i) => (
          <tr key={i}><td className="lbl">{t.term}</td><td className="muted">연결 {t.deg}</td><td style={{ fontFamily: "monospace" }}>{t.spark}</td></tr>
        ))}
      </tbody></table>
    </div>
  );
}
