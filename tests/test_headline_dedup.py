"""Pins the empirically-calibrated headline-hygiene semantics (headline_dedup.py):
rewrite-syndication merges, factory templates and short-headline coincidences do NOT,
outlet junk is stripped. No DB, no network."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from skg.analyze.headline_dedup import (clean_headline, collapse_groups,  # noqa: E402
                                        day_change_from_closes, diverse)


# --------------------------------------------------------------------- clean_headline
def test_outlet_tail_and_repeated_title_stripped():
    raw = ("SKC, AI 전환 속도 낸다…전담 조직 출범 - MTN 머니투데이방송. "
           "SKC, AI 전환 속도 낸다…전담 조직 출범 MTN 머니투데이방송")
    out = clean_headline(raw, "MTN 머니투데이방송")
    assert "MTN" not in out and out.startswith("SKC, AI 전환 속도")
    assert out.count("전담 조직 출범") == 1   # duplicated-title summary dropped


def test_body_credit_stripped_without_outlet_param():
    raw = '" 씨어스 , UAE 220억 계약 체결" - 신한투자증권. 24일 신한투자증권은 씨어스에 대해 밝혔다'
    out = clean_headline(raw)
    assert '" 씨어스 , UAE 220억 계약 체결"' in out
    assert " - 신한투자증권" not in out


# --------------------------------------------------------------------- collapse_groups
def _r(text, date="2026-06-26", ent=None):
    return {"text": text, "date": date, "ent": ent}


REWRITES = [  # real SKC variants — one story, eight headlines
    _r("SKC, AX 전담 조직 출범…전사적 AI 전환 가속화", ent="SKC"),
    _r("SKC, CEO 직속 AI 전담조직 출범…AI 전환 가속화", ent="SKC"),
    _r("SKC 전사적 AI 전환 가속화…전담 조직 출범", ent="SKC"),
    _r("SKC, AI 전담조직 출범…전사적 AX 본격화", ent="SKC"),
    _r("SKC, 전담 조직 출범으로 AX 가속화…챗GPT 도입도 검토", ent="SKC"),
]


def test_rewrite_syndication_collapses_to_one():
    groups = collapse_groups(REWRITES)
    assert len(groups) == 1
    assert groups[0]["n_src"] == 5 and groups[0]["ents"] == ["SKC"]


def test_ticker_collision_junk_stays_separate():
    recs = REWRITES + [_r("SkyCity Entertainment Group Limited Actuals & Estimates (NZX:SKC)",
                          ent="SKC")]
    assert len(collapse_groups(recs)) == 2


def test_factory_template_different_companies_not_merged():
    recs = [_r("3 Reasons to Avoid ALGN and 1 Stock to Buy Instead", ent="ALIGN"),
            _r("3 Reasons to Avoid HSIC and 1 Stock to Buy Instead", ent="HENRY SCHEIN")]
    assert len(collapse_groups(recs)) == 2   # entity-conservative: near-dup across ents blocked


def test_exact_wire_copy_across_companies_merges_same_day():
    recs = [_r("'Gold is not done': Goldman Sachs predicts a rise to $4,900", ent="A"),
            _r("'Gold is not done': Goldman Sachs predicts a rise to $4,900", ent="B")]
    g = collapse_groups(recs)
    assert len(g) == 1 and g[0]["ents"] == ["A", "B"]


def test_short_headline_coincidence_not_merged():
    recs = [_r("코스피 상승 마감"), _r("코스닥 상승 마감")]
    assert len(collapse_groups(recs)) == 2   # 8-bigram floor


def test_recurring_daily_wrap_does_not_chain_across_month():
    recs = [_r("코스피, 외국인 순매수에 상승 마감…반도체 강세 지속", date=f"2026-06-{d:02d}")
            for d in range(1, 29)]
    groups = collapse_groups(recs)
    assert len(groups) >= 14   # span guard: 2-day groups max, never one month-blob


# --------------------------------------------------------------------- display helpers
def test_diverse_drops_near_repeat_display_items():
    items = [{"t": "SKC, AX 전담 조직 출범…전사적 AI 전환 가속화"},
             {"t": "SKC, CEO 직속 AI 전담조직 출범…전사 AX 추진 본격화"},
             {"t": "일진전기, 유럽 HVDC 3천억 수주"}]
    kept = diverse(items, 6)
    assert len(kept) == 2 and kept[1]["t"].startswith("일진전기")


def test_day_change_staleness_guard():
    closes = [100.0, 110.0]
    assert day_change_from_closes(closes, "2026-07-02", "2026-07-03T00:00:00") == 0.1
    assert day_change_from_closes(closes, "2026-06-20", "2026-07-03T00:00:00") is None
    assert day_change_from_closes("[100, 105]", "2026-07-03", "2026-07-03T00:00:00") == 0.05
