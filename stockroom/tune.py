"""CP07: compare one index against identical data and retain write-side evidence."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from .environment import connect
from .ledger import check_ledger, require_ledger, write_transaction
from .operation import execute, parser
from .report import measure
from .transfer import Transfer
from .writer import submit

INDEX = "transfer_item_destination_id"


def copy_database(source, destination):
    with closing(connect(source, read_only=True)) as src:
        with closing(sqlite3.connect(destination, autocommit=True)) as dst:
            src.backup(dst)


def index(path, enabled):
    with closing(connect(path)) as db:
        with write_transaction(db):
            require_ledger(db)
            if enabled:
                db.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} "
                           "ON transfer(item_id,destination_location_id,id)")
            else:
                db.execute(f"DROP INDEX IF EXISTS {INDEX}")
        db.execute("PRAGMA optimize")
    return {"index": INDEX, "enabled": enabled}


def sample_writes(path, prefix, count):
    samples = []
    for i in range(count):
        source, destination = ("loc-north", "loc-south") if i % 2 == 0 else ("loc-south", "loc-north")
        request = Transfer(f"{prefix}-{i}", "item-bolt", source, destination, 1)
        start = perf_counter_ns()
        result = submit(path, request)
        if result["replayed"]:
            raise ValueError(f"reserved exercise ID already exists: {request.id}")
        samples.append(perf_counter_ns() - start)
    return samples


def compare(path, repeats=5):
    with TemporaryDirectory(prefix="stockroom-report-") as temp:
        root = Path(temp)
        common, plain, indexed = (root / name for name in ("common.db", "plain.db", "indexed.db"))
        copy_database(path, common)
        sample_writes(common, "cp07-fill", 64)
        copy_database(common, plain)
        copy_database(common, indexed)
        index(plain, False)
        index(indexed, True)
        result = {}
        for p in (plain, indexed):
            reports = [measure(p, item, repeats) for item in ("item-bolt", "item-nut")]
            writes = sample_writes(p, "cp07-cost", 8)
            if not check_ledger(p)["ok"]:
                raise ValueError("workload failed ledger reconciliation")
            result[p.stem] = {"reports": reports, "write_samples_ns": writes,
                              "bytes_after_writes": p.stat().st_size}
        if [r["rows"] for r in result["plain"]["reports"]] != [
                r["rows"] for r in result["indexed"]["reports"]]:
            raise ValueError("indexed results differ from baseline")
    return result


def main():
    args = parser(__doc__)
    args.add_argument("command", choices=("compare", "install", "remove"))
    args.add_argument("--repeats", type=int, default=5)
    options = args.parse_args()
    if options.command == "compare":
        return execute(lambda: compare(options.database, options.repeats))
    return execute(lambda: index(options.database, options.command == "install"))


if __name__ == "__main__":
    raise SystemExit(main())
