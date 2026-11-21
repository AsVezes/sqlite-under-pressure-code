"""CP10: admit a verified restore in isolation and rehearse cutover and return."""
from contextlib import closing
import json
from pathlib import Path
import shutil
from tempfile import mkdtemp
from time import monotonic_ns
from uuid import uuid4

from tools.e1 import inspect_connection

from .backup import digest, validate, verify_bundle
from .environment import connect
from .operation import execute, parser
from .transfer import MAX_BALANCE, Transfer, apply_in_transaction
from .writer import receipt_for, watermark


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


def require_history_prefix(live, restored, cut):
    with closing(connect(live, read_only=True)) as source, closing(connect(restored, read_only=True)) as candidate:
        source.execute("BEGIN")
        candidate.execute("BEGIN")
        opening = "SELECT item_id, location_id, quantity FROM opening_balance ORDER BY 1, 2"
        history = """
            SELECT r.seq, t.id, t.item_id, t.source_location_id, t.destination_location_id, t.quantity
            FROM receipt r JOIN transfer t ON t.id=r.transfer_id
            WHERE r.seq <= ? ORDER BY r.seq
        """
        if source.execute(opening).fetchall() != candidate.execute(opening).fetchall():
            raise ValueError("backup opening balances differ from the source")
        from itertools import zip_longest
        missing = object()
        for source_row, candidate_row in zip_longest(
            source.execute(history, (cut,)), candidate.execute(history, (cut,)),
            fillvalue=missing,
        ):
            if source_row is missing or candidate_row is missing:
                raise ValueError("backup receipt history length differs from the source")
            if source_row != candidate_row:
                raise ValueError("backup receipt history diverges from the source")


def smoke_request(db):
    position = db.execute("""
        SELECT src.item_id, src.location_id, dst.location_id
        FROM stock_balance src JOIN stock_balance dst
          ON src.item_id=dst.item_id AND src.location_id<>dst.location_id
        WHERE src.quantity>0 AND dst.quantity<?
        ORDER BY 1, 2, 3 LIMIT 1
    """, (MAX_BALANCE,)).fetchone()
    token = uuid4().hex.upper()
    if position is None:
        item, north, south = token, token + "-N", token + "-S"
        db.execute("INSERT INTO item(id,sku) VALUES (?,?)", (item, token))
        db.executemany("INSERT INTO location(id,code,code_history) VALUES (?,?,?)",
                       [(location, location, location) for location in (north, south)])
        quantities = [(item, north, 1), (item, south, 0)]
        for table in ("opening_balance", "stock_balance"):
            db.executemany(f"INSERT INTO {table}(item_id,location_id,quantity) VALUES (?,?,?)", quantities)
        position = (item, north, south)
    return Transfer("restore-smoke-" + token, *position, 1)


def smoke(path, expected):
    if validate(path)["ledger"] != expected["ledger"]:
        raise ValueError("read smoke mismatch")
    with closing(connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            request = smoke_request(db)
            apply_in_transaction(db, request)
            boundary = expected["watermark"] + 1
            if receipt_for(db, request.id) != boundary or watermark(db) != boundary:
                raise ValueError("write smoke did not advance the receipt sequence")
            if not inspect_connection(db)["ok"]:
                raise ValueError("write smoke failed ledger reconciliation")
        finally:
            db.execute("ROLLBACK")
    after = validate(path)
    if (after["ledger"], after["watermark"]) != (expected["ledger"], expected["watermark"]):
        raise ValueError("write smoke changed ledger")


def rehearse(live, bundle, parent):
    begin = monotonic_ns()
    original = validate(live)
    restored, candidate = restore(bundle, parent)
    try:
        if candidate["workspace_id"] != original["workspace_id"]:
            raise ValueError("backup belongs to a different ledger")
        gap = original["watermark"] - candidate["watermark"]
        if gap < 0:
            raise ValueError("backup receipt boundary is ahead of the source")
        require_history_prefix(live, restored, candidate["watermark"])
        smoke(restored, candidate)
    except BaseException:
        shutil.rmtree(restored.parent)
        raise
    pointer = restored.parent / "selection.json"
    select(pointer, live)
    select(pointer, restored)
    try:
        if selected(pointer) != restored:
            raise ValueError("selection did not point to the verified restore")
        elapsed = monotonic_ns() - begin
        current = validate(live)
        if (current["ledger"], current["watermark"]) != (original["ledger"], original["watermark"]):
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
