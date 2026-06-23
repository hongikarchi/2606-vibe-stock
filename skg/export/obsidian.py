"""obsidian — render the analysis into a navigable markdown vault.

Design (research 02b §humanExposure + 02c fix #5 "collapse 12 flags to 2-3 badges"):
  _index.md                  dashboard: minority reports on TOP, then naive-vs-credible ranks
  entities/<name>.md         per-entity page with 3 composite badges + provenance
  minority/<doc>.md          dropped-then-recovered claims (dissent NOT collapsed)

Determinism: every set/dict-derived list is sorted() before emission. No buy/sell vocab
(structural guardrail — the templates have no such field).
"""
from __future__ import annotations

import re
from pathlib import Path

import config as cfg
from ..models import AnalysisResult


def _slug(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "-", name).strip("-")
    return s or "entity"


def write_vault(results: list[AnalysisResult], flags: dict, bitemporal: dict,
                entity_detail: dict, as_of: str, vault_dir: str | Path) -> None:
    vault = Path(vault_dir)
    (vault / "entities").mkdir(parents=True, exist_ok=True)
    (vault / "minority").mkdir(parents=True, exist_ok=True)
    _write_index(results, flags, bitemporal, entity_detail, as_of, vault)
    for r in results:
        _write_entity(r, flags, entity_detail.get(r.entity_id, {}), as_of, vault)
    _write_minority(flags, as_of, vault)


# --------------------------------------------------------------------------- index
def _write_index(results, flags, bitemporal, entity_detail, as_of, vault) -> None:
    L: list[str] = []
    L.append("# 주식 지식그래프 — 대시보드")
    L.append(f"\n*as-of: {as_of}*  ·  **AI는 정보를 구조화할 뿐, 판단은 사람이 합니다.**\n")

    # --- MINORITY REPORTS ON TOP (dissent must not be a footnote) ---
    omissions = flags.get("omission", [])
    skews = flags.get("stance_dispersion", [])
    L.append("## ⚠️ 소수·이견 리포트 (먼저 보세요)\n")
    if not omissions and not skews:
        L.append("- (이번 코퍼스에서 탐지된 누락/편향 없음)\n")
    else:
        for o in omissions:
            # lead with the concrete material fact; show % only when it's a real (non-zero) bound
            material = ", ".join(o.get("material_dropped") or o["omissions"])
            pct = o["omitted_mass_lower_bound_pct"]
            mass = f", 누락질량 ≥{pct}%(하한)" if pct > 0 else ""
            L.append(f"- **누락된 material** · [[{o['doc_id']}]] — **{material}** "
                     f"(추출이 빠뜨림; recall@span={o['recall_at_span']}{mass})")
        for s in skews:
            L.append(f"- **선택 편향** · [[skew_{s['doc_id']}]] — 원문 {dict(s['source_stance'])} "
                     f"→ 추출 {dict(s['elevated_stance'])} (JSD={s['jsd']})")
        L.append("")

    # --- IMPORTANCE: naive vs credibility-weighted ---
    L.append("## 중요도 랭킹 — naive vs 신뢰도가중\n")
    L.append("원시 중심성(naive)은 **시끄러운 것(LOUD)**을 위로 올립니다. "
             "신뢰도가중 PPR + TrustRank는 출처 신뢰도를 접어 **TRUE를 위로** 올립니다. "
             "`⬇` = 신뢰도 때문에 강등된 항목(펌프 의심).\n")
    L.append("| 엔티티 | naive | 신뢰도가중 | K eff / M raw | trusted share |")
    L.append("|---|---|---|---|---|")
    for r in results:
        moved = ""
        if r.rank_naive and r.rank_credible:
            if r.rank_credible > r.rank_naive:
                moved = " ⬇"
            elif r.rank_credible < r.rank_naive:
                moved = " ⬆"
        km = f"{r.k_effective}/{r.m_raw}" if r.m_raw else "—"
        link = f"[[{_slug(r.entity_id)}]]"
        L.append(f"| {link} | #{r.rank_naive} | #{r.rank_credible}{moved} | {km} | {r.trusted_share:.2f} |")

    # --- BI-TEMPORAL: survivorship + ticker reuse (no look-ahead) ---
    L.append("\n## 시점 정합성 (bi-temporal) — 생존편향 방지\n")
    L.append("과거 랭킹을 *그때 존재했던 우주*로 재구성합니다. 오늘 살아남은 종목만 보는 "
             "생존편향(look-ahead)을 막습니다.\n")
    L.append(f"- 현재({bitemporal['as_of_now'][:10]}) 우주: {len(bitemporal['universe_now'])}개 발행사")
    L.append(f"- 과거({bitemporal['as_of_past'][:10]}) 우주: {len(bitemporal['universe_past'])}개 발행사")
    only_past = ", ".join(bitemporal["only_in_past"]) or "(없음)"
    L.append(f"- **과거에만 존재** (그 후 상장폐지): **{only_past}** — 과거 분석엔 포함, 현재엔 제외")
    tr = bitemporal["ticker_reuse"]
    L.append(f"- 티커 재사용: `$V` → 2007년 {tr['$V @2007']} / 2026년 {tr['$V @2026']} "
             "(같은 표면형, 시점별 다른 엔티티)\n")

    L.append("\n---\n*DEFERRED (이 데모에 미포함): info-flow/전이엔트로피, Leiden/BERTopic 군집, "
             "교차계열 NLI, full CIB, 실시간 LLM 추출. 근거는 README 참조.*\n")
    (vault / "_index.md").write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------- entity page
def _write_entity(r: AnalysisResult, flags, detail, as_of, vault) -> None:
    L: list[str] = []
    L.append(f"# {r.entity_id}\n")
    L.append(f"*as-of: {as_of}*\n")

    # --- IDENTITY: collapsed aliases + securities (the cross-lingual resolution payoff) ---
    aliases = detail.get("aliases", [])
    securities = detail.get("securities", [])
    if aliases or securities:
        L.append("## 정체성 (해소 결과)\n")
        if aliases:
            L.append(f"- **합쳐진 별칭**: {', '.join('`'+a+'`' for a in aliases)} "
                     "→ 한 노드로 collapse (교차언어 해소)")
        if securities:
            L.append(f"- **증권**: {', '.join(securities)}")
        L.append("")

    # --- RELATIONSHIPS (연관성 — the user's first ask) ---
    rel_out = detail.get("rel_out", [])
    rel_in = detail.get("rel_in", [])
    if rel_out or rel_in:
        L.append("## 연관성 (관계 그래프)\n")
        for rel, obj, src in rel_out:
            L.append(f"- {r.entity_id} —**{rel}**→ [[{_slug(obj)}]]  *(출처: {src})*")
        for rel, subj, src in rel_in:
            L.append(f"- [[{_slug(subj)}]] —**{rel}**→ {r.entity_id}  *(출처: {src})*")
        L.append("")

    # --- 3 COMPOSITE BADGES ---
    L.append("## 배지\n")
    # 1) Grounding
    g_issues = r.flags.get("grounding", [])
    if g_issues:
        L.append(f"- 🟠 **Grounding**: {', '.join(sorted(set(g_issues)))} "
                 "(근거 span이 부정/인용으로 극성 반전 — 출처충실성 의심)")
    else:
        L.append("- 🟢 **Grounding**: 근거 span 검증됨 (parametric 주장 아님)")
    # 2) Corroboration
    corro = r.flags.get("corroboration")
    if corro:
        L.append(f"- 🟡 **Corroboration**: {corro}")
    elif r.m_raw:
        L.append(f"- 🟢 **Corroboration**: {r.k_effective} effective / {r.m_raw} raw "
                 "(독립성 상한; good-source 복사는 과소계수)")
    else:
        L.append("- ⚪ **Corroboration**: 관계 엣지로만 등장 (직접 언급 없음)")
    # 3) Dispersion
    L.append(f"- 🔵 **Dispersion**: trusted-share {r.trusted_share:.2f} "
             "(낮을수록 비신뢰 출처 비중↑) · 이견은 [[minority]] 참조\n")

    # --- importance numbers ---
    L.append("## 중요도\n")
    moved = "강등(펌프 의심) ⬇" if (r.rank_naive and r.rank_credible > r.rank_naive) else \
            ("상승 ⬆" if (r.rank_naive and r.rank_credible < r.rank_naive) else "변화 없음")
    L.append(f"- naive PageRank rank: **#{r.rank_naive}**")
    L.append(f"- 신뢰도가중 PPR rank: **#{r.rank_credible}** ({moved})")
    L.append(f"- ppr_naive={r.ppr_naive:.4f} · ppr_credible={r.ppr_credible:.4f}\n")

    # --- CITATIONS: every claim traced to source + credibility + span (provenance) ---
    claims = detail.get("claims", [])
    if claims:
        L.append("## 근거 (provenance)\n")
        L.append("| relation | 대상/내용 | stance | 출처 | 신뢰도 | 근거 span |")
        L.append("|---|---|---|---|---|---|")
        for c in claims:
            obj = c["object"] or "—"
            span = (c["span"] or "").replace("|", "/")
            L.append(f"| {c['relation']} | {obj} | {c['stance']} | {c['source']} "
                     f"| {c['credibility']:.2f} | {span} |")
        L.append("")
    (vault / "entities" / f"{_slug(r.entity_id)}.md").write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------- minority report
def _write_minority(flags, as_of, vault) -> None:
    for o in flags.get("omission", []):
        L: list[str] = []
        L.append(f"# 누락 복원 — {o['doc_id']}\n")
        L.append(f"*as-of: {as_of}* · 편향 추출이 빠뜨린 항목을 비-LLM 베이스라인이 복원했습니다.\n")
        L.append(f"- recall@span: **{o['recall_at_span']}**")
        L.append(f"- 누락 항목: **{', '.join(o['omissions'])}**")
        L.append(f"- 추정 누락 질량: **≥ {o['omitted_mass_lower_bound_pct']}%** ({o['label']})\n")
        L.append("> 이견·소수 신호는 요약으로 뭉개지 않고 1급 노드로 보존됩니다.\n")
        (vault / "minority" / f"{o['doc_id']}.md").write_text("\n".join(L), encoding="utf-8")
    for s in flags.get("stance_dispersion", []):
        L = []
        L.append(f"# 선택 편향 — {s['doc_id']}\n")
        L.append(f"*as-of: {as_of}* · grounded ≠ unbiased: 각 추출은 참이나 *선택*이 편향됐습니다.\n")
        L.append(f"- 원문 stance 분포: `{dict(s['source_stance'])}`")
        L.append(f"- 추출 stance 분포: `{dict(s['elevated_stance'])}`")
        L.append(f"- Jensen-Shannon divergence: **{s['jsd']}** (임계 {cfg.STANCE_SKEW_JSD})\n")
        (vault / "minority" / f"skew_{s['doc_id']}.md").write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------- guardrail
def guardrail_scan(vault_dir: str | Path) -> list[str]:
    vault = Path(vault_dir)
    hits: list[str] = []
    for md in sorted(vault.rglob("*.md")):
        text = md.read_text(encoding="utf-8").casefold()
        for term in cfg.FORBIDDEN_VOCAB:
            if term.casefold() in text:
                hits.append(f"{md.name}: {term}")
    return sorted(hits)
