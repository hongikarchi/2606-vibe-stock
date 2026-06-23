"""Entity resolution — cross-lingual, ID-anchored, with match-or-ABSTAIN.

Pipeline (research 02b §1):
  A) deterministic authoritative-ID join (corp_code / CIK / ISIN / ticker)  -> RESOLVED 1.0
  B) time-scoped alias exact match (삼전, 005930, $V-as-of-T)                -> RESOLVED 1.0
  C) rapidfuzz blocking + margin rule -> RESOLVE or ABSTAIN -> PROVISIONAL
must-not-link: different ISIN, or a forbidden parent/subsidiary pair, forces ABSTAIN.

naive_resolve() is the CONTROL: pure surface-string identity, so the demo can show how
many MORE nodes a naive approach would create (삼성전자 / Samsung / 삼전 / 005930 stay split).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process

import config as cfg
from .store.sqlite_repo import SqliteRepository


@dataclass
class ResolutionOutcome:
    surface: str
    status: str               # resolved | provisional
    target_id: str | None     # canonical id (issuer/security) or None
    score: float
    candidates: list[tuple[str, float]]  # [(target_id, score)] sorted desc


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold().strip()


class Resolver:
    """Resolves surface forms against the issuer master held in the repository."""

    def __init__(self, repo: SqliteRepository, as_of: str,
                 must_not_link: list[tuple[str, str]] | None = None):
        self.repo = repo
        self.as_of = as_of
        # symmetric forbidden-merge set
        self.forbidden: set[frozenset[str]] = {
            frozenset(p) for p in (must_not_link or [])
        }
        # Build the candidate gazetteer: canonical_id -> display name (issuers only for
        # importance; securities resolve via alias/ID directly).
        self.universe = {i.issuer_id: i.name for i in repo.get_active_universe(as_of)}
        # name->id and normalized-name->id maps for fuzzy matching
        self._choices = {iid: _norm(name) for iid, name in self.universe.items()}

    # ---- Stage A: authoritative ID --------------------------------------
    def _id_anchor(self, surface: str) -> str | None:
        # alias table holds tickers and ID-like surfaces too; a single exact hit wins
        hits = self.repo.resolve_alias(surface, self.as_of)
        if len(hits) == 1:
            kind, tid = hits[0]
            return tid
        return None

    # ---- Stage C: margin rule over rapidfuzz scores ---------------------
    def _fuzzy(self, surface: str) -> list[tuple[str, float]]:
        q = _norm(surface)
        if not self._choices:
            return []
        # WRatio handles partial / token-order differences well
        results = process.extract(
            q, self._choices, scorer=fuzz.WRatio,
            limit=5, score_cutoff=cfg.RESOLVE["block_min"],
        )
        # results: list of (matched_value, score, key) -> key is issuer_id
        scored = sorted(((key, score / 100.0) for _, score, key in results),
                        key=lambda t: (-t[1], t[0]))
        return scored

    def resolve(self, surface: str) -> ResolutionOutcome:
        # A) deterministic id/alias anchor
        anchored = self._id_anchor(surface)
        if anchored is not None:
            return ResolutionOutcome(surface, "resolved", anchored, 1.0, [(anchored, 1.0)])

        # C) fuzzy + margin rule
        cands = self._fuzzy(surface)
        if not cands:
            return ResolutionOutcome(surface, "provisional", None, 0.0, [])

        top_id, top = cands[0]
        second = cands[1][1] if len(cands) > 1 else 0.0

        # must-not-link: if top two are a forbidden pair AND close, force ABSTAIN
        if len(cands) > 1 and frozenset({top_id, cands[1][0]}) in self.forbidden \
                and (top - second) < cfg.RESOLVE["margin"]:
            return ResolutionOutcome(surface, "provisional", None, top, cands)

        if top >= cfg.RESOLVE["accept"] and (top - second) >= cfg.RESOLVE["margin"]:
            return ResolutionOutcome(surface, "resolved", top_id, top, cands)

        # ambiguous or below floor -> PROVISIONAL (never force-merge, never drop)
        return ResolutionOutcome(surface, "provisional", None, top, cands)


def naive_resolve(surfaces: list[str]) -> int:
    """CONTROL: number of distinct nodes a pure string-identity resolver would create."""
    return len({_norm(s) for s in surfaces})
