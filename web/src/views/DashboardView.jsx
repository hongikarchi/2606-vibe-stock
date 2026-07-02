import React from "react";

function Spark({ series }) {
  if (!series || series.length < 2) return null;
  const w = 160, h = 30, lo = Math.min(...series), hi = Math.max(...series), rng = hi - lo || 1;
  const pts = series.map((v, i) => `${((i / (series.length - 1)) * w).toFixed(1)},${(h - ((v - lo) / rng) * h).toFixed(1)}`).join(" ");
  const up = series[series.length - 1] >= series[0];
  return <svg width={w} height={h} style={{ verticalAlign: "middle" }}><polyline points={pts} fill="none" stroke={up ? "#6BCB77" : "#FF6B6B"} strokeWidth="1.5" /></svg>;
}

// 최대낙폭 바: 길이=낙폭 깊이, 전 화면 공통 스케일(섹션 간 비교 가능). MDD는 단방향 크기라
// 단일 색(먹색 레드) + 길이 — 숫자는 .neg 텍스트가 담당
function MddBar({ mdd }) {
  if (mdd == null) return <span className="muted">—</span>;
  const wpx = Math.min(180, Math.abs(mdd) * 300);
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      <span className="barbg" style={{ width: 120 }}>
        <span className="barfg" style={{ width: `${Math.min(120, wpx)}px`, background: "#a53a3a" }} />
      </span>{" "}
      <b className="neg">{(mdd * 100).toFixed(1)}%</b>
    </span>
  );
}

// underwater 스파크: 1년 고점 대비 낙폭 곡선 (0선 아래 면적)
function Underwater({ dd }) {
  if (!dd || dd.length < 2) return null;
  const w = 160, h = 30, lo = Math.min(...dd, -0.001);
  const y = (v) => (v / lo) * (h - 2);
  const pts = dd.map((v, i) => `${((i / (dd.length - 1)) * w).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} style={{ verticalAlign: "middle", background: "#0e131c", borderRadius: 4 }}>
      <polygon points={`0,0 ${pts} ${w},0`} fill="#FF6B6B22" />
      <polyline points={pts} fill="none" stroke="#FF6B6B" strokeWidth="1.5" />
    </svg>
  );
}

function Breadth({ label, b }) {
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

const fmtTurnover = (v, ccy) => {
  if (v == null) return "—";
  if (ccy === "KRW") return v >= 1e12 ? (v / 1e12).toFixed(1) + "조" : Math.round(v / 1e8).toLocaleString() + "억";
  return v >= 1e9 ? "$" + (v / 1e9).toFixed(1) + "B" : "$" + Math.round(v / 1e6) + "M";
};

function TurnoverTable({ title, rows }) {
  if (!rows || !rows.length) return null;
  return (
    <div>
      <div style={{ fontWeight: 600, margin: "6px 0" }}>{title}</div>
      <table><tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td className="muted">{i + 1}</td>
            <td>{r.name.length > 16 ? r.name.slice(0, 15) + "…" : r.name}</td>
            <td className="muted">{fmtTurnover(r.turnover, r.ccy)}</td>
            <td className={r.chg == null ? "muted" : r.chg >= 0 ? "pos" : "neg"}>
              {r.chg == null ? "—" : (r.chg >= 0 ? "+" : "") + (r.chg * 100).toFixed(1) + "%"}
            </td>
            <td><MddBar mdd={r.mdd} /></td>
          </tr>
        ))}
      </tbody></table>
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

      {d.index_mdd?.length > 0 && <>
        <h2>지수 최대낙폭 (최근 1년)</h2>
        <p className="muted">최대낙폭(MDD)=1년 내 고점→저점 최대 하락. '고점대비'는 지금 얼마나 내려와 있는지.</p>
        <table><tbody>
          {d.index_mdd.map((m, i) => (
            <tr key={i}>
              <td className="lbl">{m.name}</td>
              <td><MddBar mdd={m.mdd} /></td>
              <td className="muted" style={{ whiteSpace: "nowrap" }}>
                고점대비 <b className={m.curr_dd <= -0.05 ? "neg" : "muted"}>{(m.curr_dd * 100).toFixed(1)}%</b>
              </td>
              <td><Underwater dd={m.dd_series} /></td>
            </tr>
          ))}
        </tbody></table>
      </>}

      <h2>원자재 · 지표 · 메모리 — 현재값 + 추세 {d.mdd_window && <span className="muted">+ 최대낙폭({d.mdd_window})</span>}</h2>
      <p className="muted">선 모양으로 '어느 방향으로 움직이는 중'인지 보세요.</p>
      <table><tbody>
        {d.macros.map((m, i) => (
          <tr key={i}>
            <td className="lbl">{m.name}</td><td>{m.px}</td>
            <td className={m.chg >= 0 ? "pos" : "neg"}>{(m.chg * 100).toFixed(1)}%</td>
            <td><Spark series={m.series} /></td>
            <td>{m.mdd != null && <MddBar mdd={m.mdd} />}</td>
          </tr>
        ))}
      </tbody></table>

      {(d.turnover_top?.kr?.length > 0 || d.turnover_top?.us?.length > 0) && <>
        <h2>거래대금 상위 10 (오늘 돈이 도는 곳)</h2>
        <p className="muted">순위=거래대금 · 등락=당일 · 막대=1년 최대낙폭. 활발히 거래되는 종목이 얼마나 깊은 조정을 거쳤는지 함께 보세요.</p>
        <div className="duo">
          <TurnoverTable title="🇰🇷 한국" rows={d.turnover_top?.kr} />
          <TurnoverTable title="🇺🇸 미국" rows={d.turnover_top?.us} />
        </div>
      </>}

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
      <table className="terms"><tbody>
        {d.terms.map((t, i) => (
          <tr key={i}>
            <td className="lbl">{t.term}</td>
            <td className="muted">연결 {t.deg}</td>
            <td className="spark">{t.spark}</td>
          </tr>
        ))}
      </tbody></table>
    </div>
  );
}
