"""CP11: replay a combined incident on a disposable copy of the cumulative ledger."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from .backup import capture, validate
from .environment import connect
from .ledger import require_ledger
from .migrate import step
from .operation import execute, parser
from .report import measure
from .restore import rehearse
from .storage import profile
from .transfer import Transfer
from .tune import copy_database
from .writer import submit


def drill(path):
    with TemporaryDirectory(prefix="stockroom-drill-") as temp:
        root = Path(temp)
        live = root / "origin.db"
        copy_database(path, live)
        with closing(connect(live, read_only=True)) as db:
            version = require_ledger(db)["schema_version"]
        stages = []
        if version == 1:
            for _ in range(1000):
                outcome = step(live, 10)
                stages.append(outcome)
                if outcome["schema"] == 2:
                    break
            else:
                raise ValueError("migration did not reach schema v2")
        profile(live, "wal")
        with closing(connect(live, read_only=True)) as db:
            source = db.execute(
                "SELECT location_id FROM stock_balance WHERE item_id='item-bolt' "
                "AND location_id IN ('loc-north','loc-south') AND quantity>0 "
                "ORDER BY quantity DESC,location_id LIMIT 1"
            ).fetchone()
        if source is None:
            raise ValueError("the drill requires an available bolt in north or south")
        src = source[0]
        dst = "loc-south" if src == "loc-north" else "loc-north"
        captured = Transfer(f"cut-{uuid4().hex}", "item-bolt", src, dst, 1)
        submit(live, captured)
        capture_commit = monotonic_ns()
        bundle = Path(capture(live, root)["bundle"])
        operation = Transfer(f"after-{uuid4().hex}", "item-bolt", dst, src, 1)
        submit(live, operation)
        last_commit = monotonic_ns()
        expected = validate(live)
        baseline = measure(live, "item-bolt")
        timeline = rehearse(live, bundle, root)
        restored = Path(timeline["restored"])
        # Validated backup files are standalone. Apply the live profile before
        # resuming commits on the isolated restored branch.
        profile(restored, "wal")
        events = []
        with closing(connect(restored)) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            try:
                submit(restored, operation, wait_ms=0)
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode & 255 != sqlite3.SQLITE_BUSY:
                    raise
                events.extend(exc.events)
            else:
                raise RuntimeError("expected writer contention")
            finally:
                blocker.execute("ROLLBACK")
        receipt = submit(restored, operation)
        # A client discards the first response and resubmits the exact same operation.
        repeat = submit(restored, operation)
        state = validate(restored)
        observed = measure(restored, "item-bolt")
        if (not repeat["replayed"] or repeat["receipt"] != receipt["receipt"]
                or timeline["rpo_operations"] != 1
                or state["watermark"] != expected["watermark"]
                or state["ledger"] != expected["ledger"] or baseline["sha256"] != observed["sha256"]):
            raise RuntimeError("reconciliation failed")
        return {"schema_start": version, "migration": stages,
                "profile": profile(restored), "contention": events,
                "rpo_operations": timeline["rpo_operations"],
                "rpo_between_acknowledgments_ns": last_commit - capture_commit,
                "rto_smoke_ns": timeline["rto_ns"],
                "restored_cut": timeline["restored_watermark"],
                "final_watermark": state["watermark"], "retry_receipt": repeat["receipt"],
                "report_sha256": observed["sha256"], "source_id": state["source_id"],
                "ledger": state["ledger"]}


def main():
    options = parser(__doc__).parse_args()
    return execute(lambda: drill(options.database))


if __name__ == "__main__":
    raise SystemExit(main())
