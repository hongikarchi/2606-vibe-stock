import React, { useEffect, useMemo, useRef, useState } from "react";
import { BridgeRow, IssuerPanel } from "./shared.jsx";

// ---------------------------------------------------------------- squarify (Bruls)
// Deterministic: input sorted desc by weight (name tiebreak); greedy worst-aspect-ratio.
// Layout is computed ONCE in world coordinates (memoized); zoom/pan are a view transform,
// never a relayout.
function squarify(items, x, y, w, h) {
  const out = [];
  const total = items.reduce((s, t) => s + t.w, 0) || 1;
  let rest = items.map((t) => ({ ...t, a: (t.w * w * h) / total })).filter((t) => t.a > 0.4);
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

// diverging chg color: ±3% fixed domain (finviz), gray midpoint, desaturated poles
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

const SECHDR = 20, INDHDR = 13, SPAD = 3, IPAD = 2;

export default function MarketMapView({ useArtifact }) {
  const d = useArtifact("graph");
  const wrapRef = useRef(null);
  const [mkt, setMkt] = useState("KR");
  const [sel, setSel] = useState(null);
  const [size, setSize] = useState({ w: 800, h: 560 });
  const [view, setView] = useState({ k: 1, tx: 0, ty: 0 });   // zoom scale + pan
  const drag = useRef(null);

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

  // reset view on market switch / resize
  useEffect(() => { setView({ k: 1, tx: 0, ty: 0 }); }, [mkt, size.w, size.h]);

  const byName = useMemo(
    () => (d ? Object.fromEntries(d.issuers.map((i) => [i.name, i])) : {}), [d]);

  // 2-level layout: sector (finviz 11) -> industry -> stock cell. World coords, memoized.
  const layout = useMemo(() => {
    if (!d) return null;
    const inMkt = d.issuers.filter((i) =>
      mkt === "KR" ? i.iid.startsWith("DART") : i.iid.startsWith("CIK"));
    const caps = inMkt.map((i) => i.mktcap).filter((v) => v > 0);
    if (!caps.length) return { sectors: [], missing: inMkt.length, n: inMkt.length };
    const minCap = Math.min(...caps);
    const missing = inMkt.filter((i) => !(i.mktcap > 0)).length;

    // group by sector_l1 -> industry
    const secMap = new Map();
    for (const i of inMkt) {
      const sec = i.sector_l1 || "기타";
      const ind = i.industry || sec;
      if (!secMap.has(sec)) secMap.set(sec, new Map());
      const im = secMap.get(sec);
      if (!im.has(ind)) im.set(ind, []);
      im.get(ind).push({ key: i.name, w: i.mktcap > 0 ? i.mktcap : minCap, i });
    }
    const capW = (cells) => cells.reduce((s, c) => s + (c.i.chg != null ? c.w : 0), 0);
    const capChg = (cells) => {
      const cw = capW(cells);
      return cw > 0 ? cells.reduce((s, c) => s + (c.i.chg != null ? c.w * c.i.chg : 0), 0) / cw : null;
    };
    const sectors = [...secMap.entries()].map(([name, im]) => {
      const inds = [...im.entries()].map(([iname, cells]) => {
        cells.sort((a, b) => b.w - a.w || a.key.localeCompare(b.key));
        return { name: iname, cells, w: cells.reduce((s, c) => s + c.w, 0), chg: capChg(cells) };
      }).sort((a, b) => b.w - a.w || a.name.localeCompare(b.name));
      const all = inds.flatMap((x) => x.cells);
      return { name, inds, w: all.reduce((s, c) => s + c.w, 0), chg: capChg(all) };
    }).sort((a, b) => b.w - a.w || a.name.localeCompare(b.name));

    // level 1: sectors over the canvas
    const secR = squarify(sectors.map((s) => ({ key: s.name, w: s.w, s })), 0, 0, size.w, size.h);
    for (const r of secR) {
      const s = r.s;
      s.x = r.x; s.y = r.y; s.rw = r.w; s.rh = r.h;
      const ix = r.x + SPAD, iy = r.y + SECHDR,
            iw = Math.max(0, r.w - 2 * SPAD), ih = Math.max(0, r.h - SECHDR - SPAD);
      // level 2: industries inside the sector
      const indR = iw > 6 && ih > 6
        ? squarify(s.inds.map((n) => ({ key: n.name, w: n.w, n })), ix, iy, iw, ih) : [];
      for (const ir of indR) {
        const n = ir.n;
        n.x = ir.x; n.y = ir.y; n.rw = ir.w; n.rh = ir.h;
        const hasHdr = ir.w > 46 && ir.h > 34;   // industry header only when it fits
        const jy = ir.y + (hasHdr ? INDHDR : IPAD);
        const jw = Math.max(0, ir.w - 2 * IPAD);
        const jh = Math.max(0, ir.h - (hasHdr ? INDHDR : IPAD) - IPAD);
        n.hasHdr = hasHdr;
        // level 3: stock cells
        n.cellRects = jw > 3 && jh > 3
          ? squarify(n.cells.map((c) => ({ key: c.key, w: c.w, i: c.i })),
                     ir.x + IPAD, jy, jw, jh) : [];
      }
    }
    return { sectors, missing, n: inMkt.length };
  }, [d, mkt, size]);

  if (!d) return <div className="loading">불러오는 중…</div>;

  const cells = [];
  for (const s of layout.sectors) for (const n of (s.inds || [])) for (const c of (n.cellRects || [])) cells.push(c);
  const centroids = {};
  for (const c of cells) centroids[c.key] = [c.x + c.w / 2, c.y + c.h / 2];

  const bridges = (d.bridges || []).filter((b) => b.verified);
  const drawable = bridges.filter((b) => centroids[b.a] && centroids[b.b]);
  const bridgeEnds = new Set(drawable.flatMap((b) => [b.a, b.b]));

  const movers = cells.map((c) => c.i).filter((i) => i.chg != null).sort((a, b) => b.chg - a.chg);
  const top5 = movers.slice(0, 5), bot5 = movers.slice(-5).reverse();

  // ---- zoom / pan ----
  const { k, tx, ty } = view;
  const clamp = (v) => ({
    k: v.k,
    tx: Math.min(0, Math.max(size.w * (1 - v.k), v.tx)),
    ty: Math.min(0, Math.max(size.h * (1 - v.k), v.ty)),
  });
  const onWheel = (e) => {
    e.preventDefault();
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const k2 = Math.min(12, Math.max(1, k * (e.deltaY < 0 ? 1.2 : 1 / 1.2)));
    setView(clamp({ k: k2, tx: mx - (mx - tx) * (k2 / k), ty: my - (my - ty) * (k2 / k) }));
  };
  const onDown = (e) => { drag.current = { x: e.clientX, y: e.clientY, tx, ty, moved: false }; };
  const onMove = (e) => {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
    setView((v) => clamp({ k: v.k, tx: drag.current.tx + dx, ty: drag.current.ty + dy }));
  };
  const onUp = () => { drag.current = null; };
  const clickCell = (name) => { if (!drag.current?.moved) setSel({ type: "issuer", name }); };
  const reset = () => setView({ k: 1, tx: 0, ty: 0 });

  // labels drawn in an UNTRANSFORMED layer, gated on EFFECTIVE (on-screen) size
  const P = (x, y) => [x * k + tx, y * k + ty];
  const onScreen = (c) => {
    const [sx, sy] = P(c.x, c.y);
    return sx + c.w * k > 0 && sx < size.w && sy + c.h * k > 0 && sy < size.h;
  };

  // ---- panel (unchanged behaviors) ----
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
          <b>{n}</b> · {byName[n].industry || byName[n].sector || "?"}
          {byName[n].chg != null && <> · 오늘 <span className={byName[n].chg >= 0 ? "pos" : "neg"}>{fmtPct(byName[n].chg)}</span></>}
        </div>
      ))}
    </>
  ) : (
    <>
      <h2>🗺️ 시장지도</h2>
      <div className="sub">섹터→산업 2단계 · 크기=시가총액 · 색=오늘 등락 · <span style={{ color: "#FFD93D" }}>금색=검증된 연결</span></div>
      <div className="legend">
        finviz처럼 섹터(기술·헬스케어…) 안에 산업(반도체·소프트웨어…)으로 묶었습니다.
        <b> 휠로 확대 · 드래그로 이동</b>하면 작은 기업 이름도 보입니다. 셀 클릭 → 그 기업 상세.
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
        {bridges.map((b, kk) => (
          <div key={kk} onClick={() => setSel({ type: "bridge", b })} style={{ cursor: "pointer" }}>
            <BridgeRow b={b} onSelect={(n) => setSel({ type: "issuer", name: n })} canSelect={(n) => !!byName[n]} />
          </div>
        ))}
      </>}
      {layout.missing > 0 && (
        <div className="legend" style={{ marginTop: 10 }}>시총 미확인 {layout.missing}곳은 최소 크기로 표시.</div>
      )}
    </>
  );

  return (
    <div className="split">
      <div className="canvas" ref={wrapRef} style={{ position: "relative", overflow: "hidden" }}>
        <div className="mmap-toggle">
          {["KR", "US"].map((m) => (
            <button key={m} className={m === mkt ? "on" : ""} onClick={() => { setMkt(m); setSel(null); }}>
              {m === "KR" ? "🇰🇷 한국" : "🇺🇸 미국"}
            </button>
          ))}
          {k > 1 && <button onClick={reset} title="원래 크기로">⤢ 리셋</button>}
        </div>
        <svg width={size.w} height={size.h} style={{ display: "block", cursor: drag.current ? "grabbing" : "grab" }}
             onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove}
             onMouseUp={onUp} onMouseLeave={onUp}>
          {/* transformed world: rects + bridges */}
          <g transform={`translate(${tx},${ty}) scale(${k})`}>
            {layout.sectors.map((s) => (
              <g key={s.name}>
                <rect x={s.x} y={s.y} width={s.rw} height={s.rh} fill="#0e1420" stroke="#2a3550" strokeWidth={1.5 / k} />
                {(s.inds || []).map((n) => (
                  <g key={n.name}>
                    {n.hasHdr && <rect x={n.x} y={n.y} width={n.rw} height={n.rh} fill="none" stroke="#1c2740" strokeWidth={0.8 / k} />}
                    {(n.cellRects || []).map((c) => (
                      <g key={c.key} className="cell" onClick={() => clickCell(c.i.name)}>
                        <rect x={c.x} y={c.y} width={c.w} height={c.h} fill={colorFor(c.i.chg)}
                              stroke={bridgeEnds.has(c.i.name) ? "#FFD93D" : "#0b0f1a"}
                              strokeWidth={(bridgeEnds.has(c.i.name) ? 2 : 1.2) / k} rx={2 / k} />
                        <title>{c.i.name} · {c.i.industry || c.i.sector || "?"} · 시총 {fmtCap(c.i.mktcap, c.i.ccy)}{c.i.chg != null ? ` · ${fmtPct(c.i.chg)}` : " · 등락 없음"}</title>
                      </g>
                    ))}
                  </g>
                ))}
              </g>
            ))}
            <g>
              {drawable.map((b, kk) => {
                const [x1, y1] = centroids[b.a], [x2, y2] = centroids[b.b];
                const on = sel?.type === "bridge" && sel.b === b;
                return (
                  <g key={kk} onClick={() => setSel({ type: "bridge", b })} style={{ cursor: "pointer" }}>
                    <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={12 / k} />
                    <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#FFD93D" strokeWidth={(on ? 3 : 2) / k}
                          strokeDasharray={`${6 / k} ${6 / k}`} />
                    <title>검증된 연결: {b.label} · r={b.r} · z={b.z}σ</title>
                  </g>
                );
              })}
            </g>
          </g>
          {/* UNTRANSFORMED label layer: constant screen-size text, gated on effective size */}
          <g style={{ pointerEvents: "none" }}>
            {layout.sectors.filter((s) => s.rw * k > 70).map((s) => {
              const [px, py] = P(s.x, s.y);
              return (
                <text key={s.name} x={Math.max(4, px) + 4} y={Math.max(12, py + 14)} fontSize="12"
                      fill="#9fb6d0" style={{ fontWeight: 700 }}>
                  {s.name}{s.chg != null && <tspan fill={s.chg >= 0 ? "#6BCB77" : "#FF6B6B"}> {fmtPct(s.chg)}</tspan>}
                </text>
              );
            })}
            {cells.filter((c) => c.w * k >= 46 && c.h * k >= 26 && onScreen(c)).map((c) => {
              const [px, py] = P(c.x, c.y);
              const ew = c.w * k, eh = c.h * k;
              const showPct = eh >= 42 && c.i.chg != null;
              const fs = ew >= 92 && eh >= 54 ? 13 : 11;
              const maxCh = Math.max(2, Math.floor((ew - 6) / (fs * 0.62)));
              const nm = c.i.name.length > maxCh ? c.i.name.slice(0, maxCh - 1) + "…" : c.i.name;
              return (
                <g key={c.key}>
                  <text x={px + ew / 2} y={py + eh / 2 + (showPct ? -3 : 4)} fontSize={fs}
                        textAnchor="middle" fill="#e8e8e8">{nm}</text>
                  {showPct && (
                    <text x={px + ew / 2} y={py + eh / 2 + 12} fontSize={fs - 1} textAnchor="middle"
                          fill={c.i.chg >= 0 ? "#a9e6b5" : "#ffb3b3"}>{fmtPct(c.i.chg)}</text>
                  )}
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
