"""CP04: capture a passive WAL observation without interpreting file size as backlog."""
from contextlib import closing
from time import monotonic_ns

from .environment import connect
from .ledger import require_version
from .operation import execute, parser
from .storage import current


def event(events, phase, error=None):
    if events is None:
        return
    row = {"phase": phase, "monotonic_ns": monotonic_ns()}
    if error is not None:
        row.update(error=str(error), code=getattr(error, "sqlite_errorcode", None),
                   name=getattr(error, "sqlite_errorname", None))
    events.append(row)


def observe(path):
    with closing(connect(path)) as db:
        require_version(db, 1)
        state = current(db)
        busy, frames, backfilled = db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        return {"profile": state, "checkpoint": {
            "busy": busy, "frames": frames, "backfilled": backfilled,
        }}


def main():
    args = parser(__doc__).parse_args()
    return execute(lambda: observe(args.database))


if __name__ == "__main__":
    raise SystemExit(main())
