"""Storage layer. `make_repo(cfg)` selects the Repository implementation behind the
swap seam from config (sqlite for the offline demo, neo4j for the accumulating graph)."""
from __future__ import annotations


def make_repo(cfg):
    """Return the Repository implementation named by cfg.STORAGE_BACKEND."""
    if cfg.STORAGE_BACKEND == "neo4j":
        from .neo4j_repo import Neo4jRepository
        return Neo4jRepository(
            cfg.NEO4J_URI, cfg.NEO4J_USER, cfg.NEO4J_PASSWORD, cfg.NEO4J_DATABASE
        )
    from .sqlite_repo import SqliteRepository
    return SqliteRepository(cfg.DB_PATH)
