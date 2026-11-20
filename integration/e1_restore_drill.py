#!/usr/bin/env python3
"""Rehearse a restore cutover and return using a disposable F1 service pointer."""

from contextlib import closing
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic_ns

import sqlite3

from integration.e1_backup import backup, database_state, digest, initialize_backup_fixture, restore
from integration.e1_faults import connect, transfer
from tools.e1 import inspect

SOURCE = "service-origin.db"
RESTORED = "service-restored.db"


def select(root, name):
    # This pointer only selects databases within the newly created fixture.
    stage = root / "selection.next"
    stage.write_text(name + "\n", encoding="utf-8")
    stage.replace(root / "selection")


def inspect_selected(root):
    name = (root / "selection").read_text(encoding="utf-8").strip()
    if name not in (SOURCE, RESTORED):
        raise ValueError(f"unknown service database {name!r}")
    path = root / name
    return {"selected": name, "state": database_state(path), "o1": inspect(path)}


def commit_transfer(path, identifier, units):
    with closing(connect(path)) as db:
        db.execute("PRAGMA synchronous=FULL")
        transfer(db, identifier, units)
        db.execute("COMMIT")
        return monotonic_ns()


def measure(root):
    source = root / SOURCE
    restored = root / RESTORED
    artifact = root / "backup.db"
    select(root, SOURCE)
    mode = initialize_backup_fixture(source)
    first_commit = commit_transfer(source, "tx-001", 3)
    backup(source, artifact, lambda *_: None)
    backup_hash = digest(artifact)
    last_eligible_commit = commit_transfer(source, "tx-002", 1)
    origin = inspect_selected(root)
    origin_hash = digest(source)

    declared = monotonic_ns()
    rejected = restore(artifact, "0" * 64, restored)
    after_invalid = inspect_selected(root)
    verified = restore(artifact, backup_hash, restored)
    if not verified["accepted"]:
        raise RuntimeError(f"backup rejected: {verified['reason']}")
    validation_done = monotonic_ns()
    select(root, RESTORED)
    activated = monotonic_ns()
    after_cutover = inspect_selected(root)
    with closing(connect(root / after_cutover["selected"])) as db:
        transfer(db, "smoke-rollback", 1)
        uncommitted_smoke = db.execute(
            "SELECT count(*) FROM transfer WHERE id='smoke-rollback'"
        ).fetchone()[0]
        db.execute("ROLLBACK")
    after_rollback = inspect_selected(root)
    ready = monotonic_ns()

    # There are no committed writes to the restored database before returning.
    select(root, SOURCE)
    returned = inspect_selected(root)
    return_done = monotonic_ns()

    lost_operations = origin["o1"]["transfers"] - after_cutover["o1"]["transfers"]
    phases = {
        "rejected_artifact_and_validation": validation_done - declared,
        "activated": activated - declared,
        "rto_to_smoke_completion": ready - declared,
        "return_complete": return_done - ready,
        "rpo_between_commit_acks": last_eligible_commit - first_commit,
    }
    oracles = {
        "wal": mode == "wal",
        "reject_before_cutover": rejected["reason"] == "DIGEST"
        and after_invalid == origin,
        "original_watermark": origin["state"]["watermark"] == "tx-002" and origin["o1"]["ok"],
        "restored_watermark": after_cutover["state"]["watermark"] == "tx-001"
        and after_cutover["selected"] == RESTORED and after_cutover["o1"]["ok"],
        "lost_operations": lost_operations == 1,
        "read_write_smoke": uncommitted_smoke == 1 and after_rollback == after_cutover,
        "returned_before_reopening_writes": returned == origin and digest(source) == origin_hash,
        "backup_preserved": digest(artifact) == backup_hash,
        "measurements_ordered": declared <= validation_done <= activated <= ready <= return_done,
    }
    with closing(connect(":memory:")) as db:
        source_id = db.execute("SELECT sqlite_source_id()").fetchone()[0]
    return {"sqlite_version": sqlite3.sqlite_version, "sqlite_source_id": source_id,
            "python": sys.version, "oracles": oracles, "durations_ns": phases,
            "lost_confirmed_operations": lost_operations, "origin": origin,
            "invalid": rejected, "restored": after_cutover, "returned": returned}


def main():
    with TemporaryDirectory(prefix="sqlite-work-restore-drill-") as tmp:
        result = measure(Path(tmp))
    print(json.dumps(result, indent=2))
    return 0 if all(result["oracles"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
