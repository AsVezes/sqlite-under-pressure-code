"""CP10: admit a verified restore in isolation and rehearse cutover and return."""
from contextlib import closing
import json
from pathlib import Path
import shutil
from tempfile import mkdtemp
from time import monotonic_ns

from .backup import digest, validate, verify_bundle
from .environment import connect
from .operation import execute, parser


def restore(bundle, parent):
    expected, manifest = verify_bundle(bundle)
    destination = Path(mkdtemp(prefix="stockroom-restore-", dir=parent))
    path = destination / "ledger.db"
    try:
        shutil.copyfile(bundle / "ledger.db", path)
        if digest(path) != manifest["sha256"]:
            raise ValueError("restored bytes differ from validated bundle")
        observed = validate(path)
        if any(observed[k] != expected[k] for k in ("workspace_id", "schema_version", "watermark", "ledger")):
            raise ValueError("restored state differs from validated bundle")
    except BaseException:
        shutil.rmtree(destination)
        raise
    return path, observed


def select(pointer, database):
    staged = pointer.with_suffix(".next")
    staged.write_text(json.dumps({"database": str(database)}) + "\n", encoding="utf-8")
    staged.replace(pointer)


def selected(pointer):
    return Path(json.loads(pointer.read_text(encoding="utf-8"))["database"])


def smoke(path, expected):
    if validate(path)["ledger"] != expected["ledger"]:
        raise ValueError("read smoke mismatch")
    with closing(connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("UPDATE stock_balance SET quantity=quantity WHERE item_id='item-bolt'")
        finally:
            db.execute("ROLLBACK")
    if validate(path)["ledger"] != expected["ledger"]:
        raise ValueError("write smoke changed ledger")


def rehearse(live, bundle, parent):
    begin = monotonic_ns()
    original = validate(live)
    restored, candidate = restore(bundle, parent)
    if candidate["workspace_id"] != original["workspace_id"]:
        raise ValueError("backup belongs to a different ledger")
    gap = original["watermark"] - candidate["watermark"]
    if gap < 0:
        raise ValueError("backup receipt boundary is ahead of the source")
    pointer = restored.parent / "selection.json"
    select(pointer, live)
    select(pointer, restored)
    try:
        smoke(selected(pointer), candidate)
        elapsed = monotonic_ns() - begin
        if validate(live)["ledger"] != original["ledger"]:
            raise ValueError("source changed during the rehearsal")
    finally:
        select(pointer, live)
    return {"restored": str(restored), "selection": str(pointer),
            "returned_to": str(selected(pointer)), "source_watermark": original["watermark"],
            "restored_watermark": candidate["watermark"], "rpo_operations": gap,
            "rto_ns": elapsed, "source_id": candidate["source_id"]}


def main():
    args = parser(__doc__)
    args.add_argument("bundle", type=Path)
    args.add_argument("parent", type=Path)
    options = args.parse_args()
    return execute(lambda: rehearse(options.database.resolve(), options.bundle, options.parent))


if __name__ == "__main__":
    raise SystemExit(main())
