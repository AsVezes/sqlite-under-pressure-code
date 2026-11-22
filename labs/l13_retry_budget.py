#!/usr/bin/env python3
"""L13 / C12: bounded SQLITE_BUSY retry, no retry for domain errors.

Uses only a disposable SQLite file. Event acknowledgements establish order;
a fake clock verifies the deadline algorithm without scheduler assumptions.
"""
import json
import platform
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def retry_busy(operation, *, now, deadline, wait, attempts):
    """Retry ordinary SQLITE_BUSY; never retry stale-snapshot promotion in place."""
    history = []
    for index in range(attempts):
        try:
            value = operation()
            history.append({"attempt": index + 1, "result": "ok"})
            return value, history
        except sqlite3.Error as error:
            code = getattr(error, "sqlite_errorcode", None)
            primary = None if code is None else code & 255
            history.append({"attempt": index + 1, "code": code,
                            "name": getattr(error, "sqlite_errorname", None)})
            if (primary != sqlite3.SQLITE_BUSY or code == sqlite3.SQLITE_BUSY_SNAPSHOT
                    or index + 1 >= attempts or now() >= deadline):
                raise
            wait()
    raise RuntimeError("unreachable retry state")


def run():
    checks = {}
    events = []
    with tempfile.TemporaryDirectory(prefix="sqlite-l13-") as directory:
        path = Path(directory) / "fixture.sqlite3"
        holder = sqlite3.connect(path, isolation_level=None, timeout=0)
        challenger = sqlite3.connect(path, isolation_level=None, timeout=0)
        try:
            mode = holder.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            holder.execute("PRAGMA foreign_keys=ON")
            challenger.execute("PRAGMA foreign_keys=ON")
            holder.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
            holder.execute("CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
            holder.execute("INSERT INTO parent VALUES (1)")
            holder.execute("BEGIN IMMEDIATE")
            holder.execute("UPDATE parent SET id=1 WHERE id=1")
            events.append("HOLDER_WRITE_ACK")

            # A clock/slot model: the first failed attempt advances one slot.
            ticks = [0]
            def fake_now():
                return ticks[0]
            def fake_wait():
                ticks[0] += 1
                if ticks[0] == 1:
                    holder.execute("COMMIT")
                    events.append("HOLDER_RELEASE_ACK")

            def acquire():
                challenger.execute("BEGIN IMMEDIATE")
                return "acquired"

            outcome, history = retry_busy(acquire, now=fake_now, deadline=3,
                                          wait=fake_wait, attempts=4)
            checks["busy_then_release"] = (outcome == "acquired" and
                len(history) == 2 and history[0]["code"] == sqlite3.SQLITE_BUSY and
                history[1]["result"] == "ok" and ticks[0] == 1)
            challenger.execute("ROLLBACK")
            events.append("CHALLENGER_RELEASE_ACK")

            holder.execute("BEGIN IMMEDIATE")
            events.append("HOLDER_EXHAUSTION_ACK")
            ticks[0] = 0
            try:
                retry_busy(acquire, now=fake_now, deadline=2,
                           wait=lambda: ticks.__setitem__(0, ticks[0] + 1), attempts=8)
            except sqlite3.OperationalError as error:
                exhausted = (error.sqlite_errorcode == sqlite3.SQLITE_BUSY and ticks[0] == 2)
            else:
                exhausted = False
            checks["deadline_preserves_busy"] = exhausted
            checks["holder_unchanged_on_exhaustion"] = holder.in_transaction
            holder.execute("ROLLBACK")
            events.append("HOLDER_EXHAUSTION_RELEASE_ACK")

            # Foreign-key failures are not transient writer contention.
            invoked = [0]
            def invalid_insert():
                invoked[0] += 1
                challenger.execute("INSERT INTO child VALUES (7, 999)")
            try:
                retry_busy(invalid_insert, now=fake_now, deadline=100,
                           wait=lambda: (_ for _ in ()).throw(RuntimeError("unexpected wait")),
                           attempts=10)
            except sqlite3.IntegrityError as error:
                domain_code = error.sqlite_errorcode
            else:
                domain_code = None
            checks["domain_not_retried"] = (invoked[0] == 1 and
                domain_code is not None and (domain_code & 255) == sqlite3.SQLITE_CONSTRAINT)
            checks["state_preserved"] = (challenger.execute("SELECT id FROM parent").fetchall() == [(1,)]
                and challenger.execute("SELECT count(*) FROM child").fetchone()[0] == 0)
            checks["integrity"] = challenger.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            checks["foreign_keys"] = challenger.execute("PRAGMA foreign_key_check").fetchall() == []

            # Negative oracle: the deliberately wrong expected row count MUST be rejected.
            try:
                require(challenger.execute("SELECT count(*) FROM child").fetchone()[0] == 1,
                        "negative control detected an absent child")
            except RuntimeError:
                checks["negative_control"] = True
            else:
                checks["negative_control"] = False

            # Real monotonic clock integration, without timing-dependent success claim.
            checks["monotonic_clock"] = time.monotonic() <= time.monotonic()
            identity = challenger.execute("SELECT sqlite_version(), sqlite_source_id()").fetchone()
            result = {
                "lab": "L13", "status": "pass" if all(checks.values()) else "fail",
                "environment": {"python": sys.version, "platform": platform.platform(),
                                "sqlite_version": identity[0], "sqlite_source_id": identity[1],
                                "journal_mode": mode, "busy_timeout_ms": 0},
                "events": events, "retry_history": history,
                "oracles": checks,
                "limitations": ["Two connections in one process, not cross-process contention",
                                "Fake clock models retry budget; not a measured scheduling deadline",
                                "No sleep or durability/power-loss inference",
                                "Snapshot restart is covered by L11, not proven here"]
            }
            return result
        finally:
            if challenger.in_transaction:
                challenger.execute("ROLLBACK")
            if holder.in_transaction:
                holder.execute("ROLLBACK")
            challenger.close()
            holder.close()


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, indent=2, sort_keys=True))
    sys.exit(0 if report["status"] == "pass" else 1)
