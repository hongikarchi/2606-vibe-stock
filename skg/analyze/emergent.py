"""emergent.py — data-driven term network (replaces the fixed theme gazetteer).

The user's design (correct): don't hand-pick themes — remove generic words, and the
well-connected words rise into hubs naturally. Bias-free genericness filter = DOCUMENT
FREQUENCY: a term in a large fraction of all docs IS generic by definition (korea, ceo,
business, outlet names), so DF auto-demotes it — no hand-curated stoplist of *topics*.

The only hand list is language FUNCTION words (the, with, after, 그리고...) — these are not
market topics in any framing, so excluding them is not a topical bias. Everything topical is
left to the data. Survivors are ranked by co-occurrence connectivity (the user's "연결고리
많은 단어"). This is DF-filter-then-degree ≈ TF-IDF: one method, = the user's idea.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from itertools import combinations

_TOK = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}")

# NON-TOPICAL words to drop. Three bias-free categories (NONE of them is a market topic, so
# excluding them does not pre-decide which themes the data may surface):
#   1) language function words (KO particles/connectives + EN stopwords)
#   2) news INFRASTRUCTURE — wire services, aggregators, data vendors, outlet names
#   3) generic finance/quantity scaffolding (stock, price, year, billion, ceo, 실적...) that is
#      universal market vocabulary, not a specific theme.
# Specific TOPICS (AI, 반도체, 유가, 이란...) are NEVER listed — document frequency + the data
# decide those, so the old gazetteer's blind spots cannot creep back in.
_FUNCTION = set("""
the and for with from this that you are has had not but all can its now new than into out off
over per via amp here first amid after before how why what when who will been more most some
such only also they them their there then both each many much very upon about above against
그리고 그러나 그런데 또한 위해 통해 관련 대한 이번 지난 오늘 내일 올해 작년 기자 단독 종합 속보
무단 전재 배포 금지 라며 면서 했다 한다 이라고 라고 으로 에서 에게 부터 까지 보다 처럼
# KO reporting/boilerplate verbs + scaffolding (frequent-but-below-df_hi, so DF can't demote them):
밝혔다 밝혔 있다 없다 따르면 위한 위해서 규모 억원 만원 조원 달러 이날 오는 주요 대해 이어 함께
것으로 것이라고 전망이다 예정이다 계획이다 나타났다 보인다 가운데 대비 기록했다 기록 달성 추진 방침
# generic non-topical nouns (geography/scale/recency — not a market theme, like the EN korea/year entries):
사업 국내 미국 핵심 그룹 최근 최대 속도 속도를 규모의 가장 관련해 통해서 이상 이하 수준 계획 전략

inc corp ltd group co plc llc holdings holding company corporation
news update report says said say according reuters bloomberg
chosunbiz marketscreener newswire ked quiver simplywall tradingview tradingkey seeking alpha
zacks benzinga motley investing insider gurufocus stocktitan stockstory directorstalk globenewswire
businesswire prnewswire finance yahoo nasdaq nyse krx kosdaq daum mtn
tikr barchart stocktwits fool wallst tipranks marketbeat
# EN headline-template / scaffolding fragments that co-occur with everything (the noise hubs):
hits form valuation upside despite undervalued overvalued fair street wall time june july sahm hoc
canada plan under maintains rating reiterates lowers raises sets initiates coverage
next down one out way back off set get put run top end big key two three
매일경제 한국경제 서울경제 머니투데이 이데일리 연합뉴스 조선비즈 인포맥스 뉴스핌 파이낸셜

year month quarter day week stock stocks shares share price prices market markets value
million billion trillion percent investor investors investment trading trade fund analyst
results result earnings revenue profit growth high low strong weak best top gain gains loss
target buy sell hold rating upgrade downgrade business south korean korea ceo cfo chief
실적 매출 영업이익 주가 종목 증시 코스피 코스닥 투자 시장 기업 상승 하락 강세 약세 전망 분석
# earnings-report / press-release SCAFFOLDING words (non-topical, appear across all outlets):
eps estimates estimate forecast guidance consensus reports report reported announces announced
announcement analysis daily weekly today recent could would should outlook outperform underperform
dividend yield buyback insider stake holder holders filing filed sec quarterly annual fiscal
therapeutics pharmaceuticals technologies systems solutions industries enterprises ventures
확대 글로벌 뉴스 네이트 목표가 공시 발표 전일 종가 시간 기준 대비
""".split())


def tokens(text: str) -> set[str]:
    """Distinct topical-candidate tokens in a doc (function words removed; case-folded EN)."""
    out = set()
    for w in _TOK.findall(text or ""):
        wl = w if any("가" <= c <= "힣" for c in w) else w.casefold()
        if wl in _FUNCTION:
            continue
        out.add(wl)
    return out


def build_term_network(docs: list[str], df_hi: float = 0.02, df_lo: int = 10,
                       min_cooccur: int = 5, top_terms: int = 120):
    """docs = list of news texts. Returns (terms, edges):
      terms = [{term, df, degree}]  — survivors ranked by connectivity (the emergent hubs)
      edges = [{a, b, weight}]      — co-occurrence among surviving terms

    df_hi: drop terms appearing in > this FRACTION of docs (generic — korea/ceo/outlets).
    df_lo: drop terms in < this many docs (rare noise / one-off company-name fragments).
    """
    n = len(docs) or 1
    df = Counter()
    doc_terms = []
    for d in docs:
        ts = tokens(d)
        doc_terms.append(ts)
        for t in ts:
            df[t] += 1

    keep = {t for t, c in df.items() if df_lo <= c <= df_hi * n}

    cooc = Counter()
    nb = defaultdict(set)
    for ts in doc_terms:
        kt = sorted(ts & keep)
        for a, b in combinations(kt, 2):
            cooc[(a, b)] += 1
            nb[a].add(b)
            nb[b].add(a)

    # rank survivors by degree (distinct co-occurrence partners) = "연결고리 많은 단어"
    ranked = sorted(keep, key=lambda t: (-len(nb[t]), -df[t]))[:top_terms]
    rankset = set(ranked)
    terms = [{"term": t, "df": df[t], "degree": len(nb[t] & rankset)} for t in ranked]
    edges = [{"a": a, "b": b, "weight": w} for (a, b), w in cooc.items()
             if w >= min_cooccur and a in rankset and b in rankset]
    return terms, edges
