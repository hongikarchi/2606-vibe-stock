"""themes.py — bilingual (KR+EN) theme/event gazetteer + headline tagging.

The user wants to connect FRAGMENTED market information into an association web they can
reason over (e.g. trace 이란 → 유가 → 환율 → 반도체). The primitive is a small, AUDITABLE
gazetteer of themes (NOT an LLM/NER judgment layer — same philosophy as the stance lexicon):
each theme is a set of KO+EN surface keywords. A headline "belongs to" every theme whose
keyword it contains; two themes in one headline CO-OCCUR (an observation, not a causal claim).

Curated first; session-authored additions are the natural overlay. Keep it inspectable.
"""
from __future__ import annotations

# theme_id -> (display label, [bilingual keywords])
THEMES = {
    "ai":            ("AI / 인공지능", ["AI", "인공지능", "artificial intelligence", "generative", "생성형", "LLM", "챗GPT", "ChatGPT"]),
    "semiconductor": ("반도체", ["반도체", "semiconductor", "chip", "HBM", "파운드리", "foundry", "wafer", "메모리", "memory chip", "D램", "DRAM", "낸드", "NAND"]),
    "datacenter":    ("데이터센터", ["데이터센터", "data center", "datacenter", "서버", "클라우드", "cloud", "hyperscaler"]),
    "power_energy":  ("전력 / 에너지", ["전력", "energy", "electricity", "원전", "nuclear", "원자력", "발전소", "grid", "송전", "전력망"]),
    "rates":         ("금리", ["금리", "interest rate", "fed", "federal reserve", "연준", "기준금리", "rate cut", "rate hike", "통화정책", "monetary policy"]),
    "fx":            ("환율", ["환율", "exchange rate", "달러", "dollar", "원화", "won", "원달러", "강달러", "약달러"]),
    "oil":           ("유가 / 원유", ["유가", "crude", "oil price", "OPEC", "원유", "WTI", "brent", "정유"]),
    "gold":          ("금 / 안전자산", ["금값", "gold price", "금 시세", "안전자산", "safe haven", "귀금속"]),
    "trump":         ("트럼프 / 美정치", ["트럼프", "trump", "백악관", "white house", "행정명령", "executive order"]),
    "geopolitics":   ("지정학 / 중동", ["이란", "iran", "중동", "middle east", "israel", "이스라엘", "전쟁", "war", "분쟁", "conflict", "우크라이나", "ukraine", "지정학", "geopolit"]),
    "trade":         ("관세 / 무역", ["관세", "tariff", "trade war", "무역", "수출규제", "export control", "통상"]),
    "earnings":      ("실적", ["실적", "earnings", "매출", "revenue", "영업이익", "operating profit", "guidance", "어닝"]),
    "ma":            ("인수합병 M&A", ["인수", "합병", "M&A", "acquisition", "merger", "지분인수", "takeover"]),
    "supply":        ("공급망 / 수급", ["공급", "supply", "부족", "shortage", "수급", "공급망", "supply chain", "증설", "capacity"]),
    "ev_battery":    ("전기차 / 배터리", ["전기차", "EV", "배터리", "battery", "2차전지", "이차전지", "충전", "리튬", "lithium"]),
    "regulation":    ("규제 / 제재", ["규제", "regulation", "제재", "sanction", "antitrust", "반독점", "과징금"]),
    "inflation":     ("물가 / 인플레이션", ["물가", "inflation", "인플레", "CPI", "소비자물가", "deflation"]),
    "defense":       ("방산 / 국방", ["방산", "defense", "무기", "weapon", "군수", "missile", "국방"]),
    "realestate":    ("부동산 / 건설", ["부동산", "real estate", "건설", "construction", "분양", "주택", "housing", "리츠", "REIT"]),
    "crypto":        ("가상자산", ["비트코인", "bitcoin", "가상자산", "crypto", "이더리움", "ethereum", "디지털자산"]),
}


def themes_in(text: str) -> set[str]:
    """Return the set of theme_ids whose keywords appear in the text (case-insensitive)."""
    t = (text or "").casefold()
    found = set()
    for tid, (_label, kws) in THEMES.items():
        if any(k.casefold() in t for k in kws):
            found.add(tid)
    return found


def label_of(theme_id: str) -> str:
    return THEMES.get(theme_id, (theme_id, []))[0]
