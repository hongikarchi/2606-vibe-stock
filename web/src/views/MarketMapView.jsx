import React, { useEffect, useMemo, useRef, useState } from "react";
import { BridgeRow, divName, IssuerPanel } from "./shared.jsx";

// ---------------------------------------------------------------- squarify (Bruls)
// Deterministic: input sorted desc by weight (name tiebreak); greedy worst-aspect-ratio.
// Same artifact => pixel-identical layout (unlike force physics).
function squarify(items, x, y, w, h) {
  const out = [];
  const total = items.reduce((s, t) => s + t.w, 0) || 1;
  let rest = items.map((t) => ({ ...t, a: (t.w * w * h) / total })).filter((t) => t.a > 0.5);
  while (rest.length) {
    const horiz = w >= h;
    const side = horiz ? h : w;
    const worst = (arr, sum) => {
      let mx = 0, mn = Infinity;
      for (const r of arr) { mx = Math.max(mx, r.a); mn = Math.min(mn, r.a); }
      const s2 = sum * sum, l2 = side * side;
      return Math.max((l2 * mx) / s2, s2 / (l2 * mn));
    };
    let row = [rest[0]], sum = rest[0].a, i = 1;
    while (i < rest.length && worst([...row, rest[i]], sum + rest[i].a) <= worst(row, sum)) {
      row.push(rest[i]); sum += rest[i].a; i++;
    }
    const thick = sum / side;
    let off = 0;
    for (const r of row) {
      const len = r.a / thick;
      out.push(horiz ? { ...r, x, y: y + off, w: thick, h: len }
                     : { ...r, x: x + off, y, w: len, h: thick });
      off += len;
    }
    if (horiz) { x += thick; w -= thick; } else { y += thick; h -= thick; }
    rest = rest.slice(i);
  }
  return out;
}

// diverging chg color: ±3% fixed domain (finviz convention), gray midpoint (a hue at the
// midpoint is an anti-pattern), desaturated poles — bright red/green stay for TEXT
function colorFor(chg) {
  if (chg == null) return "#232a37";
  const t = Math.max(-1, Math.min(1, chg / 0.03));
  const lerp = (a, b, u) => Math.round(a + (b - a) * u);
  const mid = [58, 66, 82], neg = [179, 71, 78], pos = [79, 158, 99];
  const c = t < 0 ? [0, 1, 2].map((k) => lerp(mid[k], neg[k], -t))
                  : [0, 1, 2].map((k) => lerp(mid[k], pos[k], t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

const fmtPct = (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%";
const fmtCap = (v, ccy) => {
  if (v == null) return "?";
  if (ccy === "KRW") return v >= 1e12 ? (v / 1e12).toFixed(1) + "조" : Math.round(v / 1e8) + "억";
  return v >= 1e12 ? "$" + (v / 1e12).toFixed(2) + "T" : "$" + (v / 1e9).toFixed(1) + "B";
};

const HEADER = 18, PAD = 3;

export default function MarketMapView({ useArtifact }) {
  const d = useArtifact("graph");
  const wrapRef = useRef(null);
  const [mkt, setMkt] = useState("KR");   // bridges are KR-KR today -> the differentiator lands on the landing view
  const [sel, setSel] = useState(null);   // {type:'issuer'|'bridge', ...}
  const [size, setSize] = useState({ w: 800, h: 560 });

  useEffect(() => {
    if (!wrapRef.current) return;
    const el = wrapRef.current;
    let tid = null;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(() => { clearTimeout(tid); tid = setTimeout(measure, 100); });
    ro.observe(el);
    return () => { ro.disconnect(); clearTimeout(tid); };
  }, [d]);

  const byName = useMemo(
    () => (d ? Object.fromEntries(d.issuers.map((i) => [i.name, i])) : {}), [d]);

  // layout: groups over the canvas, stocks inside each group (minus header band)
  const layout = useMemo(() => {
    if (!d) return null;
    const inMkt = d.issuers.filter((i) =>
      mkt === "KR" ? i.iid.startsWith("DART") : i.iid.startsWith("CIK"));
    const caps = inMkt.map((i) => i.mktcap).filter((v) => v > 0);
    if (!caps.length) return { groups: [], missing: inMkt.length, n: inMkt.length };
    const minCap = Math.min(...caps);
    const missing = inMkt.filter((i) => !(i.mktcap > 0)).length;
    const groupsMap = new Map();
    for (const i of inMkt) {
      const g = mkt === "KR" ? (i.sector || "기타") : divName(i.sic);
      if (!groupsMap.has(g)) groupsMap.set(g, []);
      groupsMap.get(g).push({ key: i.name, w: i.mktcap > 0 ? i.mktcap : minCap, i });
    }
    const groups = [...groupsMap.entries()]
      .map(([name, cells]) => {
        cells.sort((a, b) => b.w - a.w || a.key.localeCompare(b.key));
        const wsum = cells.reduce((s, c) => s + c.w, 0);
        const capw = cells.reduce((s, c) => s + (c.i.chg != null ? c.w : 0), 0);
        const gchg = capw > 0
          ? cells.reduce((s, c) => s + (c.i.chg != null ? c.w * c.i.chg : 0), 0) / capw
          : null;
        return { name, cells, w: wsum, chg: gchg };
      })
      .sort((a, b) => b.w - a.w || a.name.localeCompare(b.name));
    const rects = squarify(groups.map((g) => ({ key: g.name, w: g.w, g })),
                           0, 0, size.w, size.h);
    for (const r of rects) {
      const g = r.g;
      g.x = r.x; g.y = r.y; g.rw = r.w; g.rh = r.h;
      const ix = r.x + PAD, iy = r.y + HEADER, iw = Math.max(0, r.w - 2 * PAD),
            ih = Math.max(0, r.h - HEADER - PAD);
      g.cellRects = iw > 4 && ih > 4
        ? squarify(g.cells.map((c) => ({ key: c.key, w: c.w, i: c.i })), ix, iy, iw, ih)
        : [];
    }
    return { groups: rects.map((r) => r.g), missing, n: inMkt.length };
  }, [d, mkt, size]);

  if (!d) return <div className="loading">불러오는 중…</div>;

  const centroids = {};
  for (const g of layout.groups)
    for (const c of g.cellRects) centroids[c.key] = [c.x + c.w / 2, c.y + c.h / 2];

  const bridges = (d.bridges || []).filter((b) => b.verified);
  const drawable = bridges.filter((b) => centroids[b.a] && centroids[b.b]);

  const movers = layout.groups.flatMap((g) => g.cellRects.map((c) => c.i))
    .filter((i) => i.chg != null)
    .sort((a, b) => b.chg - a.chg);
  const top5 = movers.slice(0, 5), bot5 = movers.slice(-5).reverse();

  const selIssuer = sel?.type === "issuer" ? byName[sel.name] : null;
  const panel = selIssuer ? (
    <IssuerPanel i={selIssuer} bridges={d.bridges} onSelect={(n) => setSel({ type: "issuer", name: n })}
                 canSelect={(n) => !!byName[n]} />
  ) : sel?.type === "bridge" ? (
    <>
      <h2>검증된 연결</h2>
      <div className="sub">뉴스가 이어준 쌍을 가격 동조(시장·섹터 효과 제거 후)로 교차 검증 · 관측이지 신호 아님</div>
      <BridgeRow b={sel.b} onSelect={(n) => setSel({ type: "issuer", name: n })} canSelect={(n) => !!byName[n]} />
      {[sel.b.a, sel.b.b].map((n) => byName[n] && (
        <div key={n} className="hd" style={{ cursor: "pointer" }} onClick={() => setSel({ type: "issuer", name: n })}>
          <b>{n}</b> · {byName[n].sector || "?"}
          {byName[n].chg != null && <> · 오늘 <span className={byName[n].chg >= 0 ? "pos" : "neg"}>{fmtPct(byName[n].chg)}</span></>}
        </div>
      ))}
    </>
  ) : (
    <>
      <h2>🗺️ 시장지도</h2>
      <div className="sub">블록 크기=시가총액 · 색=오늘 등락 · <span style={{ color: "#FFD93D" }}>금색 점선=검증된 연결</span></div>
      <div className="legend">
        finviz처럼 시장 전체가 오늘 어디로 흐르는지 한눈에 — 여기에 섹터 지도가 못 보여주는
        <b> 숨은 연결</b>(뉴스 연결을 가격 동조로 검증한 쌍)을 겹쳐 보여줍니다. 셀 클릭 → 그 기업의 뉴스·이슈·기관동향.
      </div>
      {movers.length > 0 && <>
        <div className="seclabel">오늘 상승 Top 5</div>
        <div className="chips">{top5.map((i) => (
          <span key={i.name} className="chip" onClick={() => setSel({ type: "issuer", name: i.name })}>
            {i.name.slice(0, 14)} <span className="pos">{fmtPct(i.chg)}</span>
          </span>))}</div>
        <div className="seclabel">오늘 하락 Top 5</div>
        <div className="chips">{bot5.map((i) => (
          <span key={i.name} className="chip" onClick={() => setSel({ type: "issuer", name: i.name })}>
            {i.name.slice(0, 14)} <span className="neg">{fmtPct(i.chg)}</span>
          </span>))}</div>
      </>}
      {bridges.length > 0 && <>
        <div className="seclabel">검증된 연결 (뉴스 × 가격)</div>
        {bridges.map((b, k) => (
          <div key={k} onClick={() => setSel({ type: "bridge", b })} style={{ cursor: "pointer" }}>
            <BridgeRow b={b} onSelect={(n) => setSel({ type: "issuer", name: n })} canSelect={(n) => !!byName[n]} />
          </div>
        ))}
      </>}
      {layout.missing > 0 && (
        <div className="legend" style={{ marginTop: 10 }}>시총 미확인 {layout.missing}곳은 최소 크기·회색으로 표시.</div>
      )}
    </>
  );

  const bridgeEnds = new Set(drawable.flatMap((b) => [b.a, b.b]));

  return (
    <div className="split">
      <div className="canvas" ref={wrapRef} style={{ position: "relative", overflow: "hidden" }}>
        <div className="mmap-toggle">
          {["KR", "US"].map((m) => (
            <button key={m} className={m === mkt ? "on" : ""} onClick={() => { setMkt(m); setSel(null); }}>
              {m === "KR" ? "🇰🇷 한국" : "🇺🇸 미국"}
            </button>
          ))}
        </div>
        <svg width={size.w} height={size.h} style={{ display: "block" }}>
          {layout.groups.map((g) => (
            <g key={g.name}>
              <rect x={g.x} y={g.y} width={g.rw} height={g.rh} fill="none" stroke="#233" strokeWidth="1" />
              {g.rw > 60 && (
                <text x={g.x + 5} y={g.y + 13} fontSize="11" fill="#9fb6d0" style={{ fontWeight: 600 }}>
                  {g.name.slice(0, Math.floor((g.rw - 44) / 10))}
                  {g.chg != null && (
                    <tspan fill={g.chg >= 0 ? "#6BCB77" : "#FF6B6B"}> {fmtPct(g.chg)}</tspan>
                  )}
                </text>
              )}
              {g.cellRects.map((c) => {
                const i = c.i;
                const showName = c.w >= 52 && c.h >= 30;
                const showPct = showName && c.h >= 44 && i.chg != null;
                const big = c.w >= 110 && c.h >= 64;
                const fs = big ? 13 : 11;
                const maxCh = Math.max(1, Math.floor((c.w - 8) / fs));
                return (
                  <g key={c.key} className="cell" onClick={() => setSel({ type: "issuer", name: i.name })}>
                    <rect x={c.x} y={c.y} width={c.w} height={c.h} fill={colorFor(i.chg)}
                          stroke={bridgeEnds.has(i.name) ? "#FFD93D" : "#0b0f1a"}
                          strokeWidth={bridgeEnds.has(i.name) ? 2 : 2} rx="2" />
                    {showName && (
                      <text x={c.x + c.w / 2} y={c.y + c.h / 2 + (showPct ? -4 : 4)} fontSize={fs}
                            textAnchor="middle" fill="#e8e8e8" style={{ pointerEvents: "none" }}>
                        {i.name.length > maxCh ? i.name.slice(0, maxCh - 1) + "…" : i.name}
                      </text>
                    )}
                    {showPct && (
                      <text x={c.x + c.w / 2} y={c.y + c.h / 2 + 12} fontSize={fs - 1} textAnchor="middle"
                            fill={i.chg >= 0 ? "#a9e6b5" : "#ffb3b3"} style={{ pointerEvents: "none" }}>
                        {fmtPct(i.chg)}
                      </text>
                    )}
                    <title>{i.name} · {i.sector || "?"} · 시총 {fmtCap(i.mktcap, i.ccy)}{i.chg != null ? ` · ${fmtPct(i.chg)}` : " · 등락 데이터 없음"}{i.mktcap > 0 ? "" : " · 시총 데이터 없음"}</title>
                  </g>
                );
              })}
            </g>
          ))}
          <g>
            {drawable.map((b, k) => {
              const [x1, y1] = centroids[b.a], [x2, y2] = centroids[b.b];
              const on = sel?.type === "bridge" && sel.b === b;
              return (
                <g key={k} onClick={() => setSel({ type: "bridge", b })} style={{ cursor: "pointer" }}>
                  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth="12" />
                  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#FFD93D" strokeWidth={on ? 3 : 2}
                        strokeDasharray="6 6" />
                  <title>검증된 연결: {b.label} · r={b.r} · z={b.z}σ</title>
                </g>
              );
            })}
          </g>
        </svg>
        <div className="mmap-legend">
          {[-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03].map((v) => (
            <span key={v} style={{ background: colorFor(v) }}>{v === 0 ? "0" : (v > 0 ? "+" : "") + v * 100 + "%"}</span>
          ))}
          <span style={{ background: "#232a37" }}>없음</span>
        </div>
      </div>
      <div className="panel">{panel}</div>
    </div>
  );
}
