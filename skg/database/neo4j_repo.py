"""Neo4jRepository — Neo4j implementation of the Repository seam.

Design principle: PROPERTIES carry correctness; RELATIONSHIPS carry the browser demo.
Every scalar field of every dataclass is a node property, and every as-of READ is a flat
`MATCH (n:Label) WHERE <property filter> RETURN <properties> ORDER BY <key>` that mirrors
the SQLite column read exactly — never a traversal. Reconstructing dataclasses by walking
edges is precisely where Neo4j would silently diverge from SQLite, so reads ignore edges.
Edges (OF_ISSUER, ABOUT, ...) are MERGE'd only for the localhost:7474 visualization.

Bi-temporal: times are ISO-8601 strings compared LEXICALLY with <= / > — identical to
SQLite's TEXT comparison, so ordering and boundary semantics match without date parsing.

Idempotency: all writes MERGE on a stable key (never CREATE), so a crashed/re-run loop
never duplicates. init_schema() is non-destructive (CREATE CONSTRAINT IF NOT EXISTS).
"""
from __future__ import annotations

import json
from dataclasses import asdict

from neo4j import GraphDatabase, NotificationMinimumSeverity, RoutingControl

from ..models import AnalysisResult, Claim, Issuer, Mention, Source

# Constraints double as the MERGE-backing indexes. Names are arbitrary but stable.
_CONSTRAINTS = [
    ("source_id", "Source", "source_id"),
    ("issuer_id", "Issuer", "issuer_id"),
    ("security_id", "Security", "security_id"),
    ("listing_id", "Listing", "listing_id"),
    ("claim_id", "Claim", "claim_id"),
    ("mention_id", "Mention", "mention_id"),
    ("alias_key", "Alias", "alias_key"),
    ("result_key", "AnalysisResult", "result_key"),
    ("sector_id", "Sector", "sector_id"),
    ("indicator_id", "MacroIndicator", "indicator_id"),
    ("series_id", "PriceSeries", "series_id"),
    ("theme_id", "Theme", "theme_id"),
    ("term", "Term", "term"),
    ("themeday_key", "ThemeDay", "key"),
]


def _strip_none(d: dict) -> dict:
    """Neo4j silently drops null-valued properties; remove them on write so `IS NULL`
    matches absent props (mirrors SQLite) and the field reads back as Python None."""
    return {k: v for k, v in d.items() if v is not None}


def _alias_row(a) -> dict:
    # SQLite uses an AUTOINCREMENT alias_id; Neo4j needs a content key. valid_from is
    # part of it so the time-scoped $V -> Vivendi/Visa pair does not collide.
    r = _strip_none(asdict(a))
    r["alias_key"] = "|".join([
        a.surface_form, a.target_kind, a.target_id, a.valid_from or "",
    ])
    return r


class Neo4jRepository:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self.db = database
        # We deliberately omit null-valued props (mirroring SQLite NULL), which makes Neo4j
        # warn "property key does not exist" on every as-of read. That's expected, not a
        # bug — silence WARNING-level notifications so loop progress stays readable.
        self.driver = GraphDatabase.driver(
            uri, auth=(user, password),
            notifications_min_severity=NotificationMinimumSeverity.OFF,
        )

    def _write(self, query: str, **params) -> None:
        self.driver.execute_query(
            query, database_=self.db, routing_=RoutingControl.WRITE, **params
        )

    def _read(self, query: str, **params):
        return self.driver.execute_query(
            query, database_=self.db, routing_=RoutingControl.READ, **params
        ).records

    # ------------------------------------------------------------------ schema
    def init_schema(self) -> None:
        # Non-destructive: safe to call every loop iteration. Accumulates, never wipes.
        for name, label, prop in _CONSTRAINTS:
            self._write(
                f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )

    def wipe(self) -> None:
        """Delete ALL nodes/relationships. Test-only — never called from the pipeline."""
        self._write("MATCH (n) DETACH DELETE n")

    # ------------------------------------------------------------------ writes
    def write_sources(self, rows: list[Source]) -> None:
        params = []
        for s in rows:
            d = asdict(s)
            d["is_trust_seed"] = int(s.is_trust_seed)  # match SQLite INTEGER 0/1
            params.append(d)
        self._write(
            "UNWIND $rows AS r MERGE (n:Source {source_id: r.source_id}) SET n += r",
            rows=params,
        )

    def write_issuer_master(self, issuers, securities, listings, aliases) -> None:
        self._write(
            "UNWIND $rows AS r MERGE (n:Issuer {issuer_id: r.issuer_id}) SET n += r",
            rows=[_strip_none(asdict(i)) for i in issuers],
        )
        self._write(
            "UNWIND $rows AS r "
            "MERGE (n:Security {security_id: r.security_id}) SET n += r "
            "WITH n, r MATCH (i:Issuer {issuer_id: r.issuer_id}) MERGE (n)-[:OF_ISSUER]->(i)",
            rows=[_strip_none(asdict(s)) for s in securities],
        )
        self._write(
            "UNWIND $rows AS r "
            "MERGE (n:Listing {listing_id: r.listing_id}) SET n += r "
            "WITH n, r MATCH (s:Security {security_id: r.security_id}) "
            "MERGE (n)-[:OF_SECURITY]->(s)",
            rows=[_strip_none(asdict(ls)) for ls in listings],
        )
        # aliases: MERGE on the synthetic content key; link to the target entity (issuer/security)
        self._write(
            "UNWIND $rows AS r "
            "MERGE (a:Alias {alias_key: r.alias_key}) SET a += r "
            "WITH a, r "
            "OPTIONAL MATCH (t) WHERE t.issuer_id = r.target_id OR t.security_id = r.target_id "
            "FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (a)-[:ALIAS_OF]->(t))",
            rows=[_alias_row(a) for a in aliases],
        )

    def write_mentions(self, rows: list[Mention]) -> None:
        params = []
        for m in rows:
            d = _strip_none(asdict(m))
            d["is_amplifier"] = int(m.is_amplifier)
            params.append(d)
        self._write(
            "UNWIND $rows AS r "
            "MERGE (n:Mention {mention_id: r.mention_id}) SET n += r "
            "WITH n, r MATCH (src:Source {source_id: r.source_id}) MERGE (n)-[:MENTIONS]->(src) "
            "WITH n, r WHERE r.resolved_target_id IS NOT NULL "
            "  OPTIONAL MATCH (e) WHERE (e:Issuer AND e.issuer_id = r.resolved_target_id) "
            "    OR (e:Security AND e.security_id = r.resolved_target_id) "
            "  FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | MERGE (n)-[:RESOLVES_TO]->(e))",
            rows=params,
        )

    def write_claims(self, rows: list[Claim]) -> None:
        params = []
        for c in rows:
            d = _strip_none(asdict(c))
            d["span_grounded"] = int(c.span_grounded)  # match SQLite INTEGER 0/1
            d["is_amplifier"] = int(c.is_amplifier)
            params.append(d)
        self._write(
            "UNWIND $rows AS r "
            "MERGE (n:Claim {claim_id: r.claim_id}) SET n += r "
            "WITH n, r MATCH (src:Source {source_id: r.source_id}) MERGE (n)-[:FROM_SOURCE]->(src) "
            "WITH n, r WHERE NOT r.subject_id STARTS WITH 'provisional::' "
            "  OPTIONAL MATCH (e) WHERE (e:Issuer AND e.issuer_id = r.subject_id) "
            "    OR (e:Security AND e.security_id = r.subject_id) "
            "    OR (e:MacroIndicator AND e.indicator_id = r.subject_id) "
            "  FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | MERGE (n)-[:ABOUT]->(e))",
            rows=params,
        )

    def write_analysis_results(self, rows: list[AnalysisResult]) -> None:
        params = []
        for r in rows:
            params.append({
                "result_key": f"{r.entity_id}@{r.as_of}",
                "entity_id": r.entity_id, "as_of": r.as_of,
                "ppr_naive": r.ppr_naive, "ppr_credible": r.ppr_credible,
                "rank_naive": r.rank_naive, "rank_credible": r.rank_credible,
                "k_effective": r.k_effective, "m_raw": r.m_raw,
                "trusted_share": r.trusted_share,
                # dict isn't a valid Neo4j property type -> store JSON (byte-identical to SQLite)
                "flags_json": json.dumps(r.flags, ensure_ascii=False, sort_keys=True),
            })
        self._write(
            "UNWIND $rows AS r "
            "MERGE (n:AnalysisResult {result_key: r.result_key}) SET n += r",
            rows=params,
        )

    # ------------------------------------------- market / connectivity layer
    def write_sectors(self, rows) -> None:
        """:Sector nodes + (:Issuer)-[:IN_SECTOR]->(:Sector). Turns issuer islands into
        sector clusters — the cheapest connectivity (SIC already in the EDGAR submission)."""
        if not rows:
            return
        self._write(
            "UNWIND $rows AS r "
            "MERGE (s:Sector {sector_id: r.sector_id}) "
            "SET s.sic_code = r.sic_code, s.name = r.name, "
            "    s.event_time = r.event_time, s.knowledge_time = r.knowledge_time "
            "WITH s, r MATCH (i:Issuer {issuer_id: r.issuer_id}) MERGE (i)-[:IN_SECTOR]->(s)",
            rows=[_strip_none(asdict(s)) for s in rows],
        )

    def write_macro(self, rows) -> None:
        if not rows:
            return
        self._write(
            "UNWIND $rows AS r MERGE (m:MacroIndicator {indicator_id: r.indicator_id}) SET m += r",
            rows=[_strip_none(asdict(m)) for m in rows],
        )

    def write_price_series(self, rows) -> None:
        """:PriceSeries node (one per ticker, bounded window) + (:Issuer)-[:HAS_PRICE]->(:PriceSeries)."""
        if not rows:
            return
        self._write(
            "UNWIND $rows AS r "
            "MERGE (p:PriceSeries {series_id: r.series_id}) SET p += r "
            "WITH p, r MATCH (i:Issuer {issuer_id: r.issuer_id}) MERGE (i)-[:HAS_PRICE]->(p)",
            rows=[_strip_none(asdict(p)) for p in rows],
        )

    def write_comovements(self, rows) -> None:
        """(:PriceSeries)-[:CO_MOVES_WITH]->(:MacroIndicator). DESCRIPTIVE, gated/labeled:
        corr/window/disclaimer/is_exploratory live on the EDGE. NOT a signal — connects both
        markets' price series to the shared macro hubs (the cross-market connective tissue)."""
        if not rows:
            return
        self._write(
            "UNWIND $rows AS r "
            "MATCH (p:PriceSeries {series_id: r.series_id}) "
            "MATCH (m:MacroIndicator {indicator_id: r.indicator_id}) "
            "MERGE (p)-[c:CO_MOVES_WITH]->(m) "
            "SET c.corr = r.corr, c.n_obs = r.n_obs, c.window_start = r.window_start, "
            "    c.window_end = r.window_end, c.method = r.method, "
            "    c.is_exploratory = r.is_exploratory, c.disclaimer = r.disclaimer, "
            "    c.event_time = r.event_time, c.knowledge_time = r.knowledge_time",
            rows=rows,
        )

    def write_themes(self, themes: list[dict]) -> None:
        """:Theme nodes. theme = {theme_id, label, freq}."""
        if not themes:
            return
        self._write(
            "UNWIND $rows AS r MERGE (t:Theme {theme_id: r.theme_id}) "
            "SET t.label = r.label, t.freq = r.freq",
            rows=themes,
        )

    def write_theme_cooccurrence(self, edges: list[dict]) -> None:
        """(:Theme)-[:CO_OCCURS {weight}]->(:Theme). weight = # headlines both appear in.
        Undirected co-occurrence stored once per unordered pair (a < b). An OBSERVATION."""
        if not edges:
            return
        self._write(
            "UNWIND $rows AS r "
            "MATCH (a:Theme {theme_id: r.a}) MATCH (b:Theme {theme_id: r.b}) "
            "MERGE (a)-[e:CO_OCCURS]->(b) SET e.weight = r.weight",
            rows=edges,
        )

    def write_theme_entity(self, edges: list[dict]) -> None:
        """(:Theme)-[:MENTIONED_WITH {weight}]->(:Issuer|:MacroIndicator). Anchors a theme to
        the concrete entities its headlines were about — so a 반도체 theme links to 삼성전자."""
        if not edges:
            return
        self._write(
            "UNWIND $rows AS r "
            "MATCH (t:Theme {theme_id: r.theme_id}) "
            "MATCH (e) WHERE e.issuer_id = r.entity_id OR e.indicator_id = r.entity_id "
            "MERGE (t)-[x:MENTIONED_WITH]->(e) SET x.weight = r.weight",
            rows=edges,
        )

    def write_terms(self, terms: list[dict]) -> None:
        """:Term nodes (data-driven, emergent). term = {term, df, degree, +optional spark}."""
        if not terms:
            return
        self._write(
            "UNWIND $rows AS r MERGE (t:Term {term: r.term}) "
            "SET t.df = r.df, t.degree = r.degree, t.spark = r.spark",
            rows=[{**t, "spark": t.get("spark", "")} for t in terms],
        )

    def write_term_cooccurrence(self, edges: list[dict]) -> None:
        """(:Term)-[:CO_OCCURS {weight}]->(:Term). Observed co-occurrence in news text."""
        if not edges:
            return
        self._write(
            "UNWIND $rows AS r MATCH (a:Term {term: r.a}) MATCH (b:Term {term: r.b}) "
            "MERGE (a)-[e:CO_OCCURS]->(b) SET e.weight = r.weight",
            rows=edges,
        )

    def clear_terms(self) -> None:
        """Emergent terms are recomputed wholesale each run; drop old ones first."""
        self._write("MATCH (t:Term) DETACH DELETE t")

    def write_theme_days(self, rows: list[dict]) -> None:
        """:ThemeDay {theme_id, day, count, w_bull, w_bear, w_neut} — per-day theme volume +
        stance. ADDITIVE layer alongside the aggregate :Theme nodes (never replaces them).
        This is the storage shape that powers (a) time-decay as a weighted sum over days,
        (b) temporal trend charts, (c) accumulation — future crawl/websocket data just appends
        more day-buckets. MERGE on (theme_id, day) so re-runs overwrite that day, not duplicate."""
        if not rows:
            return
        self._write(
            "UNWIND $rows AS r "
            "MERGE (d:ThemeDay {key: r.theme_id + '@' + r.day}) "
            "SET d.theme_id = r.theme_id, d.day = r.day, d.count = r.count, "
            "    d.w_bull = r.w_bull, d.w_bear = r.w_bear, d.w_neut = r.w_neut "
            "WITH d, r MATCH (t:Theme {theme_id: r.theme_id}) MERGE (t)-[:ON_DAY]->(d)",
            rows=rows,
        )

    def get_theme_days(self, theme_id: str) -> list[dict]:
        """Per-day series for one theme, oldest->newest (for trend charts)."""
        recs = self._read(
            "MATCH (d:ThemeDay {theme_id: $tid}) "
            "RETURN d.day AS day, d.count AS count, d.w_bull AS w_bull, "
            "d.w_bear AS w_bear, d.w_neut AS w_neut ORDER BY d.day",
            tid=theme_id)
        return [dict(r) for r in recs]

    def set_issuer_52w_position(self, positions: dict) -> None:
        """Stamp each issuer with its 52-week position (0-100). Descriptive market-state."""
        if not positions:
            return
        self._write(
            "UNWIND $rows AS r MATCH (i:Issuer {issuer_id: r.iid}) SET i.pos_52w = r.pos",
            rows=[{"iid": k, "pos": v} for k, v in positions.items()],
        )

    def write_ratings(self, rows: list[dict]) -> None:
        """Stamp analyst-ratings JSON on Issuer nodes (consensus + per-firm changes).
        OBSERVATION of institutional ratings — stored with its disclaimer, never our signal."""
        if not rows:
            return
        params = [{"iid": r["issuer_id"],
                   "consensus": json.dumps(r["consensus"], ensure_ascii=False),
                   "changes": json.dumps(r["changes"], ensure_ascii=False),
                   "disclaimer": r["disclaimer"], "kt": r["knowledge_time"]}
                  for r in rows]
        self._write(
            "UNWIND $rows AS r MATCH (i:Issuer {issuer_id: r.iid}) "
            "SET i.ratings_consensus = r.consensus, i.ratings_changes = r.changes, "
            "    i.ratings_disclaimer = r.disclaimer, i.ratings_kt = r.kt",
            rows=params)

    def get_issuer_symbols(self) -> list[tuple[str, str]]:
        """(issuer_id, yfinance_symbol). US tickers as-is; KR need .KS/.KQ from the listing venue."""
        rows = self._read(
            "MATCH (i:Issuer)<-[:OF_ISSUER]-(:Security)<-[:OF_SECURITY]-(l:Listing) "
            "RETURN i.issuer_id AS iid, l.ticker AS ticker, l.venue AS venue")
        out = []
        for r in rows:
            iid, ticker, venue = r["iid"], r["ticker"], r["venue"]
            if iid.startswith("DART"):
                sym = f"{ticker}.{'KQ' if venue == 'KQ' else 'KS'}"
            else:
                sym = ticker
            out.append((iid, sym))
        return out

    def get_issuer_tickers(self) -> list[tuple[str, str, str]]:
        """(issuer_id, security_id, ticker) for issuers that have a listing — the price fetcher input."""
        recs = self._read(
            "MATCH (i:Issuer)<-[:OF_ISSUER]-(sec:Security)<-[:OF_SECURITY]-(l:Listing) "
            "RETURN i.issuer_id AS iid, sec.security_id AS sid, l.ticker AS ticker "
            "ORDER BY i.issuer_id"
        )
        return [(r["iid"], r["sid"], r["ticker"]) for r in recs]

    # ------------------------------------------------------------------ reads
    # Each read mirrors the SQLite WHERE/ORDER BY exactly. as_of is a lexical string compare.
    def get_active_universe(self, as_of: str) -> list[Issuer]:
        recs = self._read(
            "MATCH (i:Issuer) WHERE i.knowledge_time <= $as_of "
            "AND i.status_valid_from <= $as_of "
            "AND (i.status_valid_to IS NULL OR i.status_valid_to > $as_of) "
            "RETURN i.issuer_id AS issuer_id, i.name AS name, "
            "i.listing_status AS listing_status, i.status_valid_from AS status_valid_from, "
            "i.status_valid_to AS status_valid_to, i.knowledge_time AS knowledge_time "
            "ORDER BY i.issuer_id",
            as_of=as_of,
        )
        return [Issuer(r["issuer_id"], r["name"], r["listing_status"],
                       r["status_valid_from"], r["status_valid_to"], r["knowledge_time"])
                for r in recs]

    def resolve_alias(self, surface_form: str, as_of: str) -> list[tuple[str, str]]:
        recs = self._read(
            "MATCH (a:Alias) WHERE a.surface_form = $surface AND a.valid_from <= $as_of "
            "AND (a.valid_to IS NULL OR a.valid_to > $as_of) "
            "RETURN a.target_kind AS target_kind, a.target_id AS target_id "
            "ORDER BY a.target_kind, a.target_id",
            surface=surface_form, as_of=as_of,
        )
        return [(r["target_kind"], r["target_id"]) for r in recs]

    def get_claims(self, as_of: str) -> list[Claim]:
        recs = self._read(
            "MATCH (c:Claim) WHERE c.knowledge_time <= $as_of "
            "RETURN c {.*} AS c ORDER BY c.claim_id",
            as_of=as_of,
        )
        return [self._claim(r["c"]) for r in recs]

    def get_mentions(self, as_of: str) -> list[Mention]:
        recs = self._read(
            "MATCH (m:Mention) WHERE m.knowledge_time <= $as_of "
            "RETURN m {.*} AS m ORDER BY m.mention_id",
            as_of=as_of,
        )
        out = []
        for r in recs:
            m = r["m"]
            out.append(Mention(
                m["mention_id"], m["doc_id"], m["source_id"], m["surface_form"],
                m.get("resolved_target_id"), m["resolution_status"], m["source_span"],
                m["event_time"], m["ingest_time"], m["knowledge_time"],
                m.get("dup_group_id"), bool(m["is_amplifier"]),
            ))
        return out

    def get_sources(self) -> dict[str, Source]:
        recs = self._read("MATCH (s:Source) RETURN s {.*} AS s ORDER BY s.source_id")
        out = {}
        for r in recs:
            s = r["s"]
            out[s["source_id"]] = Source(
                s["source_id"], s["name"], s["source_type"], s["credibility_class"],
                s["credibility"], bool(s["is_trust_seed"]),
            )
        return out

    def get_analysis_results(self, as_of: str) -> list[AnalysisResult]:
        recs = self._read(
            "MATCH (a:AnalysisResult) WHERE a.as_of = $as_of "
            "RETURN a {.*} AS a ORDER BY a.rank_credible, a.entity_id",
            as_of=as_of,
        )
        out = []
        for r in recs:
            a = r["a"]
            out.append(AnalysisResult(
                a["entity_id"], a["as_of"], a["ppr_naive"], a["ppr_credible"],
                a["rank_naive"], a["rank_credible"], a["k_effective"], a["m_raw"],
                a["trusted_share"], json.loads(a["flags_json"]),
            ))
        return out

    @staticmethod
    def _claim(c: dict) -> Claim:
        return Claim(
            claim_id=c["claim_id"], doc_id=c["doc_id"], source_id=c["source_id"],
            source_credibility=c["source_credibility"], subject_id=c["subject_id"],
            relation=c["relation"], object_text=c["object_text"], claim_key=c["claim_key"],
            stance=c["stance"], source_span=c["source_span"], span_start=c["span_start"],
            span_end=c["span_end"], span_grounded=bool(c["span_grounded"]),
            event_time=c["event_time"], ingest_time=c["ingest_time"],
            knowledge_time=c["knowledge_time"], dup_group_id=c.get("dup_group_id"),
            is_amplifier=bool(c["is_amplifier"]), superseded_by=c.get("superseded_by"),
            contradicts=c.get("contradicts"),
        )

    # ------------------------------------------------------------------ misc
    def node_count(self) -> int:
        recs = self._read("MATCH (n) RETURN count(n) AS c")
        return recs[0]["c"]

    def close(self) -> None:
        self.driver.close()
