"""themes.py — bilingual (KR+EN) theme/event gazetteer + headline tagging.

The user wants to connect FRAGMENTED market information into an association web they can
reason over (e.g. trace 이란 → 유가 → 환율 → 반도체). The primitive is a small, AUDITABLE
gazetteer of themes (NOT an LLM/NER judgment layer — same philosophy as the stance lexicon):
each theme is a set of KO+EN surface keywords. A headline "belongs to" every theme whose
keyword it contains; two themes in one headline CO-OCCUR (an observation, not a causal claim).

Curated first; session-authored additions are the natural overlay. Keep it inspectable.
"""
from __future__ import annotations

import re

# theme_id -> (display label, [bilingual keywords])
THEMES = {
    "ai":            ("AI / 인공지능", ["AI", "인공지능", "artificial intelligence", "generative", "생성형", "LLM", "챗GPT", "ChatGPT"]),
    "semiconductor": ("반도체", ["반도체", "semiconductor", "chip", "HBM", "파운드리", "foundry", "wafer", "메모리", "memory chip", "D램", "DRAM", "낸드", "NAND"]),
    "datacenter":    ("데이터센터", ["데이터센터", "data center", "datacenter", "서버", "클라우드", "cloud", "hyperscaler"]),
    "power_energy":  ("전력 / 에너지", ["전력", "energy", "electricity", "원전", "nuclear", "원자력", "발전소", "grid", "송전", "전력망"]),
    "rates":         ("금리", ["금리", "interest rate", "fed", "federal reserve", "연준", "기준금리", "rate cut", "rate hike", "통화정책", "monetary policy"]),
    # fx keywords MEASURED-precision fix (2026-07-03): bare 달러/dollar/won/원화 matched every
    # valuation headline ("36,000 won", "billion-dollar IPO") — 88 fx "stories" were ~80%
    # currency-UNIT hits, not currency-MARKET stories. Qualified forms only.
    "fx":            ("환율", ["환율", "exchange rate", "원달러", "원·달러", "강달러", "약달러",
                             "달러 강세", "달러 약세", "won-dollar", "달러인덱스", "원화 가치", "원화 약세"]),
    "oil":           ("유가 / 원유", ["유가", "crude", "oil price", "OPEC", "원유", "WTI", "brent", "정유"]),
    "gold":          ("금 / 안전자산", ["금값", "gold price", "금 시세", "안전자산", "safe haven", "귀금속"]),
    "trump":         ("트럼프 / 美정치", ["트럼프", "trump", "백악관", "white house", "행정명령", "executive order"]),
    "geopolitics":   ("지정학 / 중동", ["이란", "iran", "중동", "middle east", "israel", "이스라엘", "전쟁", "war", "분쟁", "conflict", "우크라이나", "ukraine", "지정학", "geopolit"]),
    # bare 무역 dropped (matched company names: 영원'무역', 무역보험공사 — measured 2026-07-03)
    "trade":         ("관세 / 무역", ["관세", "tariff", "trade war", "무역전쟁", "무역협상", "무역분쟁",
                                  "수출규제", "export control", "통상마찰", "통상분쟁"]),
    # NOTE: '실적'(earnings) removed as a theme — it is an EVENT TYPE (every company reports
    # earnings), not a subject. Measured: it spanned 259/302 sectors (vs 반도체 83), 88% of its
    # headlines were earnings-only valuation boilerplate ("Price to earnings forward… TradingView"),
    # and 실적/earnings/매출 are ALREADY in the emergent non-topical stoplist. Earnings-driven moves
    # still surface under the real subject themes (AI/반도체/…). See THEME_CLASSIFICATION.md.
    "ma":            ("인수합병 M&A", ["인수", "합병", "M&A", "acquisition", "merger", "지분인수", "takeover"]),
    # '공급망/수급': dropped the over-broad tokens. bare 공급/supply = generic "provide/deliver"
    # (전기 공급, 변압기 공급계약, even the company "Tractor Supply") — 46% of supply-only headlines
    # were this, not supply-chain. 수급 was 84% 주식 수급 (외국인/기관 순매수 flows = trading-signal
    # content the no-signal stance forbids), not goods supply/demand. 부족 = generic "lack". Kept the
    # qualified supply-chain terms only. (measured; see THEME_CLASSIFICATION.md)
    "supply":        ("공급망 / 증설", ["공급망", "supply chain", "shortage", "증설", "capacity"]),
    "ev_battery":    ("전기차 / 배터리", ["전기차", "EV", "배터리", "battery", "2차전지", "이차전지", "충전", "리튬", "lithium"]),
    "regulation":    ("규제 / 제재", ["규제", "regulation", "제재", "sanction", "antitrust", "반독점", "과징금"]),
    "inflation":     ("물가 / 인플레이션", ["물가", "inflation", "인플레", "CPI", "소비자물가", "deflation"]),
    "defense":       ("방산 / 국방", ["방산", "defense", "무기", "weapon", "군수", "missile", "국방"]),
    "realestate":    ("부동산 / 건설", ["부동산", "real estate", "건설", "construction", "분양", "주택", "housing", "리츠", "REIT"]),
    "crypto":        ("가상자산", ["비트코인", "bitcoin", "가상자산", "crypto", "이더리움", "ethereum", "디지털자산"]),
    # ---- industry parents added 2026-07-03 (corpus-validated: post-dedup story counts
    # shipbuild 57 / bio 197 / auto 76 / finance 332 / enter 53 / consumer 101 — whole
    # sectors the gazetteer previously missed although flow-clustering shows them as real
    # co-movement groups). Company names deliberately NOT used as keywords.
    "shipbuild":     ("조선 / 해운", ["조선", "선박", "shipbuilding", "함정", "LNG선", "유조선", "조선소", "해운", "상선"]),
    "bio":           ("바이오 / 제약", ["바이오", "제약", "신약", "임상", "biotech", "pharma", "치료제", "FDA"]),
    "auto":          ("자동차 / 모빌리티", ["자동차", "완성차", "모빌리티", "automotive", "자율주행", "로보택시"]),
    "finance":       ("금융 / 은행·증권", ["은행", "증권사", "보험", "금융지주", "카드", "핀테크", "banking", "금융그룹"]),
    "enter":         ("엔터 / 게임·콘텐츠", ["엔터", "게임", "콘텐츠", "웹툰", "K팝", "케이팝", "드라마", "음원", "아이돌"]),
    "consumer":      ("유통 / 소비재", ["유통", "식품", "화장품", "K뷰티", "K푸드", "편의점", "백화점", "리테일", "패션"]),
}


def _kw_hit(kw: str, text_cf: str) -> bool:
    """Does keyword kw occur in text_cf? Latin-script keywords match on WORD BOUNDARIES
    (so 'AI' doesn't fire on 'm-ai-l'/'Haw-ai-i', 'EV' not on 'r-ev-enue', 'fed' not on
    'Fe-d-Ex'); Korean keywords use substring (Hangul is agglutinative, so '반도체' inside
    '반도체용' is a correct hit). This single fix removes the bulk of the old false positives
    (measured: AI bucket was 36% real, EV 19% — the rest were substring accidents)."""
    kw = kw.casefold()
    if any("가" <= c <= "힣" for c in kw):       # Korean -> substring
        return kw in text_cf
    return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text_cf) is not None


# ---- 2-level hierarchy: parents = THEMES above (stable spine); children = data/subthemes.json
# (session-curated, see that file + pipelines/curate flow). Loaded once. Each child:
#   child_id -> (label, parent_id, [keywords]). themes_in() returns BOTH levels.
def _load_subthemes():
    import json
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[2] / "data" / "subthemes.json"
    out = {}
    if not p.exists():
        return out
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    for parent_id, children in data.items():
        if parent_id.startswith("_") or parent_id not in THEMES:
            continue
        for ch in children:
            out[ch["id"]] = (ch["label"], parent_id, ch["keywords"])
    return out


SUBTHEMES = _load_subthemes()              # child_id -> (label, parent_id, keywords)
_CHILD_PARENT = {cid: p for cid, (_l, p, _k) in SUBTHEMES.items()}


def themes_in(text: str, include_children: bool = True) -> set[str]:
    """theme_ids whose keywords appear in text. Returns BOTH parent themes (THEMES) and,
    when include_children, child sub-themes (SUBTHEMES) — word-boundary for Latin / substring
    for Korean (see _kw_hit). A child hit does NOT auto-add its parent here; callers that want
    only parents pass include_children=False (e.g. back-compat counting)."""
    t = (text or "").casefold()
    found = set()
    for tid, (_label, kws) in THEMES.items():
        if any(_kw_hit(k, t) for k in kws):
            found.add(tid)
    if include_children:
        for cid, (_label, _parent, kws) in SUBTHEMES.items():
            if any(_kw_hit(k, t) for k in kws):
                found.add(cid)
    return found


def label_of(theme_id: str) -> str:
    if theme_id in THEMES:
        return THEMES[theme_id][0]
    if theme_id in SUBTHEMES:
        return SUBTHEMES[theme_id][0]
    return theme_id


def parent_of(theme_id: str) -> str | None:
    """Parent theme_id of a child, or None if it's a parent/unknown."""
    return _CHILD_PARENT.get(theme_id)


def is_parent(theme_id: str) -> bool:
    return theme_id in THEMES
