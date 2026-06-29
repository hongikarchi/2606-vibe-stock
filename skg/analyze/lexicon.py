"""Small bilingual (KR+EN) lexicons for offline, deterministic stance & grounding checks.

Hand-authored and shipped in-repo (no model download). These are intentionally small and
auditable — the research's point is that the credibility/stance priors must be inspectable,
not hidden in a 2GB encoder. Limitations (KR slang gaps, sarcasm) are disclosed in README.
"""
from __future__ import annotations

BULLISH = [
    "급등", "호재", "사상최대", "상한가", "대박", "강세",
    # KR directional verbs whose negated/opposite form is rare in practice (precision-biased):
    "수주", "출시", "신고가", "돌파", "흑자전환", "최대 실적",
    "surge", "beat", "record", "upgrade", "breakthrough", "rally", "jump",
]
BEARISH = [
    "급락", "우려", "적자", "소송", "감액", "분식", "하락", "악재", "리스크",
    "미치지 못", "불확실", "경고", "배제할 수 없",
    # KR event/reaction verbs that are unambiguously negative (rare positive sense):
    "사망", "제재", "횡령", "적자전환", "하향", "약세", "부진", "폭락", "상장폐지",
    # negative qualifiers that neutralize an otherwise-bullish event verb
    # (e.g. '수주 취소', '계약 철회' -> net neutral, not bullish):
    "취소", "철회", "무산", "반려",
    "risk", "probe", "lawsuit", "downgrade", "fraud", "loss", "warns", "plunge",
    # EN price-reaction verbs (so 'beat but stock fell' nets bearish, not bullish):
    "falls", "falling", "declines", "decline", "slumps", "tumbles", "plunges", "sell-off",
]
# tokens that flip or weaken the polarity of a nearby claim (grounding §6)
NEGATION = ["아니", "없", "부인", "반박", "overblown", "denied", "refuted", "false", "not", "no"]
HEDGE = ["수도", "가능성", "추정", "reportedly", "allegedly", "may", "could", "uncertain", "rumored"]
ATTRIBUTION = ["주장", "따르면", "측은", "alleges", "claims", "according", "skeptics", "제보"]


def stance_of(text: str) -> str:
    """bullish | bearish | neutral, by net polarity-token count.

    Polarity is carried by multi-word phrases in the lexicon (e.g. '미치지 못', '배제할 수
    없') rather than by a crude global negation-flip, which mis-handled double negation
    ('배제할 수 없다'). Negation/hedge are used by the GROUNDING guard, not here.
    """
    t = text.casefold()
    bull = sum(t.count(w.casefold()) for w in BULLISH)
    bear = sum(t.count(w.casefold()) for w in BEARISH)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "neutral"


def has_any(text: str, words: list[str]) -> bool:
    t = text.casefold()
    return any(w.casefold() in t for w in words)
