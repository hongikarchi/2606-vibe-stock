"""SqliteRepository — SQLite implementation of the Repository seam.

The whole schema is one DDL string (no migration framework — see plan: 1-2 person, no
over-engineering). Every fact row is bi-temporal (event_time + knowledge_time); as-of
reads filter `knowledge_time <= as_of`. Times are ISO-8601 TEXT (lexicographically
sortable => deterministic ordering without parsing).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..models import AnalysisResult, Claim, Issuer, Mention, Source

DDL = """
CREATE TABLE sources (
  source_id         TEXT PRIMARY KEY,
  name              TEXT,
  source_type       TEXT,
  credibility_class TEXT,
  credibility       REAL,
  is_trust_seed     INTEGER
);

-- bi-temporal ISSUER MASTER (research 01c fix #3: survivorship). Delisted/merged retained.
CREATE TABLE issuers (
  issuer_id         TEXT PRIMARY KEY,
  name              TEXT,
  listing_status    TEXT,
  status_valid_from TEXT,
  status_valid_to   TEXT,      -- NULL = still valid
  knowledge_time    TEXT
);
CREATE TABLE securities (
  security_id TEXT PRIMARY KEY,
  issuer_id   TEXT REFERENCES issuers(issuer_id),
  share_class TEXT
);
CREATE TABLE listings (
  listing_id  TEXT PRIMARY KEY,
  security_id TEXT REFERENCES securities(security_id),
  ticker      TEXT,
  venue       TEXT
);
-- aliases are TIME-SCOPED edges, never keys ($V=Vivendi pre-2008, Visa post-2008)
CREATE TABLE aliases (
  alias_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  surface_form TEXT,
  lang         TEXT,
  target_kind  TEXT,
  target_id    TEXT,
  valid_from   TEXT,
  valid_to     TEXT
);

CREATE TABLE mentions (
  mention_id         TEXT PRIMARY KEY,
  doc_id             TEXT,
  source_id          TEXT REFERENCES sources(source_id),
  surface_form       TEXT,
  resolved_target_id TEXT,
  resolution_status  TEXT,
  source_span        TEXT,
  event_time         TEXT,
  ingest_time        TEXT,
  knowledge_time     TEXT,
  dup_group_id       TEXT,
  is_amplifier       INTEGER
);

CREATE TABLE claims (
  claim_id           TEXT PRIMARY KEY,
  doc_id             TEXT,
  source_id          TEXT REFERENCES sources(source_id),
  source_credibility REAL,
  subject_id         TEXT,
  relation           TEXT,
  object_text        TEXT,
  claim_key          TEXT,
  stance             TEXT,
  source_span        TEXT,
  span_start         INTEGER,
  span_end           INTEGER,
  span_grounded      INTEGER,
  event_time         TEXT,
  ingest_time        TEXT,
  knowledge_time     TEXT,
  dup_group_id       TEXT,
  is_amplifier       INTEGER,
  superseded_by      TEXT,
  contradicts        TEXT
);

CREATE TABLE analysis_results (
  entity_id     TEXT,
  as_of         TEXT,
  ppr_naive     REAL,
  ppr_credible  REAL,
  rank_naive    INTEGER,
  rank_credible INTEGER,
  k_effective   INTEGER,
  m_raw         INTEGER,
  trusted_share REAL,
  flags_json    TEXT
);
"""


class SqliteRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # one connection; ordering kept deterministic by explicit ORDER BY in reads
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------------ schema
    def init_schema(self) -> None:
        self.conn.executescript(DDL)
        self.conn.commit()

    # ------------------------------------------------------------------ writes
    def write_sources(self, rows: list[Source]) -> None:
        self.conn.executemany(
            "INSERT INTO sources VALUES (?,?,?,?,?,?)",
            [(s.source_id, s.name, s.source_type, s.credibility_class,
              s.credibility, int(s.is_trust_seed)) for s in rows],
        )
        self.conn.commit()

    def write_issuer_master(self, issuers, securities, listings, aliases) -> None:
        self.conn.executemany(
            "INSERT INTO issuers VALUES (?,?,?,?,?,?)",
            [(i.issuer_id, i.name, i.listing_status, i.status_valid_from,
              i.status_valid_to, i.knowledge_time) for i in issuers],
        )
        self.conn.executemany(
            "INSERT INTO securities VALUES (?,?,?)",
            [(s.security_id, s.issuer_id, s.share_class) for s in securities],
        )
        self.conn.executemany(
            "INSERT INTO listings VALUES (?,?,?,?)",
            [(ls.listing_id, ls.security_id, ls.ticker, ls.venue) for ls in listings],
        )
        self.conn.executemany(
            "INSERT INTO aliases (surface_form, lang, target_kind, target_id, valid_from, valid_to)"
            " VALUES (?,?,?,?,?,?)",
            [(a.surface_form, a.lang, a.target_kind, a.target_id, a.valid_from, a.valid_to)
             for a in aliases],
        )
        self.conn.commit()

    def write_mentions(self, rows: list[Mention]) -> None:
        self.conn.executemany(
            "INSERT INTO mentions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(m.mention_id, m.doc_id, m.source_id, m.surface_form, m.resolved_target_id,
              m.resolution_status, m.source_span, m.event_time, m.ingest_time,
              m.knowledge_time, m.dup_group_id, int(m.is_amplifier)) for m in rows],
        )
        self.conn.commit()

    def write_claims(self, rows: list[Claim]) -> None:
        self.conn.executemany(
            "INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(c.claim_id, c.doc_id, c.source_id, c.source_credibility, c.subject_id,
              c.relation, c.object_text, c.claim_key, c.stance, c.source_span,
              c.span_start, c.span_end, int(c.span_grounded), c.event_time, c.ingest_time,
              c.knowledge_time, c.dup_group_id, int(c.is_amplifier), c.superseded_by,
              c.contradicts) for c in rows],
        )
        self.conn.commit()

    def write_analysis_results(self, rows: list[AnalysisResult]) -> None:
        self.conn.executemany(
            "INSERT INTO analysis_results VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(r.entity_id, r.as_of, r.ppr_naive, r.ppr_credible, r.rank_naive,
              r.rank_credible, r.k_effective, r.m_raw, r.trusted_share,
              json.dumps(r.flags, ensure_ascii=False, sort_keys=True)) for r in rows],
        )
        self.conn.commit()

    # ------------------------------------------------------------------ reads
    def get_active_universe(self, as_of: str) -> list[Issuer]:
        cur = self.conn.execute(
            "SELECT * FROM issuers WHERE knowledge_time <= ? "
            "AND status_valid_from <= ? "
            "AND (status_valid_to IS NULL OR status_valid_to > ?) "
            "ORDER BY issuer_id",
            (as_of, as_of, as_of),
        )
        return [Issuer(r["issuer_id"], r["name"], r["listing_status"],
                       r["status_valid_from"], r["status_valid_to"], r["knowledge_time"])
                for r in cur]

    def resolve_alias(self, surface_form: str, as_of: str) -> list[tuple[str, str]]:
        cur = self.conn.execute(
            "SELECT target_kind, target_id FROM aliases "
            "WHERE surface_form = ? AND valid_from <= ? "
            "AND (valid_to IS NULL OR valid_to > ?) "
            "ORDER BY target_kind, target_id",
            (surface_form, as_of, as_of),
        )
        return [(r["target_kind"], r["target_id"]) for r in cur]

    def get_claims(self, as_of: str) -> list[Claim]:
        cur = self.conn.execute(
            "SELECT * FROM claims WHERE knowledge_time <= ? ORDER BY claim_id", (as_of,)
        )
        return [self._claim(r) for r in cur]

    def get_mentions(self, as_of: str) -> list[Mention]:
        cur = self.conn.execute(
            "SELECT * FROM mentions WHERE knowledge_time <= ? ORDER BY mention_id", (as_of,)
        )
        return [Mention(r["mention_id"], r["doc_id"], r["source_id"], r["surface_form"],
                        r["resolved_target_id"], r["resolution_status"], r["source_span"],
                        r["event_time"], r["ingest_time"], r["knowledge_time"],
                        r["dup_group_id"], bool(r["is_amplifier"])) for r in cur]

    def get_sources(self) -> dict[str, Source]:
        cur = self.conn.execute("SELECT * FROM sources ORDER BY source_id")
        return {r["source_id"]: Source(r["source_id"], r["name"], r["source_type"],
                                       r["credibility_class"], r["credibility"],
                                       bool(r["is_trust_seed"])) for r in cur}

    def get_analysis_results(self, as_of: str) -> list[AnalysisResult]:
        cur = self.conn.execute(
            "SELECT * FROM analysis_results WHERE as_of = ? ORDER BY rank_credible, entity_id",
            (as_of,),
        )
        return [AnalysisResult(r["entity_id"], r["as_of"], r["ppr_naive"], r["ppr_credible"],
                               r["rank_naive"], r["rank_credible"], r["k_effective"],
                               r["m_raw"], r["trusted_share"],
                               json.loads(r["flags_json"])) for r in cur]

    @staticmethod
    def _claim(r: sqlite3.Row) -> Claim:
        return Claim(
            claim_id=r["claim_id"], doc_id=r["doc_id"], source_id=r["source_id"],
            source_credibility=r["source_credibility"], subject_id=r["subject_id"],
            relation=r["relation"], object_text=r["object_text"], claim_key=r["claim_key"],
            stance=r["stance"], source_span=r["source_span"], span_start=r["span_start"],
            span_end=r["span_end"], span_grounded=bool(r["span_grounded"]),
            event_time=r["event_time"], ingest_time=r["ingest_time"],
            knowledge_time=r["knowledge_time"], dup_group_id=r["dup_group_id"],
            is_amplifier=bool(r["is_amplifier"]), superseded_by=r["superseded_by"],
            contradicts=r["contradicts"],
        )

    def close(self) -> None:
        self.conn.close()
