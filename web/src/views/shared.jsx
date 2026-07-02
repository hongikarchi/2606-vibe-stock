import React from "react";

// US SIC 2-digit division -> (label, color). Shared by GraphView (dot colors) and
// MarketMapView (treemap grouping). KR uses Korean sector names from the artifact directly.
export const DIV = [
  [1, 9, "농림어업", "#6BCB77"], [10, 14, "광업", "#B5651D"], [15, 17, "건설", "#C19A6B"],
  [20, 39, "제조업", "#4D96FF"], [40, 49, "운수·통신·전기", "#9D4EDD"], [50, 51, "도매", "#00C2A8"],
  [52, 59, "소매", "#FF6B6B"], [60, 67, "금융·보험·부동산", "#FFD93D"], [70, 89, "서비스", "#FF9F45"],
  [90, 99, "공공행정", "#A0A0A0"],
];

export function divColor(sic) {
  const mg = parseInt(String(sic || "").slice(0, 2));
  for (const [lo, hi, , c] of DIV) if (mg >= lo && mg <= hi) return c;
  return "#777";
}

export function divName(sic) {
  const mg = parseInt(String(sic || "").slice(0, 2));
  for (const [lo, hi, name] of DIV) if (mg >= lo && mg <= hi) return name;
  return "기타";
}

export function StanceBar({ stance }) {
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

// 검증된 연결(bridge) evidence row — 뉴스 연결을 가격 동조로 교차 검증한 결과 표시
export function BridgeRow({ b, onSelect, canSelect }) {
  const clickable = (name) => (canSelect ? canSelect(name) : true);
  return (
    <div className="hd" style={{ borderLeft: b.verified ? "3px solid #FFD93D" : "3px solid #445" }}>
      <b onClick={() => clickable(b.a) && onSelect && onSelect(b.a)} style={{ cursor: "pointer" }}>{b.a}</b>
      {" ↔ "}
      <b onClick={() => clickable(b.b) && onSelect && onSelect(b.b)} style={{ cursor: "pointer" }}>{b.b}</b>
      <span style={{ color: "#8ab" }}> · {b.label}</span><br />
      <span style={{ color: "#99a", fontSize: 12 }}>
        residual r={b.r > 0 ? "+" : ""}{b.r} · z={b.z}σ · {b.grade}
        {b.verified ? " — 뉴스 연결이 가격 동조로 교차 검증됨" : ""}
      </span>
    </div>
  );
}

// 기업 상세 패널 — GraphView와 MarketMapView가 공유하는 우측 패널 전체
// (stance/기관동향/관련이슈/검증된연결/동업종/헤드라인)
export function IssuerPanel({ i, bridges, onSelect, canSelect }) {
  const myBridges = (bridges || []).filter((b) => b.a === i.name || b.b === i.name);
  return (
    <>
      <h2>{i.name}</h2>
      <div className="sub">
        {i.sector || "?"}{i.rank ? <> · PPR #{i.rank}</> : null}
        {i.pos != null && <> · 52주 위치 <b style={{ color: i.pos >= 70 ? "#6BCB77" : i.pos <= 30 ? "#FF6B6B" : "#aaa" }}>{Math.round(i.pos)}%</b></>}
        {i.mdd != null && <> · 1년 최대낙폭 <b className="neg">{(i.mdd * 100).toFixed(1)}%</b></>}
      </div>
      <div className="sub">
        뉴스 {i.news_count || 0}건
        {i.chg != null && <> · 오늘 <b className={i.chg >= 0 ? "pos" : "neg"}>{(i.chg * 100).toFixed(1)}%</b></>}
      </div>
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
      {myBridges.length > 0 && <>
        <div className="seclabel">검증된 연결</div>
        {myBridges.map((b, k) => <BridgeRow key={k} b={b} onSelect={onSelect} canSelect={canSelect} />)}
      </>}
      {i.peers?.length > 0 && <>
        <div className="seclabel">같은 업종 기업</div>
        <div className="chips">{i.peers.map((p, k) => (
          <span key={k} className="chip" onClick={() => (canSelect ? canSelect(p) : true) && onSelect && onSelect(p)}>{p}</span>
        ))}</div>
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
}
