#!/usr/bin/env python3
"""L15/C13: stale preflight is not an authorization to debit.

A deterministic correctness pilot, not a queue/throughput benchmark. All
databases are disposable. Connection order is explicit; no sleeps or timing
assumptions are used.
"""
import json
import platform
import sqlite3
import tempfile
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def balance(db):
    return db.execute("SELECT qty FROM inventory WHERE sku='A'").fetchone()[0]


def run():
    with tempfile.TemporaryDirectory(prefix="sqlite-l15-") as directory:
        path = Path(directory) / "inventory.sqlite"
        with sqlite3.connect(path, isolation_level=None, timeout=0) as setup:
            setup.execute("CREATE TABLE inventory(sku TEXT PRIMARY KEY, qty INTEGER NOT NULL CHECK(qty >= 0))")
            setup.execute("INSERT INTO inventory VALUES('A', 10)")
        a = sqlite3.connect(path, isolation_level=None, timeout=0)
        b = sqlite3.connect(path, isolation_level=None, timeout=0)
        try:
            ident = {
                "sqlite_version": a.execute("SELECT sqlite_version()").fetchone()[0],
                "sqlite_source_id": a.execute("SELECT sqlite_source_id()").fetchone()[0],
                "python": platform.python_version(),
                "platform": platform.platform(),
            }
            # Explicit preflight, followed by a competing committed debit.
            observed_preflight = balance(a)
            require(observed_preflight == 10, "unexpected preflight fixture")
            b.execute("BEGIN IMMEDIATE")
            b.execute("UPDATE inventory SET qty=qty-7 WHERE sku='A'")
            b.execute("COMMIT")
            require(balance(a) == 3, "competing debit was not visible")
            # Negative control: a stale preflight is not sufficient. A broken
            # application using qty=qty-6 would violate the CHECK constraint.
            negative_code = None
            a.execute("BEGIN IMMEDIATE")
            try:
                a.execute("UPDATE inventory SET qty=qty-6 WHERE sku='A'")
            except sqlite3.IntegrityError as exc:
                negative_code = getattr(exc, "sqlite_errorcode", None)
                a.execute("ROLLBACK")
            else:
                a.execute("ROLLBACK")
                raise RuntimeError("stale preflight unexpectedly authorized debit")
            require(negative_code is not None and negative_code & 255 == sqlite3.SQLITE_CONSTRAINT,
                    "negative control failed for the wrong reason")
            require(balance(a) == 3, "negative control changed persisted balance")
            # Positive: validation belongs inside the writer transaction.
            a.execute("BEGIN IMMEDIATE")
            current = balance(a)
            require(current == 3, "transactional validation saw unexpected balance")
            requested = 2
            require(current >= requested, "insufficient stock inside transaction")
            a.execute("UPDATE inventory SET qty=qty-? WHERE sku='A'", (requested,))
            a.execute("COMMIT")
            require(balance(b) == 1, "committed result not visible from second connection")
            require(a.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integrity check failed")
            require(not a.in_transaction and not b.in_transaction, "transaction left open")
            return {"identity": ident, "preflight": observed_preflight,
                    "after_competitor": 3, "negative_primary_code": negative_code & 255,
                    "final_balance": balance(b), "checks": {"stale_preflight_rejected": True,
                    "in_transaction_validation": True, "persisted_result": True,
                    "integrity": True, "transactions_closed": True},
                    "limits": "Deterministic two-connection correctness pilot; no queue, batching, p95, fairness or throughput measurements."}
        finally:
            a.close()
            b.close()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
