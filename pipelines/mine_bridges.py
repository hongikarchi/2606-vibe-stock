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
    """Bridge term occurs as a REAL token, not embedded in a bigger word.
    - Latin terms (ESS/HBM/FC-BGA): word-boundary match — else ESS fires inside 'Businesskorea',
      'Essex', 'Simmtech' (the substring disease; same fix as the stance lexicon).
    - Korean terms (변압기/유리기판): reject only when a hangul immediately PRECEDES (농[구리]그),
      since Korean compounds glue without spaces and a trailing 용/주 is still a real hit (유리기판용).
    """
    t = text.lower()
    tm = term.lower()
    if not any(_hangul(c) for c in tm):   # Latin -> word boundary
        return re.search(r"(?<![a-z0-9])" + re.escape(tm) + r"(?![a-z0-9])", t) is not None
    for m in re.finditer(re.escape(tm), t):
        before = t[m.start() - 1] if m.start() > 0 else ""
        if before and _hangul(before):   # preceded by hangul -> embedded in a bigger word
            continue
        return True
    return False


# Curated conglomerate families — the prefix rule alone leaks 472 same-group pairs (삼성증권↔
# 삼성SDI don't share a clean prefix but ARE one chaebol). Cheap, accurate, objective. NOT a DART
# ownership ingest (that's the infeasible rule-based-relation problem). Maintain by hand.
FAMILIES = {
    "삼성": ["삼성", "samsung"], "SK": ["SK", "에스케이"], "LG": ["LG", "엘지"],
    "현대차": ["현대차", "현대자동차", "기아", "현대모비스", "현대글로비스"],
    "HD현대": ["HD현대", "현대중공업", "현대일렉트릭", "현대미포", "한국조선해양"],
    "효성": ["효성"], "포스코": ["포스코", "posco"], "롯데": ["롯데", "lotte"],
    "한화": ["한화"], "CJ": ["CJ"], "GS": ["GS"], "두산": ["두산", "doosan"],
    "신세계": ["신세계", "이마트"], "코오롱": ["코오롱"], "한진": ["한진", "대한항공"],
    "DB": ["DB하이텍", "DB금융", "DB손해"], "OCI": ["OCI"], "HD": ["하이트진로"],
}


def _family(name: str):
    for fam, keys in FAMILIES.items():
        if any(k.lower() in name.lower() for k in keys):
            return fam
    return None


def same_group(a: str, b: str) -> bool:
    # 1) curated family map (catches affiliates with no shared prefix)
    fa, fb = _family(a), _family(b)
    if fa and fa == fb:
        return True
    # 2) prefix / holdings-suffix fallback (covers families not in the map)
    a2, b2 = a.replace(" ", ""), b.replace(" ", "")
    s, l = (a2, b2) if len(a2) <= len(b2) else (b2, a2)
    if len(s) >= 2 and l.startswith(s):
        return True
    for tok in ("Holdings", "홀딩스", "사이언스", "그룹", "지주"):
        if a.replace(tok, "").strip() == b.replace(tok, "").strip() and a != b:
            return True
    return False


# Secondary-context terms — used to build each issuer's context PROFILE, so we can flag pairs a
# bridge term links by HOMONYM/different-chain (폴리실리콘: OCI=태양광 vs 와이씨=HBM). Objective:
# low profile-cosine + both profiles rich = different chains; thin profile = low-confidence (we
# say so, we don't force a merge or a drop). This FLAGS for the user; it never asserts "same chain".
CONTEXT_TERMS = ["태양광", "solar", "HBM", "메모리", "반도체", "전력", "데이터센터", "배터리",
                 "2차전지", "조선", "선박", "방산", "바이오", "풍력", "원전", "유리기판",
                 "변압기", "폴리실리콘", "전기차", "가스터빈", "수소", "로봇", "파운드리"]


def main() -> None:
    import math
    from collections import Counter

    repo = make_repo(cfg)
    rows = repo._read(
        "MATCH (cl:Claim)-[:ABOUT]->(i:Issuer) WHERE cl.source_id STARTS WITH 'news::' "
        "RETURN cl.source_span AS h, collect(DISTINCT i.name) AS issuers")
    docs = [((r["h"] or "").strip(), set(r["issuers"])) for r in rows if (r["h"] or "").strip()]

    terms = [t for t in BRIDGE_TERMS if len(t) >= MIN_TERM_LEN or not any(_hangul(c) for c in t)]

    term_iss: dict[str, set] = {t: set() for t in terms}
    ev: dict[tuple, list] = {}
    comention: dict[tuple, int] = {}
    df: dict[str, int] = {t: 0 for t in terms}
    profile: dict[str, "Counter"] = {}

    for h, iss in docs:
        hits = [t for t in terms if clean_hit(t, h)]
        ctx = [c for c in CONTEXT_TERMS if clean_hit(c, h)]
        for t in hits:
            df[t] += 1
            for x in iss:
                term_iss[t].add(x)
                ev.setdefault((x, t), []).append(h)
        for x in iss:
            p = profile.setdefault(x, Counter())
            for c in ctx:
                p[c] += 1
        il = sorted(iss)
        if 2 <= len(il) <= 8:
            for a in range(len(il)):
                for b in range(a + 1, len(il)):
                    comention[(il[a], il[b])] = comention.get((il[a], il[b]), 0) + 1

    def cos(a: str, b: str) -> float:
        A, B = profile.get(a, Counter()), profile.get(b, Counter())
        keys = set(A) | set(B)
        if not keys:
            return 0.0
        dot = sum(A[k] * B[k] for k in keys)
        na = math.sqrt(sum(v * v for v in A.values()))
        nb = math.sqrt(sum(v * v for v in B.values()))
        return dot / (na * nb) if na and nb else 0.0

    def profile_rich(x: str) -> bool:
        return sum(profile.get(x, Counter()).values()) >= 3   # enough context to judge

    # --- build cross-group, non-co-mentioned candidate PAIRS, with multi-term corroboration ---
    # pair -> set(bridge terms linking it)
    pair_terms: dict[tuple, set] = {}
    for t in terms:
        members = sorted(term_iss[t])
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                x, y = members[i], members[j]
                if comention.get(tuple(sorted((x, y))), 0) > 0:   # exclude 1st-order
                    continue
                if same_group(x, y):
                    continue
                pair_terms.setdefault(tuple(sorted((x, y))), set()).add(t)

    CONF_HI, CONF_LO = 0.35, 0.35   # cosine split for same-context vs different-chain flag
    cands = []
    for (x, y), tset in pair_terms.items():
        c = cos(x, y)
        rich = profile_rich(x) and profile_rich(y)
        if not rich:
            flag = "⚠️ 컨텍스트 부족(저신뢰)"
        elif c >= CONF_HI:
            flag = "✅ 컨텍스트 일치"
        else:
            flag = "🚩 다른 공급망 의심(동음이의?)"
        # rank: more shared bridge terms first, then higher context-cosine, then rarer bridge
        rarity = min(df[t] for t in tset)
        cands.append((len(tset), round(c, 2), -rarity, x, y, sorted(tset), flag))
    cands.sort(reverse=True)

    # --- report: ONE digestible batch, candidates-for-verdict (loop does NOT judge value) ---
    confirmed = [c for c in cands if c[6].startswith("✅")]
    out = ["# 비자명 연결 후보 — 사용자 검증용 (배포 안 됨 · 루프는 가치 판단 안 함)\n",
           "bridge term을 공유하지만 직접 동시언급 없고 그룹사도 아닌 기업 쌍. 객관 정제만 적용:",
           "단어경계 위생 · 그룹사 필터(계열맵) · 동음이의 플래그(컨텍스트 프로파일 코사인) ·",
           "multi-term 보강(여러 term이 잇는 쌍 우선). **각 쌍에 👍/👎와 bridge term 가감을 표시**해주세요.\n",
           f"as_of {cfg.AS_OF_NOW[:10]} · {len(docs)} 헤드라인 · 후보쌍 {len(cands)}개 "
           f"(✅일치 {sum(1 for c in cands if c[6].startswith('✅'))} · "
           f"🚩의심 {sum(1 for c in cands if c[6].startswith('🚩'))} · "
           f"⚠️저신뢰 {sum(1 for c in cands if c[6].startswith('⚠'))})\n",
           "## ✅ 컨텍스트 일치 + 다중 term 우선 (가장 검토 가치 높은 순)\n"]
    shown = [c for c in cands if c[6].startswith("✅")][:20]
    for nterm, c, _r, x, y, tset, flag in shown:
        out.append(f"\n### [{x}] ↔ [{y}]  · 다리 {nterm}개 `{', '.join(tset)}` · 컨텍스트 cos={c}")
        for who in (x, y):
            t0 = tset[0]
            e = ev.get((who, t0), [""])[0]
            out.append(f"  - **{who}** —({t0})— {e[:88]}")
    out.append("\n## 🚩 다른 공급망 의심 (동음이의 — 루프가 거른 것, 확인용)\n")
    for nterm, c, _r, x, y, tset, flag in [c for c in cands if c[6].startswith("🚩")][:10]:
        out.append(f"- [{x}] ↔ [{y}] `{', '.join(tset)}` cos={c} — 프로파일 분리")

    report = pathlib.Path(cfg.OUT) / "bridge_candidates.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(out), encoding="utf-8")
    print(f"[bridges] {len(cands)} candidate pairs "
          f"(✅{sum(1 for c in cands if c[6].startswith('✅'))} "
          f"🚩{sum(1 for c in cands if c[6].startswith('🚩'))} "
          f"⚠️{sum(1 for c in cands if c[6].startswith('⚠'))})")
    print(f"[bridges] report -> {report}")
    repo.close()



if __name__ == "__main__":
    main()
