#!/usr/bin/env python3
"""L05 pilot: atomic transfer and savepoint scope on disposable SQLite fixtures.

Run: python3 labs/l05_atomicity.py
No path arguments; never touches an existing database.
"""
import json
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def connect(path):
    # Explicit SQL boundaries; Python 3.12+ supports autocommit=True.
    if sys.version_info >= (3, 12):
        return sqlite3.connect(path, autocommit=True)
    return sqlite3.connect(path, isolation_level=None)


def state(conn):
    return {
        "balances": [list(r) for r in conn.execute("SELECT id, qty FROM balances ORDER BY id")],
        "ledger": [list(r) for r in conn.execute("SELECT src, dst, qty FROM ledger ORDER BY id")],
    }


def initial(conn):
    conn.executescript("""
        CREATE TABLE balances(id INTEGER PRIMARY KEY, qty INTEGER NOT NULL CHECK(qty >= 0));
        CREATE TABLE ledger(id INTEGER PRIMARY KEY, src INTEGER, dst INTEGER, qty INTEGER NOT NULL);
        INSERT INTO balances VALUES (1, 10), (2, 0);
    """)


def debit(conn):
    cursor = conn.execute("UPDATE balances SET qty=qty-3 WHERE id=1 AND qty>=3")
    if cursor.rowcount != 1:
        raise RuntimeError(f"debit affected {cursor.rowcount} rows; expected exactly one")


def finish(conn):
    conn.execute("UPDATE balances SET qty=qty+3 WHERE id=2")
    conn.execute("INSERT INTO ledger(src,dst,qty) VALUES(1,2,3)")


def run_case(root, name, scenario):
    path = root / (name + ".sqlite3")
    conn = connect(path)
    try:
        initial(conn)
        before = state(conn)
        if scenario == "statement_failure":
            debit(conn)
            # Simulated application exception between independent statements.
        elif scenario == "transaction_failure":
            conn.execute("BEGIN")
            debit(conn)
            conn.execute("ROLLBACK")
        elif scenario == "success":
            conn.execute("BEGIN")
            debit(conn)
            finish(conn)
            conn.execute("COMMIT")
        elif scenario == "savepoint_outer_rollback":
            conn.execute("BEGIN")
            conn.execute("SAVEPOINT attempt")
            debit(conn)
            finish(conn)
            conn.execute("RELEASE attempt")
            conn.execute("ROLLBACK")
        elif scenario == "insufficient":
            conn.execute("BEGIN")
            changed = conn.execute(
                "UPDATE balances SET qty=qty-11 WHERE id=1 AND qty>=11"
            ).rowcount
            if changed != 0:
                raise RuntimeError(f"insufficient-balance update affected {changed} rows")
            conn.execute("ROLLBACK")
        else:
            raise ValueError(scenario)
    finally:
        conn.close()
    reopened = connect(path)
    try:
        after = state(reopened)
        integrity = reopened.execute("PRAGMA integrity_check").fetchone()[0]
        return {"before": before, "after": after, "integrity_check": integrity}
    finally:
        reopened.close()


def main():
    with tempfile.TemporaryDirectory(prefix="sqlite-l05-") as directory:
        root = Path(directory)
        probe = connect(":memory:")
        try:
            identity = {
                "sqlite_version": probe.execute("SELECT sqlite_version()").fetchone()[0],
                "sqlite_source_id": probe.execute("SELECT sqlite_source_id()").fetchone()[0],
                "compile_options": [r[0] for r in probe.execute("PRAGMA compile_options")],
            }
        finally:
            probe.close()
        cases = {name: run_case(root, name, name) for name in (
            "statement_failure", "transaction_failure", "success",
            "savepoint_outer_rollback", "insufficient"
        )}
        base = cases["transaction_failure"]["before"]
        expected_success = {"balances": [[1, 7], [2, 3]], "ledger": [[1, 2, 3]]}
        checks = {
            "statement_failure_exposes_partial_state":
                cases["statement_failure"]["after"]["balances"] == [[1, 7], [2, 0]]
                and cases["statement_failure"]["after"]["ledger"] == [],
            "transaction_failure_rolls_back": cases["transaction_failure"]["after"] == base,
            "success_is_atomic": cases["success"]["after"] == expected_success,
            "release_does_not_commit_outer": cases["savepoint_outer_rollback"]["after"] == base,
            "insufficient_balance_no_effect": cases["insufficient"]["after"] == base,
            "integrity_checks_ok": all(v["integrity_check"] == "ok" for v in cases.values()),
        }
        result = {
            "lab": "L05", "status": "pass" if all(checks.values()) else "fail",
            "environment": {"python": sys.version, "platform": platform.platform(), **identity},
            "cases": cases, "oracles": checks,
            "limitations": [
                "Synthetic standalone pilot, not R2's F1 ledger/invariant O1",
                "Simulated application interruption, not process/power failure",
                "One SQLite connection per case; no concurrency or durability guarantee",
            ],
        }
        print(json.dumps(result, indent=2))
        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
