"""NewsFetcher — key-free news ingest via Google News RSS (two-track).

Track A (company news): query Google News by issuer name -> Documents whose subject is the
queried issuer (subject is KNOWN for free, so no entity extraction needed for it).
Track B (macro news): query macro topics (oil, Fed rates, USD/KRW, gold...) -> Documents
whose subject is a :MacroIndicator. This is how "이란 전쟁/유가 급등" style news that is
NOT about one company still lands in the graph — attached to the commodity/rate it moves.

Each RSS <item> carries a per-article <source> (the actual outlet: Reuters, a blog, ...),
so credibility is mapped off the OUTLET, not the feed — tier-1 press -> major_news 0.60,
unknown/aggregator -> community 0.20. This is the first credibility VARIANCE in the graph,
which is what finally makes naive != canonical and gives "TRUE over LOUD" something to rank.

doc_id is derived from the article URL (stable) so periodic re-polling dedups idempotently.
"""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_GNEWS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"

# Tier-1 outlets -> major_news (0.60). Everything else (blogs, aggregators, unknown) falls
# to community (0.20). Matched case-insensitively as a substring of the <source> text.
TIER1_OUTLETS = [
    "reuters", "bloomberg", "associated press", "ap news", "wall street journal", "wsj",
    "financial times", "cnbc", "the new york times", "barron", "marketwatch", "forbes",
    "yonhap", "연합뉴스", "한국경제", "매일경제", "조선일보", "중앙일보", "동아일보",
    "한겨레", "jtbc", "sbs", "kbs", "mbc", "뉴시스", "머니투데이",
]

# Track B: macro topics -> the MacroIndicator they attach to (indicator_id from market.py).
MACRO_TOPICS = [
    ("crude oil price OPEC",        "MACRO:CL=F"),
    ("gold price",                  "MACRO:GC=F"),
    ("Federal Reserve interest rate", "MACRO:^TNX"),
    ("US Treasury yield",           "MACRO:^TNX"),
    ("dollar index DXY",            "MACRO:DX-Y.NYB"),
    ("USD KRW won exchange rate",   "MACRO:KRW=X"),
    ("S&P 500 index",               "MACRO:^GSPC"),
    ("KOSPI index",                 "MACRO:^KS11"),
]

# Korean market/macro topics -> the same macro indicator nodes. This is how 시황 news
# (코스피 시황, 한은 금리, 원/달러) lands in the graph without needing a KR company node.
MACRO_TOPICS_KR = [
    ("코스피 증시 시황",      "MACRO:^KS11"),
    ("한국은행 기준금리",     "MACRO:^TNX"),
    ("원달러 환율",          "MACRO:KRW=X"),
    ("국제 유가 油價",        "MACRO:CL=F"),
    ("금 시세 국제 금값",     "MACRO:GC=F"),
]


def _strip_html(s: str) -> str:
    """RSS/Naver descriptions carry HTML tags + entities; flatten to readable text."""
    import html as _html
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)  # &quot; &#39; &amp; ... -> real chars
    return re.sub(r"\s+", " ", s).strip()


# ALLOW-LIST of reputable press for USER-FACING display. The user's insight: rather than
# chase an ever-growing junk deny-list (factory outlets appear faster than you can list them),
# keep only vetted journalism. Measured: with Yahoo Finance included, only 13/400 top US
# issuers go dark (3%); without it, 197/400 (49%) — so Yahoo stays (its aggregated content is
# the coverage backbone; we can't resolve its true publishers retroactively). NOT a storage
# filter — junk is kept in the graph, just not surfaced in headlines/stance.
# NOTE on financial institutions (Goldman, BofA, Citi, Morgan Stanley, Wells Fargo, Moody's):
# these are NOT publishers — they're SUBJECTS mentioned in news ("Goldman raises target").
# They're already :Issuer nodes in the graph (all public, in EDGAR), so the company-graph
# lens already shows their activity. "What Goldman says about OTHER stocks" (ratings/targets)
# is relationship data needing the session/LLM extraction tier — not a publisher allow-list.
# So institutions are deliberately NOT here.
QUALITY_OUTLETS = [
    # US / global wires + tier-1 financial press (the names SaveTicker pulls from)
    "reuters", "bloomberg", "wall street journal", "wsj", "financial times", "ft.com",
    "cnbc", "marketwatch", "barron", "forbes", "new york times", "associated press",
    "ap news", "the motley fool", "business wire", "globe and mail", "yahoo finance",
    "fortune", "the economist", "axios", "cnn business", "guardian", "nikkei",
    "financial juice", "investor's business daily", "investors business daily", "kiplinger",
    # NOTE: Google News barely surfaces the wires (Reuters 35 / Bloomberg 58 / FT 3 in our
    # data) vs Yahoo 1958 — "clean US news" is limited by what Google returns, not filtering.
    # KR tier-1 press (the "세이브가 쓰는 언론사" intent — vetted Korean journalism)
    "매일경제", "한국경제", "연합뉴스", "조선비즈", "chosunbiz", "ked global", "뉴스핌",
    "서울경제", "머니투데이", "이데일리", "한겨레", "중앙일보", "동아일보", "조선일보",
    "jtbc", "sbs", "kbs", "mbc", "뉴시스", "daum", "네이트", "파이낸셜뉴스", "아시아경제",
    "헤럴드경제", "전자신문", "지디넷", "비즈워치", "더벨", "인포맥스",
    # major KR wires/dailies confirmed via Naver originallink (real publishers, not portals)
    "뉴스1", "문화일보", "경향신문", "서울신문", "ytn", "비즈니스포스트", "디지털타임스",
    "한국경제tv", "mbn", "kbs", "한겨레",
]


def is_quality_outlet(source_name: str) -> bool:
    """True if the outlet is vetted press (allow-list). Only these are surfaced in the UI."""
    s = (source_name or "").casefold()
    return any(q in s for q in QUALITY_OUTLETS)


# kept for the emergent builder's data-driven path (deny-list still useful there)
def is_junk_outlet(source_name: str) -> bool:
    """Inverse of the allow-list, for callers that still think in deny terms."""
    return not is_quality_outlet(source_name)


def _outlet_class(source_name: str) -> tuple[str, float]:
    s = (source_name or "").casefold()
    for t in TIER1_OUTLETS:
        if t.casefold() in s:
            return ("major_news", 0.60)
    return ("community", 0.20)


def _source_id(outlet: str) -> str:
    """Stable source_id per outlet: 'news::reuters'. Slugged, ascii-safe."""
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", (outlet or "unknown").casefold()).strip("-")
    return f"news::{slug or 'unknown'}"


def _doc_id(link: str) -> str:
    """Stable doc_id from the article URL so re-polling never duplicates.

    Uses hashlib (content-stable across processes). Python's builtin hash() is randomized
    per-process (SipHash), so it gave a DIFFERENT id for the same URL on each run — re-pulls
    created duplicate Claim/Mention nodes. sha1 is deterministic; idempotency holds."""
    import hashlib
    h = hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]
    return f"news_{h}"


class NewsFetcher:
    def __init__(self, min_interval: float = 0.4, max_items: int = 8):
        self.min_interval = min_interval   # ~2.5 req/s — verified safe in a 40-query burst
        self.max_items = max_items
        self._last = 0.0

    def _get(self, url: str) -> bytes:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=20).read()
        finally:
            self._last = time.monotonic()
        return data

    def _search(self, query: str, hl="en-US", gl="US", ceid="US:en") -> list[dict]:
        url = _GNEWS.format(q=urllib.parse.quote(query), hl=hl, gl=gl, ceid=ceid)
        try:
            root = ET.fromstring(self._get(url))
        except Exception:  # noqa: BLE001 — a bad feed must not kill the run
            return []
        out = []
        for it in root.findall(".//item")[: self.max_items]:
            title = (it.findtext("title", "") or "").strip()
            link = (it.findtext("link", "") or "").strip()
            pub = (it.findtext("pubDate", "") or "").strip()
            # body summary: RSS <description> often carries the lead sentence (+ ticker codes
            # in KR press). Strip HTML; richer than the title alone -> better theme emergence.
            desc = _strip_html(it.findtext("description", "") or "")
            src_el = it.find("{*}source")
            outlet = (src_el.text if src_el is not None else "") or "unknown"
            if not title or not link:
                continue
            out.append({"title": title, "link": link, "pubDate": pub, "outlet": outlet,
                        "summary": desc})
        return out

    # ----------------------------------------------------------------- Track A
    def fetch_company_news(self, issuer_id: str, name: str, knowledge_time: str,
                           lang: str = "en") -> list[dict]:
        """corpus Document dicts for one issuer. subject is the issuer (known).
        lang='ko' searches Korean Google News; subject_surface stays whatever name was
        passed, so querying by BOTH Korean and English name lands news on the SAME node."""
        if lang == "ko":
            items = self._search(name, hl="ko", gl="KR", ceid="KR:ko")
            doc_lang = "ko"
        else:
            items = self._search(f"{name} stock")
            doc_lang = "en"
        return [self._to_doc(it, knowledge_time, subject_id=issuer_id, subject_kind="issuer",
                             subject_surface=name, lang=doc_lang) for it in items]

    # ----------------------------------------------------------------- Track B
    def fetch_macro_news(self, knowledge_time: str, lang: str = "en") -> list[dict]:
        """corpus Document dicts for macro topics. subject is a MacroIndicator id.
        lang='ko' pulls 시황/금리/환율 news from Korean Google News -> same macro nodes."""
        docs = []
        topics = MACRO_TOPICS_KR if lang == "ko" else MACRO_TOPICS
        for query, indicator_id in topics:
            items = (self._search(query, hl="ko", gl="KR", ceid="KR:ko") if lang == "ko"
                     else self._search(query))
            for it in items:
                docs.append(self._to_doc(it, knowledge_time, subject_id=indicator_id,
                                         subject_kind="macro", subject_surface=query, lang=lang))
        return docs

    def _to_doc(self, it: dict, knowledge_time: str, subject_id, subject_kind,
                subject_surface, lang: str = "en") -> dict:
        outlet = it["outlet"]
        cls, cred = _outlet_class(outlet)
        event_time = _parse_rss_date(it["pubDate"]) or knowledge_time
        # text = title + body summary (de-duped if the summary just repeats the title)
        title = it["title"]
        summary = it.get("summary", "") or ""
        text = title if (not summary or summary[:30] == title[:30]) else f"{title}. {summary}"
        return {
            "doc_id": _doc_id(it["link"]),
            "source_id": _source_id(outlet),
            "lang": lang,
            "text": text,                   # title + RSS body summary (richer co-occurrence)
            "event_time": event_time,
            "ingest_time": knowledge_time,
            # private carry-fields for the news extractor / source registration:
            "_outlet": outlet, "_cred_class": cls, "_cred": cred, "_link": it["link"],
            "_subject_id": subject_id, "_subject_kind": subject_kind,
            "_subject_surface": subject_surface,
        }


_MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _parse_rss_date(s: str) -> str | None:
    """'Mon, 23 Jun 2026 04:30:00 GMT' -> '2026-06-23T04:30:00' (lexically sortable ISO)."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", s)
    if not m:
        return None
    day, mon, year, hh, mm, ss = m.groups()
    if mon not in _MONTHS:
        return None
    return f"{year}-{_MONTHS[mon]}-{int(day):02d}T{hh}:{mm}:{ss}"


# Naver originallink domain -> Korean publisher name. The API gives the real publisher URL
# (unlike Google's portal-redirect URLs), so we map domain -> outlet for precise whitelisting.
_KR_DOMAIN_PUBLISHER = {
    "mk.co.kr": "매일경제", "hankyung.com": "한국경제", "yna.co.kr": "연합뉴스",
    "sedaily.com": "서울경제", "mt.co.kr": "머니투데이", "edaily.co.kr": "이데일리",
    "hani.co.kr": "한겨레", "joongang.co.kr": "중앙일보", "donga.com": "동아일보",
    "chosun.com": "조선일보", "biz.chosun.com": "조선비즈", "fnnews.com": "파이낸셜뉴스",
    "asiae.co.kr": "아시아경제", "heraldcorp.com": "헤럴드경제", "etnews.com": "전자신문",
    "newsis.com": "뉴시스", "news1.kr": "뉴스1", "newspim.com": "뉴스핌",
    "munhwa.com": "문화일보", "khan.co.kr": "경향신문", "seoul.co.kr": "서울신문",
    "sbs.co.kr": "SBS", "kbs.co.kr": "KBS", "imbc.com": "MBC", "jtbc.co.kr": "JTBC",
    "ytn.co.kr": "YTN", "zdnet.co.kr": "지디넷", "thebell.co.kr": "더벨",
    "businesspost.co.kr": "비즈니스포스트", "dt.co.kr": "디지털타임스",
    "wowtv.co.kr": "한국경제TV", "infomax.co.kr": "인포맥스",
}


def _publisher_from_url(url: str) -> str:
    """originallink URL -> Korean publisher name (or the bare domain if unknown)."""
    dom = re.sub(r"https?://(www\.)?", "", url or "").split("/")[0].lower()
    for d, pub in _KR_DOMAIN_PUBLISHER.items():
        if dom.endswith(d):
            return pub
    return dom or "unknown"


class NaverNewsFetcher:
    """Korean news via the official Naver search API (free key). Cleaner than Google KR:
    the response's `originallink` is the REAL publisher URL, so we map it to the outlet and
    whitelist precisely. Emits the same `it` dicts NewsFetcher._to_doc consumes."""

    def __init__(self, client_id: str, client_secret: str, min_interval: float = 0.15,
                 max_items: int = 10):
        if not client_id or not client_secret:
            raise ValueError("Naver keys required (cfg.NAVER_CLIENT_ID/SECRET)")
        self.headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
        self.min_interval = min_interval
        self.max_items = max_items
        self._last = 0.0

    def _search(self, query: str) -> list[dict]:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = ("https://openapi.naver.com/v1/search/news.json?query="
               + urllib.parse.quote(query) + f"&display={self.max_items}&sort=sim")
        try:
            data = urllib.request.urlopen(
                urllib.request.Request(url, headers=self.headers), timeout=15).read()
            items = __import__("json").loads(data).get("items", [])
        except Exception:  # noqa: BLE001
            self._last = time.monotonic()
            return []
        self._last = time.monotonic()
        out = []
        for it in items:
            title = _strip_html(it.get("title", ""))
            link = it.get("originallink") or it.get("link", "")  # prefer real publisher URL
            if not title or not link:
                continue
            out.append({"title": title, "link": link, "pubDate": it.get("pubDate", ""),
                        "outlet": _publisher_from_url(it.get("originallink", "")),
                        "summary": _strip_html(it.get("description", ""))})
        return out

    def fetch_company_news(self, fetcher_for_to_doc, issuer_id, name, knowledge_time):
        """Reuse NewsFetcher._to_doc for output shape. fetcher_for_to_doc = a NewsFetcher."""
        return [fetcher_for_to_doc._to_doc(it, knowledge_time, subject_id=issuer_id,
                                           subject_kind="issuer", subject_surface=name, lang="ko")
                for it in self._search(name)]
