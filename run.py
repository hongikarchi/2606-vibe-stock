"""run.py — orchestrate the offline stock knowledge-graph pipeline end-to-end.

  ingest -> prefilter -> extract -> resolve -> store -> analyze -> export

Produces out/skg.db and out/vault/ (open the vault in Obsidian). Fully offline,
deterministic, no API keys. Run twice -> byte-identical vault.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# vault files are UTF-8; also make the console UTF-8 so Korean prints (cp949 garbles it)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg import ingest, prefilter
from skg.analyze import detectors, pagerank
from skg.analyze.pagerank import ranked
from skg.export import obsidian
from skg.extract.fixture_extractor import FixtureExtractor
from skg.models import (
    Alias,
    AnalysisResult,
    Claim,
    Issuer,
    Listing,
    Mention,
    Security,
    Source,
)
from skg.resolve import Resolver, naive_resolve
from skg.store import make_repo
from skg.analyze.graph_builder import build_credible, build_naive


def _load_issuer_master(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    issuers = [Issuer(**i) for i in data.get("issuers", [])]
    securities = [Security(**s) for s in data.get("securities", [])]
    listings = [Listing(**ls) for ls in data.get("listings", [])]
    aliases = [Alias(**a) for a in data.get("aliases", [])]
    must_not_link = [tuple(p) for p in data.get("must_not_link", [])]
    return issuers, securities, listings, aliases, must_not_link


def _load_sources(path: Path) -> list[Source]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Source(**s) for s in data]


def main(repo=None, corpus_dir=None, extractor=None, issuer_master_path=None,
         sources_path=None, as_of=None, wipe=True) -> None:
    """Run the pipeline once. Called with no args it reproduces the offline fixture demo.
    The accumulating loop (loop_build.py) injects a Neo4j repo, the real-corpus dir, the
    layered extractor, and wipe=False so the graph is never destroyed between batches."""
    as_of = as_of or cfg.AS_OF_NOW
    corpus_dir = corpus_dir or (cfg.FIXTURES / "corpus")
    issuer_master_path = issuer_master_path or (cfg.FIXTURES / "issuer_master.json")
    sources_path = sources_path or (cfg.FIXTURES / "sources.json")

    # fresh OUTPUT each run (deterministic vault). Only the filesystem out/ is wiped here;
    # the storage backend is NEVER wiped from main() (the Neo4j graph must accumulate).
    if wipe and cfg.OUT.exists():
        shutil.rmtree(cfg.OUT)
    cfg.OUT.mkdir(parents=True, exist_ok=True)

    # 1) INGEST -----------------------------------------------------------
    docs = ingest.read_corpus(corpus_dir)
    print(f"[ingest] {len(docs)} docs")

    # 2) PREFILTER (near-dup collapse, origin-vs-amplifier) ---------------
    docs = prefilter.run(docs)
    dup_groups = {d.dup_group_id for d in docs if d.dup_group_id}
    collapsed = sum(1 for d in docs if d.is_amplifier)
    print(f"[prefilter] {len(dup_groups)} dup-group(s); {collapsed} amplifier(s) collapsed")

    # 3) EXTRACT ----------------------------------------------------------
    extractor = extractor or FixtureExtractor(cfg.FIXTURES / "extractions")
    extractions = {d.doc_id: extractor.extract(d) for d in docs}

    # 4) STORE schema + master + sources ----------------------------------
    owns_repo = repo is None  # only close a repo we created; an injected one is the caller's
    repo = repo or make_repo(cfg)
    repo.init_schema()
    sources = _load_sources(sources_path)
    repo.write_sources(sources)
    src_by_id = {s.source_id: s for s in sources}
    issuers, securities, listings, aliases, must_not_link = _load_issuer_master(
        issuer_master_path
    )
    repo.write_issuer_master(issuers, securities, listings, aliases)

    # 5) RESOLVE + build claims/mentions ----------------------------------
    resolver = Resolver(repo, as_of, must_not_link=must_not_link)
    doc_by_id = {d.doc_id: d for d in docs}

    # resolve a surface form to a canonical node key; both subjects AND objects go
    # through this so one entity is the SAME node whether it appears as subject or object.
    def resolve_key(surface: str) -> tuple[str, str, str | None]:
        """Return (node_key, status, canonical_target_id_or_None)."""
        if not surface:
            return "", "resolved", None
        outcome = resolver.resolve(surface)
        if outcome.target_id:
            return outcome.target_id, "resolved", outcome.target_id
        # unresolved -> stable provisional key (never force-merged, excluded from importance)
        return f"provisional::{surface}", "provisional", None

    claims: list[Claim] = []
    mentions: list[Mention] = []
    all_surfaces: list[str] = []
    # IDs are CONTENT-STABLE (doc_id + per-doc index), not a global running counter, so the
    # accumulating loop MERGEs the same claim/mention to the same node every batch (idempotent).
    # A global counter would re-number claims as the corpus grows and duplicate nodes in Neo4j.
    for doc_id, ex in sorted(extractions.items()):
        doc = doc_by_id[doc_id]
        src = src_by_id[doc.source_id]
        for idx, ec in enumerate(ex.claims):
            all_surfaces.append(ec.subject_surface)
            subject_id, status, target = resolve_key(ec.subject_surface)
            object_key, _, _ = resolve_key(ec.object_text)
            mentions.append(Mention(
                mention_id=f"{doc_id}#m{idx}", doc_id=doc_id, source_id=doc.source_id,
                surface_form=ec.subject_surface, resolved_target_id=target,
                resolution_status=status, source_span=ec.source_span,
                event_time=doc.event_time, ingest_time=doc.ingest_time,
                knowledge_time=doc.ingest_time, dup_group_id=doc.dup_group_id,
                is_amplifier=doc.is_amplifier,
            ))
            claims.append(Claim(
                claim_id=f"{doc_id}#c{idx}", doc_id=doc_id, source_id=doc.source_id,
                source_credibility=src.credibility,
                subject_id=subject_id, relation=ec.relation, object_text=object_key,
                claim_key=ec.claim_key, stance=ec.stance, source_span=ec.source_span,
                span_start=ec.span_start, span_end=ec.span_end,
                event_time=doc.event_time, ingest_time=doc.ingest_time,
                knowledge_time=doc.ingest_time, dup_group_id=doc.dup_group_id,
                is_amplifier=doc.is_amplifier,
            ))
    repo.write_mentions(mentions)
    repo.write_claims(claims)

    naive_nodes = naive_resolve(all_surfaces)
    canonical_nodes = len({c.subject_id for c in claims if not c.subject_id.startswith("provisional::")})
    print(f"[resolve] naive string-match: {naive_nodes} nodes  |  "
          f"ID-anchored canonical: {canonical_nodes} nodes")

    # 6) ANALYZE — credibility-weighted PPR vs naive (TRUE over LOUD) ------
    stored_claims = repo.get_claims(as_of)
    # provisional subjects/objects must NOT carry importance -> exclude those edges
    def keep(c):
        return not c.subject_id.startswith("provisional::") \
            and not (c.object_text or "").startswith("provisional::")
    ranked_claims = [c for c in stored_claims if keep(c)]

    g_naive = build_naive(ranked_claims)
    g_cred, trust_seeds = build_credible(ranked_claims, src_by_id)

    naive_scores = pagerank.naive_ppr(g_naive)
    cred_scores = pagerank.credible_ppr(g_cred, trust_seeds)

    naive_rank = {n: rk for n, _, rk in ranked(naive_scores)}

    # DISPLAY only entity nodes (canonical ids), never source nodes. Re-rank within the
    # entity-only subset so ranks shown to the human are dense (#1..#N over entities).
    entity_ids = {i.issuer_id for i in issuers} | {s.security_id for s in securities}
    cred_entities = {n: s for n, s in cred_scores.items() if n in entity_ids}
    naive_entities = {n: s for n, s in naive_scores.items() if n in entity_ids}
    naive_entity_rank = {n: rk for n, _, rk in ranked(naive_entities)}
    cred_ranked = ranked(cred_entities)

    m_raw, k_eff = _km_counts(ranked_claims)
    trusted = _trusted_share(src_by_id, ranked_claims)
    name_of = {i.issuer_id: i.name for i in issuers}
    issuer_name = {i.issuer_id: i.name for i in issuers}
    for s in securities:
        cls = "보통주" if s.share_class == "common" else "우선주"
        name_of[s.security_id] = f"{issuer_name.get(s.issuer_id, s.issuer_id)} {cls} ({s.security_id})"

    # detectors run ONCE over the whole corpus; per-entity flags are attached by subject id.
    gazetteer = {a.surface_form for a in aliases} | {i.name for i in issuers}
    # alias_map: surface form -> canonical display name, so an extractor using a different
    # alias for the same entity is not mis-counted as an omission (삼전 -> 삼성전자).
    alias_map = {a.surface_form: issuer_name.get(a.target_id, a.surface_form)
                 for a in aliases if a.target_kind == "issuer"}
    for i in issuers:
        alias_map[i.name] = i.name
    all_flags = detectors.run_all(repo, extractions, docs, as_of,
                                  gazetteer=gazetteer, alias_map=alias_map)
    flags_by_entity = _flags_by_entity(all_flags, name_of)

    results: list[AnalysisResult] = []
    for node, score, rk in cred_ranked:
        results.append(AnalysisResult(
            entity_id=name_of.get(node, node), as_of=as_of,
            ppr_naive=naive_entities.get(node, 0.0), ppr_credible=score,
            rank_naive=naive_entity_rank.get(node, 0), rank_credible=rk,
            k_effective=k_eff.get(node, 0), m_raw=m_raw.get(node, 0),
            trusted_share=trusted.get(node, 0.0),
            flags=flags_by_entity.get(node, {}),
        ))
    repo.write_analysis_results(results)
    _print_detector_summary(all_flags)

    # headline contrast line
    _print_headline(results)

    # bi-temporal demo: who existed now vs in the past (survivorship), + ticker reuse
    universe_now = [i.name for i in repo.get_active_universe(cfg.AS_OF_NOW)]
    universe_past = [i.name for i in repo.get_active_universe(cfg.AS_OF_PAST)]
    bitemporal = {
        "as_of_now": cfg.AS_OF_NOW,
        "as_of_past": cfg.AS_OF_PAST,
        "universe_now": sorted(universe_now),
        "universe_past": sorted(universe_past),
        "only_in_past": sorted(set(universe_past) - set(universe_now)),
        "ticker_reuse": {
            "$V @2007": [issuer_name.get(t, t) for _, t in repo.resolve_alias("$V", "2007-06-01T00:00:00")],
            "$V @2026": [issuer_name.get(t, t) for _, t in repo.resolve_alias("$V", "2026-06-01T00:00:00")],
        },
    }
    survivor = ", ".join(bitemporal["only_in_past"]) or "(없음)"
    print(f"[bi-temporal] 과거에만 존재(생존편향 방지): {survivor}")

    # entity detail for rich pages: aliases collapsed, securities, relationships, citations
    entity_detail = _entity_detail(issuers, securities, aliases, ranked_claims,
                                   src_by_id, name_of, issuer_name)

    # 7) EXPORT -----------------------------------------------------------
    stored_results = repo.get_analysis_results(as_of)
    obsidian.write_vault(stored_results, all_flags, bitemporal, entity_detail,
                         as_of, cfg.VAULT)
    hits = obsidian.guardrail_scan(cfg.VAULT)
    print(f"[export] vault -> {cfg.VAULT}   (open in Obsidian)")
    print(f"[guardrail] forbidden-vocab hits: {len(hits)}")
    if owns_repo:
        repo.close()


def _km_counts(claims):
    """Per ENTITY (the thing being talked about): m_raw = number of mentions/endorsements;
    k_eff = number of distinct effective-independent groups (dup-collapsed). A pump of 5
    copy-paste posts about an entity => m_raw=5, k_eff=1."""
    from collections import defaultdict
    raw = defaultdict(int)
    groups = defaultdict(set)
    for c in claims:
        # the entity under discussion is the claim's subject (endorsement target)
        tgt = c.subject_id
        raw[tgt] += 1
        groups[tgt].add(c.dup_group_id or f"solo_{c.claim_id}")
    m_raw = dict(raw)
    k_eff = {k: len(v) for k, v in groups.items()}
    return m_raw, k_eff


def _trusted_share(sources, claims):
    """Fraction of an entity's endorsement credibility-mass that comes from trusted sources."""
    from collections import defaultdict
    total = defaultdict(float)
    trusted = defaultdict(float)
    for c in claims:
        v = c.subject_id
        w = c.source_credibility
        total[v] += w
        if c.source_credibility >= cfg.TRUSTED_THRESHOLD:
            trusted[v] += w
    return {v: (trusted[v] / total[v] if total[v] else 0.0) for v in total}


def _flags_by_entity(all_flags, name_of):
    """Attach effective-independent flags to their entity (keyed by canonical node id)."""
    by_entity: dict[str, dict] = {}
    for f in all_flags.get("effective_independent", []):
        by_entity.setdefault(f["entity"], {})["corroboration"] = f["label"]
    for f in all_flags.get("grounding", []):
        by_entity.setdefault(f["subject"], {}).setdefault("grounding", []).append(f["issue"])
    return by_entity


def _entity_detail(issuers, securities, aliases, claims, sources, name_of, issuer_name):
    """Collect, per canonical entity id, the data that makes its page a knowledge node:
    collapsed aliases, securities under the issuer, relationships, and cited claims."""
    from collections import defaultdict
    detail = defaultdict(lambda: {"aliases": set(), "securities": [], "rel_out": [],
                                  "rel_in": [], "claims": []})
    # aliases collapsed into each target
    for a in aliases:
        detail[a.target_id]["aliases"].add(a.surface_form)
    # securities under each issuer
    for s in securities:
        cls = "보통주" if s.share_class == "common" else "우선주"
        detail[s.issuer_id]["securities"].append(f"{cls} {s.security_id}")
    # relationships + claim citations (only for relational, non-sentiment edges)
    for c in claims:
        subj_name = name_of.get(c.subject_id, c.subject_id)
        obj_name = name_of.get(c.object_text, c.object_text)
        src = sources.get(c.source_id)
        src_name = src.name if src else c.source_id
        cite = {
            "relation": c.relation, "object": obj_name, "stance": c.stance,
            "source": src_name, "credibility": c.source_credibility,
            "span": c.source_span,
        }
        detail[c.subject_id]["claims"].append(cite)
        if c.object_text and c.relation != "sentiment":
            detail[c.subject_id]["rel_out"].append((c.relation, obj_name, src_name))
            detail[c.object_text]["rel_in"].append((c.relation, subj_name, src_name))
    # normalize sets -> sorted lists for determinism, key by DISPLAY name
    out = {}
    for eid, d in detail.items():
        out[name_of.get(eid, eid)] = {
            "aliases": sorted(d["aliases"]),
            "securities": sorted(d["securities"]),
            "rel_out": sorted(set(d["rel_out"])),
            "rel_in": sorted(set(d["rel_in"])),
            "claims": d["claims"],
        }
    return out


def _print_detector_summary(all_flags):
    n_om = len(all_flags.get("omission", []))
    n_skew = len(all_flags.get("stance_dispersion", []))
    n_ground = len(all_flags.get("grounding", []))
    n_km = len(all_flags.get("effective_independent", []))
    print(f"[detectors] omission={n_om}  stance-skew={n_skew}  "
          f"grounding-flags={n_ground}  K-of-M={n_km}")


def _print_headline(results):
    """Find the entity most demoted by credibility (the pump) and print the contrast."""
    worst = None
    for r in results:
        if r.rank_naive and r.rank_credible and r.rank_credible > r.rank_naive:
            drop = r.rank_credible - r.rank_naive
            if worst is None or drop > worst[1]:
                worst = (r, drop)
    if worst:
        r = worst[0]
        print(f"[analyze] TRUE-over-LOUD:  {r.entity_id}  "
              f"rank_naive=#{r.rank_naive}  ->  rank_credible=#{r.rank_credible}")
    else:
        print("[analyze] (no credibility-driven demotion detected in this corpus)")


if __name__ == "__main__":
    main()
