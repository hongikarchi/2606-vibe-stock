"""dashboard.py — a single READABLE market-state one-pager (out/dashboard.html).

The user has said twice that the node-graphs are hard to read. This is the opposite: a plain,
scannable dashboard of "지금 시장이 어떤 상태인가" — market breadth, commodity/memory prices,
hottest vs coldest sectors, and the live news themes — all descriptive observation, no signals.
Built from data already in the graph; no graph-reading required.
"""
from __future__ import annotations

from pathlib import Path

# KSIC (한국표준산업분류) 2-digit major-group -> Korean label, so KR sectors read as names
# instead of raw codes. Coarse but correct at the division level.
_KSIC2 = {
    "01": "농업", "03": "어업", "05": "석탄광업", "06": "원유·가스", "07": "금속광업",
    "10": "식료품", "11": "음료", "13": "섬유", "14": "의복", "16": "목재", "17": "펄프·종이",
    "18": "인쇄", "19": "석유정제", "20": "화학", "21": "의약품", "22": "고무·플라스틱",
    "23": "비금속광물", "24": "1차금속", "25": "금속가공", "26": "전자부품·반도체",
    "27": "의료·정밀기기", "28": "전기장비", "29": "기계·장비", "30": "자동차", "31": "운송장비",
    "32": "가구", "33": "기타제조", "35": "전기·가스", "36": "수도", "38": "폐기물",
    "41": "건설", "42": "토목", "46": "도매", "47": "소매", "49": "육상운송", "50": "수상운송",
    "51": "항공운송", "52": "창고·운송지원", "55": "숙박", "56": "음식점", "58": "출판",
    "59": "영상·방송", "61": "통신", "62": "소프트웨어", "63": "정보서비스", "64": "금융",
    "65": "보험", "66": "금융지원", "68": "부동산", "70": "연구개발", "71": "전문서비스",
    "72": "건축·엔지니어링", "73": "기타전문", "85": "교육", "86": "보건", "90": "예술",
}


def _ksic_name(code: str) -> str:
    return _KSIC2.get((code or "")[:2], f"기타({code})")


def _bar(pct: float, color: str, width: int = 200) -> str:
    w = int(max(0, min(100, pct)) / 100 * width)
    return (f'<span style="display:inline-block;width:{width}px;background:#1a2030;border-radius:4px;'
            f'vertical-align:middle"><span style="display:inline-block;height:14px;width:{w}px;'
            f'background:{color};border-radius:4px"></span></span>')


def _sparkline(series_json: str, w: int = 160, h: int = 30) -> str:
    """Inline SVG trend line from a JSON close array (answers '현재값만 있어 해석 어렵다' #6:
    shows the SHAPE of recent movement, not just the latest number). Green if up, red if down."""
    import json
    try:
        vals = [float(x) for x in json.loads(series_json or "[]")]
    except Exception:  # noqa: BLE001
        vals = []
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = " ".join(f"{i / (n - 1) * w:.1f},{h - (v - lo) / rng * h:.1f}" for i, v in enumerate(vals))
    color = "#6BCB77" if vals[-1] >= vals[0] else "#FF6B6B"
    return (f'<svg width="{w}" height="{h}" style="vertical-align:middle">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5"/></svg>')


def write_dashboard(repo, out_path: Path, as_of: str) -> dict:
    # --- market breadth (52w position) per market ---
    def breadth(prefix):
        rows = repo._read(
            f"MATCH (i:Issuer) WHERE i.issuer_id STARTS WITH '{prefix}' AND i.pos_52w IS NOT NULL "
            "RETURN i.pos_52w AS p")
        vals = [r["p"] for r in rows]
        if not vals:
            return None
        n = len(vals)
        return {"n": n, "hi": 100 * sum(v >= 80 for v in vals) / n,
                "lo": 100 * sum(v <= 20 for v in vals) / n,
                "med": sorted(vals)[n // 2]}
    us, kr = breadth("CIK"), breadth("DART")

    # --- commodity / macro prices + trend (recent_closes_json already on the node) ---
    macros = repo._read(
        "MATCH (m:MacroIndicator) RETURN m.name AS name, m.last_close AS px, "
        "m.pct_change_window AS chg, m.category AS cat, m.recent_closes_json AS series "
        "ORDER BY m.category, m.name")

    # --- hottest / coldest sectors by avg 52w position (KR KSIC + US SIC) ---
    sectors_raw = repo._read(
        "MATCH (i:Issuer)-[:IN_SECTOR]->(s:Sector) WHERE i.pos_52w IS NOT NULL "
        "WITH s.sector_id AS sid, s.name AS name, s.sic_code AS code, "
        "avg(i.pos_52w) AS heat, count(i) AS n WHERE n >= 4 "
        "RETURN sid, name, code, heat, n ORDER BY heat DESC")
    sectors = []
    for s in sectors_raw:
        # KR sectors are raw KSIC codes -> translate to Korean industry name
        label = _ksic_name(s["code"]) if str(s["sid"]).startswith("KSIC") else s["name"]
        sectors.append({"sector": label, "heat": s["heat"], "n": s["n"]})
    hot = sectors[:6]
    cold = sectors[-6:][::-1]

    # --- top live themes ---
    themes = repo._read("MATCH (t:Term) RETURN t.term AS term, t.degree AS deg, t.spark AS spark "
                        "ORDER BY t.degree DESC LIMIT 14")

    css = ("body{background:#0b0f1a;color:#e8e8e8;font-family:'Noto Sans KR',system-ui,sans-serif;"
           "max-width:1000px;margin:24px auto;padding:0 20px;line-height:1.6}"
           "h1{font-size:22px}h2{font-size:17px;color:#5AC8FA;border-bottom:1px solid #233;"
           "padding-bottom:4px;margin-top:28px}.row{margin:6px 0}.lbl{display:inline-block;"
           "width:200px}.pos{color:#6BCB77}.neg{color:#FF6B6B}.muted{color:#889}"
           "table{border-collapse:collapse;width:100%}td{padding:3px 8px}")

    h = [f"<!doctype html><html lang=ko><head><meta charset=utf-8><style>{css}</style></head><body>"]
    h.append(f"<h1>📊 시장 상태 대시보드 <span class=muted>(관측 · {as_of[:10]})</span></h1>")
    h.append("<p class=muted>전부 '지금 시장이 어떤 상태인가'의 객관적 관측입니다. 예측·신호 아님 — 해석은 사람이.</p>")

    # breadth
    h.append("<h2>시장 폭 (52주 위치) — 고점 근처 종목이 많을수록 과열</h2>")
    for label, b, color in [("🇺🇸 미국", us, "#4D96FF"), ("🇰🇷 한국", kr, "#FF6B6B")]:
        if not b:
            continue
        h.append(f"<div class=row><span class=lbl>{label} (n={b['n']})</span>"
                 f"고점근처 <b class=pos>{b['hi']:.0f}%</b> {_bar(b['hi'],'#6BCB77')} &nbsp; "
                 f"저점근처 <b class=neg>{b['lo']:.0f}%</b> &nbsp; 중앙값 {b['med']:.0f}%</div>")

    # commodities + macro: current value + 3mo change + TREND sparkline (#6: 흐름이 보이게)
    h.append("<h2>원자재 · 지표 · 메모리 — 현재값 + 최근 추세</h2>"
             "<p class=muted>숫자만이 아니라 선 모양으로 '어느 방향으로 움직이는 중'인지 보세요.</p><table>")
    for m in macros:
        chg = m["chg"] or 0
        cls = "pos" if chg >= 0 else "neg"
        spark = _sparkline(m.get("series"))
        h.append(f"<tr><td class=lbl>{m['name']}</td><td>{m['px']}</td>"
                 f"<td class={cls}>{chg:+.1%}</td><td>{spark}</td></tr>")
    h.append("</table>")

    # sectors
    h.append("<h2>업종 열기 (평균 52주 위치) — 어디가 뜨겁고 어디가 식었나</h2>")
    h.append("<table><tr><td><b class=pos>🔥 뜨거운 업종</b></td><td><b class=neg>❄️ 식은 업종</b></td></tr>")
    for hr, cr in zip(hot, cold):
        h.append(f"<tr><td>{hr['sector'][:26]} <span class=muted>{hr['heat']:.0f}%</span></td>"
                 f"<td>{cr['sector'][:26]} <span class=muted>{cr['heat']:.0f}%</span></td></tr>")
    h.append("</table>")

    # themes
    if themes:
        h.append("<h2>지금 도는 이슈 (뉴스에서 자동 추출 · 시간추이)</h2><table>")
        for t in themes:
            h.append(f"<tr><td class=lbl>{t['term']}</td>"
                     f"<td class=muted>연결 {t['deg']}</td><td style='font-family:monospace'>{t['spark'] or ''}</td></tr>")
        h.append("</table>")

    h.append("<p class=muted style='margin-top:30px'>이 화면 + 테마 연관망(themes/emergent.html)을 함께 보면 "
             "'지금 시장 상태 + 무슨 이슈가 도는가'를 한눈에 추론할 수 있습니다.</p>")
    h.append("</body></html>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(h), encoding="utf-8")
    return {"us_breadth": us, "kr_breadth": kr, "sectors": len(sectors),
            "macros": len(macros), "path": str(out_path)}
