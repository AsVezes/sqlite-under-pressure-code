#!/usr/bin/env python3
"""Disposable E1 backup/restore integration with F1 and an oversized source."""

from contextlib import closing
import hashlib
import json
import multiprocessing
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import monotonic

from integration.e1_faults import BASELINE, COMMITTED, WATCHDOG, connect, receive, transfer
from tools.e1 import initialize, inspect


class BackupAborted(Exception):
    pass


def writer(path, pipe):
    with pipe, closing(connect(path)) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        pipe.send("WRITER_READY")
        if receive(pipe) != "COMMIT_TRANSFER":
            raise RuntimeError("unexpected supervisor command")
        transfer(db)
        db.execute("COMMIT")
        pipe.send("WRITER_COMMITTED")
        if receive(pipe) != "RELEASE":
            raise RuntimeError("unexpected supervisor command")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def readonly(path):
    return closing(connect(path.as_uri() + "?mode=ro", uri=True))


def database_state(path):
    with readonly(path) as db:
        return {"user_version": db.execute("PRAGMA user_version").fetchone()[0],
                "integrity": db.execute("PRAGMA integrity_check").fetchall(),
                "watermark": db.execute("SELECT max(id) FROM transfer").fetchone()[0],
                "padding_rows": db.execute("SELECT count(*) FROM padding").fetchone()[0],
                "foreign_keys": db.execute("PRAGMA foreign_key_check").fetchall()}


def backup(source, destination, progress):
    deadline = monotonic() + WATCHDOG

    def bounded_progress(status, remaining, total):
        if monotonic() > deadline:
            raise TimeoutError("backup exceeded its progress deadline")
        progress(status, remaining, total)

    with readonly(source) as src, closing(connect(destination)) as dst:
        src.backup(dst, pages=1, progress=bounded_progress, sleep=0)


def restore(artifact, expected_digest, destination):
    # Called only with paths inside the exclusive fixture workspace.
    if digest(artifact) != expected_digest:
        return {"accepted": False, "reason": "DIGEST"}
    with artifact.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    if digest(destination) != expected_digest:
        return {"accepted": False, "reason": "RESTORED_DIGEST"}
    state = database_state(destination)
    if state["user_version"] != 1:
        return {"accepted": False, "reason": "SCHEMA_VERSION", "state": state}
    oracle = inspect(destination)
    accepted = (state["integrity"] == [("ok",)] and not state["foreign_keys"]
                and state["padding_rows"] == 24 and oracle["ok"])
    return {"accepted": accepted, "reason": None if accepted else "INVARIANTS",
            "state": state, "o1": oracle}


def quantity_vector(oracle):
    return tuple(row["quantity"] for row in oracle["balances"])


def initialize_backup_fixture(source):
    initialize(source)
    with closing(connect(source)) as db:
        mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA user_version=1")
        db.execute("CREATE TABLE padding (id INTEGER PRIMARY KEY, payload BLOB)")
        db.executemany("INSERT INTO padding VALUES (?,zeroblob(4096))",
                       ((i,) for i in range(24)))
    return mode


def experiment(root):
    source = root / "ledger.db"
    mode = initialize_backup_fixture(source)
    control_path = root / "control.db"
    control_steps = []
    backup(source, control_path, lambda *step: control_steps.append(step))
    control_hash = digest(control_path)
    control = restore(control_path, control_hash, root / "control-restored.db")

    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=writer, args=(source, child))
    process.start()
    child.close()
    steps = []
    acks = []
    provisional = root / "provisional.db"
    with parent:
        def progress(status, remaining, total):
            steps.append((status, remaining, total))
            if len(steps) == 1 and status == sqlite3.SQLITE_OK and remaining > 0:
                parent.send("COMMIT_TRANSFER")
                acks.append(receive(parent))

        try:
            acks.append(receive(parent))
            backup(source, provisional, progress)
            parent.send("RELEASE")
            process.join(WATCHDOG)
            if process.is_alive():
                raise TimeoutError("backup writer failed to exit")
            writer_exit = process.exitcode
        finally:
            if process.is_alive():
                process.kill()
                process.join(WATCHDOG)
            process.close()

    provisional_hash = digest(provisional)
    restored_path = root / "restored.db"
    good = restore(provisional, provisional_hash, restored_path)
    good_artifact = root / "backup-ok.db"
    if good["accepted"]:
        provisional.rename(good_artifact)
    attempt = root / "aborted.db"
    aborted_steps = []

    def stop(status, remaining, total):
        aborted_steps.append((status, remaining, total))
        raise BackupAborted

    try:
        backup(source, attempt, stop)
    except BackupAborted:
        aborted = True
    else:
        aborted = False

    rejected_digest_path = root / "reject-digest.db"
    wrong_digest = restore(good_artifact, "0" * 64, rejected_digest_path)
    future = root / "future.db"
    inconsistent = root / "inconsistent.db"
    shutil.copyfile(good_artifact, future)
    shutil.copyfile(good_artifact, inconsistent)
    with closing(connect(future)) as db:
        db.execute("PRAGMA user_version=2")
    with closing(connect(inconsistent)) as db:
        db.execute("UPDATE stock_balance SET quantity=quantity+1 WHERE item_id='item-bolt' AND location_id='loc-north'")
    wrong_schema = restore(future, digest(future), root / "reject-version.db")
    wrong_ledger = restore(inconsistent, digest(inconsistent), root / "reject-o1.db")

    # A reversible smoke write checks the restored file without changing the backup.
    with closing(connect(restored_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM padding WHERE id=0")
        smoke_inside = db.execute("SELECT count(*) FROM padding").fetchone()[0]
        db.execute("ROLLBACK")
    smoke_after = database_state(restored_path)["padding_rows"]
    final_source = database_state(source)
    checks = {
        "control": control["accepted"] and quantity_vector(control["o1"]) == BASELINE
        and control["state"]["watermark"] is None,
        "writer_between_steps": mode == "wal" and writer_exit == 0
        and acks == ["WRITER_READY", "WRITER_COMMITTED"]
        and steps[0][0] == sqlite3.SQLITE_OK and steps[0][1] > 0
        and steps[-1][0] == sqlite3.SQLITE_DONE and steps[-1][1] == 0,
        "backup_watermark": good["accepted"] and quantity_vector(good["o1"]) == COMMITTED
        and good["state"]["watermark"] == final_source["watermark"] == "tx-001",
        "abort_before_completion": aborted and len(aborted_steps) == 1
        and aborted_steps[0][0] == sqlite3.SQLITE_OK and aborted_steps[0][1] > 0
        and digest(good_artifact) == provisional_hash and digest(control_path) == control_hash,
        "bad_digest": wrong_digest["reason"] == "DIGEST" and not rejected_digest_path.exists(),
        "future_schema": wrong_schema["reason"] == "SCHEMA_VERSION",
        "valid_digest_invalid_ledger": wrong_ledger["reason"] == "INVARIANTS"
        and wrong_ledger["state"]["integrity"] == [("ok",)] and not wrong_ledger["o1"]["ok"],
        "restore_smoke": (smoke_inside, smoke_after) == (23, 24),
    }
    with closing(connect(":memory:")) as db:
        source_id = db.execute("SELECT sqlite_source_id()").fetchone()[0]
    return {"sqlite_version": sqlite3.sqlite_version, "sqlite_source_id": source_id,
            "python": sys.version, "oracles": checks, "writer_acks": acks,
            "writer_exit": writer_exit, "backup_steps": steps, "control_steps": control_steps,
            "aborted_steps": aborted_steps, "control": control, "restored": good,
            "negative": [wrong_digest, wrong_schema, wrong_ledger],
            "source": final_source, "smoke": [smoke_inside, smoke_after],
            "artifact_sha256": provisional_hash}


def main():
    with TemporaryDirectory(prefix="sqlite-work-e1-backup-") as tmp:
        result = experiment(Path(tmp))
    print(json.dumps(result, indent=2))
    return 0 if all(result["oracles"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
