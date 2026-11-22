"""L06 / C06: DEFERRED versus IMMEDIATE write-lock acquisition.

Run: python3 labs/l06_transactions.py
Only disposable databases; ordered SQL events, no arbitrary sleeps.
"""
import json
import platform
import sqlite3
import tempfile
from pathlib import Path


def require(condition, name):
    if not condition:
        raise RuntimeError("L06 oracle failed: " + name)


def scenario(mode):
    with tempfile.TemporaryDirectory(prefix="sqlite-l06-") as tmp:
        path = Path(tmp) / "lock.sqlite3"
        a = sqlite3.connect(path, timeout=0, isolation_level=None)
        b = sqlite3.connect(path, timeout=0, isolation_level=None)
        try:
            a.execute("PRAGMA journal_mode=DELETE")
            a.execute("CREATE TABLE inventory (id INTEGER PRIMARY KEY, qty INTEGER NOT NULL)")
            a.execute("INSERT INTO inventory VALUES (1, 10)")
            a.execute("BEGIN " + mode)
            if mode == "DEFERRED":
                b.execute("BEGIN IMMEDIATE")
                b.execute("UPDATE inventory SET qty=qty+1 WHERE id=1")
                try:
                    a.execute("UPDATE inventory SET qty=qty+1 WHERE id=1")
                except sqlite3.OperationalError as exc:
                    conflict = {"name": getattr(exc, "sqlite_errorname", None),
                                "code": getattr(exc, "sqlite_errorcode", None)}
                else:
                    raise RuntimeError("DEFERRED unexpectedly acquired write access")
                b.execute("COMMIT")
                a.execute("ROLLBACK")
                expected = 11
            elif mode == "IMMEDIATE":
                try:
                    b.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    conflict = {"name": getattr(exc, "sqlite_errorname", None),
                                "code": getattr(exc, "sqlite_errorcode", None)}
                else:
                    raise RuntimeError("second writer unexpectedly acquired lock")
                a.execute("UPDATE inventory SET qty=qty+2 WHERE id=1")
                a.execute("COMMIT")
                b.execute("BEGIN IMMEDIATE")
                b.execute("UPDATE inventory SET qty=qty+1 WHERE id=1")
                b.execute("COMMIT")
                expected = 13
            else:
                raise ValueError("unsupported mode")
            require(not a.in_transaction and not b.in_transaction, mode + ":transactions_closed")
            observed = b.execute("SELECT qty FROM inventory WHERE id=1").fetchone()[0]
            integrity = b.execute("PRAGMA integrity_check").fetchone()[0]
            checks = {"busy_code": conflict["code"] == sqlite3.SQLITE_BUSY,
                      "busy_name": conflict["name"] == "SQLITE_BUSY",
                      "expected_balance": observed == expected,
                      "integrity": integrity == "ok",
                      "transactions_closed": not a.in_transaction and not b.in_transaction}
            for name, ok in checks.items():
                require(ok, mode + ":" + name)
            return {"mode": mode, "conflict": conflict,
                    "quantity": observed, "checks": checks}
        finally:
            if a.in_transaction:
                a.rollback()
            if b.in_transaction:
                b.rollback()
            a.close()
            b.close()


def run():
    with sqlite3.connect(":memory:") as db:
        source = db.execute("SELECT sqlite_source_id()").fetchone()[0]
    results = [scenario("DEFERRED"), scenario("IMMEDIATE")]
    return {"lab": "L06", "status": "pass", "environment": {
        "python": platform.python_version(), "os": platform.platform(),
        "sqlite_version": sqlite3.sqlite_version, "sqlite_source_id": source},
        "results": results, "limitations": [
            "rollback journal only; two connections in one process",
            "zero busy timeout: fail-fast contention, not scheduling or fairness",
            "no crash, durability, or multi-process inference"]}


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, indent=2, sort_keys=True))
