#!/usr/bin/env python3
"""Create a disposable E1/F1 SQLite fixture and verify O1 without writing."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "fixtures" / "e1_f1.sql"


def initialize(path: Path) -> None:
    """Initialize only a previously nonexistent file (O_EXCL prevents overwrite)."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
    finally:
        connection.close()


def create() -> dict:
    root = Path(tempfile.mkdtemp(prefix="sqlite-under-pressure-e1-")).resolve()
    path = root / "f1 stockroom.sqlite"
    initialize(path)
    connection = sqlite3.connect(path)
    try:
        source_id = connection.execute("SELECT sqlite_source_id()").fetchone()[0]
    finally:
        connection.close()
    return {
        "fixture": "F1-E1",
        "database": str(path),
        "workspace": str(root),
        "python": sys.version.split()[0],
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_source_id": source_id,
        "note": "Disposable workspace; keep until pilot evidence is captured.",
    }


def inspect(path: Path) -> dict:
    """Oracle O1: reconcile every position, journal pair and item conservation."""
    if not path.is_file():
        raise FileNotFoundError(f"Existing SQLite file required: {path}")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        errors = []
        integrity = [r[0] for r in connection.execute("PRAGMA quick_check")]
        if integrity != ["ok"]:
            errors.append("O1_STRUCTURAL_CHECK")
        if list(connection.execute("PRAGMA foreign_key_check")):
            errors.append("O1_FOREIGN_KEY")
        opening = {
            (item, location): quantity
            for item, location, quantity in connection.execute(
                "SELECT item_id, location_id, quantity FROM opening_balance"
            )
        }
        balances = {
            (item, location): quantity
            for item, location, quantity in connection.execute(
                "SELECT item_id, location_id, quantity FROM stock_balance"
            )
        }
        transfers = list(connection.execute(
            "SELECT id, item_id, source_location_id, "
            "destination_location_id, quantity FROM transfer ORDER BY id"
        ))
        journal = list(connection.execute(
            "SELECT transfer_id, item_id, location_id, delta "
            "FROM journal_entry ORDER BY transfer_id, id"
        ))
        # SQLite's INTEGER affinity and CHECK(quantity >= 0) can still store
        # nonnumeric TEXT. Never allow Python arithmetic or comparisons to
        # misclassify such rows or turn an oracle failure into a traceback.
        quantities = (
            list(opening.values())
            + list(balances.values())
            + [row[4] for row in transfers]
            + [row[3] for row in journal]
        )
        if any(type(quantity) is not int for quantity in quantities):
            errors.append("O1_NONINTEGER_QUANTITY")
            return {
                "oracle": "O1",
                "ok": False,
                "errors": sorted(set(errors)),
                "balances": [],
                "transfers": len(transfers),
                "journal_entries": len(journal),
            }
        entries_by_transfer = {}
        deltas = {}
        for transfer_id, item, location, delta in journal:
            entries_by_transfer.setdefault(transfer_id, []).append(
                (item, location, delta)
            )
            key = (item, location)
            deltas[key] = deltas.get(key, 0) + delta

        if set(opening) != set(balances):
            errors.append("O1_POSITION_SET")
        for key in sorted(set(opening) | set(balances) | set(deltas)):
            expected = opening.get(key, 0) + deltas.get(key, 0)
            actual = balances.get(key)
            if actual is None or actual < 0 or actual != expected:
                errors.append("O1_BALANCE_MISMATCH:" + ":".join(key))

        transfer_ids = set()
        for transfer_id, item, source, destination, quantity in transfers:
            transfer_ids.add(transfer_id)
            expected = sorted([
                (item, source, -quantity),
                (item, destination, quantity),
            ])
            if sorted(entries_by_transfer.get(transfer_id, [])) != expected:
                errors.append("O1_JOURNAL_PAIR:" + transfer_id)
        for transfer_id in sorted(set(entries_by_transfer) - transfer_ids):
            errors.append("O1_ORPHAN_JOURNAL:" + transfer_id)

        for item in sorted({key[0] for key in set(opening) | set(balances)}):
            before = sum(qty for (i, _), qty in opening.items() if i == item)
            after = sum(qty for (i, _), qty in balances.items() if i == item)
            if before != after:
                errors.append("O1_CONSERVATION:" + item)

        errors = sorted(set(errors))
        return {
            "oracle": "O1",
            "ok": not errors,
            "errors": errors,
            "balances": [
                {"item_id": item, "location_id": location, "quantity": qty}
                for (item, location), qty in sorted(balances.items())
            ],
            "transfers": len(transfers),
            "journal_entries": len(journal),
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create", help="create a unique disposable F1 database")
    check = commands.add_parser("check", help="run read-only O1")
    check.add_argument("database", type=Path)
    args = parser.parse_args()
    try:
        result = create() if args.command == "create" else inspect(args.database)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result.get("ok", True) else 1
    except (OSError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
