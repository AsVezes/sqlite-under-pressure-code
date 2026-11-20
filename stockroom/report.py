"""CP06: return a deterministic transfer report and keep its measurement inputs."""
from contextlib import closing
import hashlib
import json
from statistics import median
from time import perf_counter_ns

from .environment import connect
from .ledger import require_version
from .operation import execute, parser

QUERY = (
    "SELECT t.id,t.item_id,t.destination_location_id,t.quantity,r.seq "
    "FROM transfer t JOIN receipt r ON r.transfer_id=t.id "
    "WHERE t.item_id=? ORDER BY t.destination_location_id,t.id"
)


def measure(path, item, repeats=1):
    if not 1 <= repeats <= 100:
        raise ValueError("repeats must be between 1 and 100")
    with closing(connect(path, read_only=True)) as db:
        db.execute("BEGIN")
        require_version(db, 1)
        samples = []
        rows = None
        for _ in range(repeats):
            start = perf_counter_ns()
            current = db.execute(QUERY, (item,)).fetchall()
            samples.append(perf_counter_ns() - start)
            if rows is not None and current != rows:
                raise RuntimeError("report changed within one read snapshot")
            rows = current
        plan = [row[3] for row in db.execute("EXPLAIN QUERY PLAN " + QUERY, (item,))]
        pages = db.execute("PRAGMA page_count").fetchone()[0]
    return {"item": item, "rows": rows, "samples_ns": samples,
            "median_ns": median(samples), "plan": plan, "page_count": pages,
            "sha256": hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()}


def main():
    args = parser(__doc__)
    args.add_argument("item")
    args.add_argument("--repeats", type=int, default=5)
    options = args.parse_args()
    return execute(lambda: measure(options.database, options.item, options.repeats))


if __name__ == "__main__":
    raise SystemExit(main())
