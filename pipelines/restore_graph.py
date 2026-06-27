"""restore_graph.py — restore the full graph from backups/graph_dump.json.gz.

    SKG_STORAGE_BACKEND=neo4j SKG_ALLOW_NEO4J_WIPE=1 python pipelines/restore_graph.py

Safety net for destructive ops (e.g. tag_universe.py --prune). WIPES the current graph and
reloads every node + relationship from the compressed dump (the exact shape export_artifacts
writes: nodes={id,labels,props}, rels={s,t,type,props}). Requires SKG_ALLOW_NEO4J_WIPE=1 so
it can never run by accident. Re-run reanalyze afterwards if you restored over a changed graph.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))

import gzip
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
from skg.database import make_repo

BATCH = 5000


def main() -> None:
    if os.environ.get("SKG_ALLOW_NEO4J_WIPE") != "1":
        print("[restore] refusing: set SKG_ALLOW_NEO4J_WIPE=1 to confirm a full wipe+reload.")
        return
    path = cfg.ROOT / "backups" / "graph_dump.json.gz"
    if not path.exists():
        print(f"[restore] no backup at {path}")
        return
    with gzip.open(path, "rt", encoding="utf-8") as f:
        dump = json.load(f)
    nodes, rels = dump["nodes"], dump["rels"]
    print(f"[restore] backup: {len(nodes)} nodes, {len(rels)} rels")

    repo = make_repo(cfg)
    print("[restore] WIPING current graph...")
    repo._write("MATCH (n) DETACH DELETE n")

    # recreate nodes by their dump id. Add a temporary marker label :_R (+ _rid prop) on every
    # node so we can index _rid and MATCH relationship endpoints fast. labels can't be
    # parameterized in Cypher, so group by label-set and build per-group queries.
    print("[restore] loading nodes...")
    for i in range(0, len(nodes), BATCH):
        _load_nodes_plain(repo, [{"rid": n["id"], "labels": n["labels"], "props": n["props"]}
                                 for n in nodes[i:i + BATCH]])
    repo._write("CREATE INDEX rid_idx IF NOT EXISTS FOR (n:_R) ON (n._rid)")

    print("[restore] loading relationships...")
    for i in range(0, len(rels), BATCH):
        # group by type (relationship type can't be parameterized either)
        from collections import defaultdict
        by_type = defaultdict(list)
        for r in rels[i:i + BATCH]:
            by_type[r["type"]].append({"s": r["s"], "t": r["t"], "props": r["props"]})
        for rtype, rows in by_type.items():
            repo._write(
                "UNWIND $rows AS r MATCH (a:_R {_rid:r.s}),(b:_R {_rid:r.t}) "
                f"CREATE (a)-[rel:`{rtype}`]->(b) SET rel = r.props", rows=rows)

    repo._write("MATCH (n) REMOVE n._rid")              # drop the temporary wiring key
    repo._write("MATCH (n:_R) REMOVE n:_R")             # drop the temporary marker label
    print(f"[restore] DONE. nodes now = {repo.node_count()}")
    repo.close()


def _load_nodes_plain(repo, chunk):
    # labels can't be parameterized, so group by label-set and build per-group queries. Every
    # node also gets a temporary :_R marker label + _rid so relationships can be wired fast.
    from collections import defaultdict
    groups = defaultdict(list)
    for n in chunk:
        groups[tuple(n["labels"])].append({"rid": n["rid"], "props": n["props"]})
    for labels, rows in groups.items():
        lbl = ":".join(f"`{l}`" for l in labels)
        repo._write(
            f"UNWIND $rows AS r CREATE (n:{lbl}:_R) SET n = r.props SET n._rid = r.rid", rows=rows)


if __name__ == "__main__":
    main()
