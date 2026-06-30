"""mine_bridges.py — mine NON-OBVIOUS issuer connections via shared specific bridge terms.

    SKG_STORAGE_BACKEND=neo4j python pipelines/mine_bridges.py

What it does (and deliberately does NOT do):
  - Mines issuer pairs that share a SPECIFIC bridge term (구리/유리기판/변압기…) in news, are
    NOT directly co-mentioned, and are NOT same-group. Attaches the evidence headline per hop.
  - Ranks by bridge SPECIFICITY (rarer term = more meaningful link) — an OBJECTIVE proxy, not a
    value score. The loop NEVER decides a cluster is "valuable/sellable" — that is the user's call.
  - Writes a human-review report (out/bridge_candidates.md). It does NOT deploy a view and does
    NOT touch web/public/data — a new surface with no regression baseline is not auto-shipped.

Division of labor (project principle: code mines, session curates):
  - CODE (here): hygiene + mining + ranking + evidence.
  - SESSION/USER: curates the bridge-term list (BRIDGE_TERMS below) and judges which clusters are
    real supply chains. Term-match is a weak proxy ("appears with 구리" != "구리 is its input"),
    and a term can bridge two DIFFERENT chains (폴리실리콘: solar vs HBM-slurry), so the CLUSTER
    must be curated, not just the term.
"""
from __future__ import annotations

import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.database import make_repo

# Session-curated specific bridge terms. Each should be a concrete supply-chain input/component,
# long/unambiguous enough to resist substring noise. Add via the curate flow as narratives shift.
BRIDGE_TERMS = [
    "유리기판", "FC-BGA", "변압기", "가스터빈", "버스덕트", "HBM", "전고체",
    "폴리실리콘", "암모니아", "초고압", "ESS", "리튬", "흑연", "네오디뮴",
]

MIN_SHARED_DOCS = 1      # a term-issuer link needs >=1 evidence headline (always true here)
MIN_TERM_LEN = 3         # avoid short ambiguous terms; 구리(2) excluded on purpose unless curated


def _hangul(c: str) -> bool:
    return "가" <= c <= "힣"


def clean_hit(term: str, text: str) -> bool:
    """Bridge term occurs as a real token, not embedded mid-compound (구리 in 농구리그)."""
    t = text.lower()
    tm = term.lower()
    for m in re.finditer(re.escape(tm), t):
        before = t[m.start() - 1] if m.start() > 0 else ""
        if before and _hangul(before):   # preceded by hangul -> embedded in a bigger word
            continue
        return True
    return False


def same_group(a: str, b: str) -> bool:
    a2, b2 = a.replace(" ", ""), b.replace(" ", "")
    s, l = (a2, b2) if len(a2) <= len(b2) else (b2, a2)
    if len(s) >= 2 and l.startswith(s):
        return True
    for tok in ("Holdings", "홀딩스", "사이언스", "그룹", "지주"):
        if a.replace(tok, "").strip() == b.replace(tok, "").strip() and a != b:
            return True
    return False


def main() -> None:
    repo = make_repo(cfg)
    rows = repo._read(
        "MATCH (cl:Claim)-[:ABOUT]->(i:Issuer) WHERE cl.source_id STARTS WITH 'news::' "
        "RETURN cl.source_span AS h, collect(DISTINCT i.name) AS issuers")
    docs = [((r["h"] or "").strip(), set(r["issuers"])) for r in rows if (r["h"] or "").strip()]

    terms = [t for t in BRIDGE_TERMS if len(t) >= MIN_TERM_LEN or not any(_hangul(c) for c in t)]

    # issuer <-> term (hygiene-filtered) + evidence, and direct co-mention set to EXCLUDE 1st-order
    term_iss: dict[str, set] = {t: set() for t in terms}
    ev: dict[tuple, list] = {}
    comention: dict[tuple, int] = {}
    df: dict[str, int] = {t: 0 for t in terms}
    for h, iss in docs:
        hits = [t for t in terms if clean_hit(t, h)]
        for t in hits:
            df[t] += 1
            for x in iss:
                term_iss[t].add(x)
                ev.setdefault((x, t), []).append(h)
        il = sorted(iss)
        if 2 <= len(il) <= 8:
            for a in range(len(il)):
                for b in range(a + 1, len(il)):
                    comention[(il[a], il[b])] = comention.get((il[a], il[b]), 0) + 1

    # build candidate clusters per term (rarer term first = more specific = ranked higher)
    out = ["# Bridge-term connection candidates (HUMAN REVIEW — not deployed)\n",
           "Mined issuer pairs that share a specific bridge term, are NOT directly co-mentioned,",
           "and are NOT same-group. Ranked by term specificity (DF). The loop does NOT judge value —",
           "mark each cluster 👍/👎 and which bridge terms to keep/drop.\n",
           f"as_of {cfg.AS_OF_NOW[:10]} · {len(docs)} headlines · bridge terms: {', '.join(terms)}\n"]
    ranked_terms = sorted((t for t in terms if len(term_iss[t]) >= 2), key=lambda t: df[t])
    for t in ranked_terms:
        members = sorted(term_iss[t])
        # only keep cross-group, non-co-mentioned pairs -> the non-obvious ones
        pairs = []
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                x, y = members[i], members[j]
                if comention.get(tuple(sorted((x, y))), 0) > 0:
                    continue
                if same_group(x, y):
                    continue
                pairs.append((x, y))
        if not pairs:
            continue
        out.append(f"\n## 다리 term: `{t}`  (이 term 등장 기사 {df[t]}건 · 연결기업 {len(members)}개) [ ] 👍/👎")
        # list the cluster members with one evidence headline each
        out.append("클러스터 멤버 (각자 이 term을 언급한 근거):")
        for m in members:
            e = ev.get((m, t), [""])[0]
            out.append(f"  - **{m}** — {e[:90]}")
        out.append(f"비자명 쌍 (직접 동시언급 없음): {len(pairs)}개")
    report = pathlib.Path(cfg.OUT) / "bridge_candidates.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(out), encoding="utf-8")
    print(f"[bridges] {len(ranked_terms)} bridge terms with cross-group clusters")
    print(f"[bridges] report -> {report}")
    repo.close()


if __name__ == "__main__":
    main()
