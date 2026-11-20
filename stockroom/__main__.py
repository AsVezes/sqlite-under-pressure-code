"""Command-line entry point for the Stockroom Ledger."""

import argparse
import json
from pathlib import Path
import sqlite3

from .environment import initialize_workspace, inspect_workspace, runtime_profile
from .ledger import check_ledger, initialize_ledger
from .transfer import Transfer, transfer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Identify Python's SQLite and the standalone CLI")
    workspace = commands.add_parser("workspace", help="Create an exclusive workspace")
    workspace.add_argument("--parent", type=Path, help="Existing directory for the new workspace")
    identify = commands.add_parser("identity", help="Identify an existing workspace")
    identify.add_argument("database", type=Path)
    init = commands.add_parser("init", help="Install schema v1 and seed F1 in a CP00 workspace")
    init.add_argument("database", type=Path)
    check = commands.add_parser("check", help="Verify schema identity and reconcile F1/O1")
    check.add_argument("database", type=Path)
    move = commands.add_parser("transfer", help="Atomically move units between locations")
    move.add_argument("database", type=Path)
    move.add_argument("id")
    move.add_argument("item_id")
    move.add_argument("source_location_id")
    move.add_argument("destination_location_id")
    move.add_argument("quantity", type=int)
    move.add_argument("--fail-after-debit", action="store_true", help="Roll back after a simulated failure in a disposable workspace")
    args = parser.parse_args()

    try:
        if args.command == "doctor":
            result = runtime_profile()
        elif args.command == "workspace":
            result = initialize_workspace(args.parent)
        elif args.command == "identity":
            result = inspect_workspace(args.database)
        elif args.command == "init":
            result = initialize_ledger(args.database)
        elif args.command == "check":
            result = check_ledger(args.database)
        else:
            request = Transfer(args.id, args.item_id, args.source_location_id,
                               args.destination_location_id, args.quantity)
            result = transfer(args.database, request, fail_after_debit=args.fail_after_debit)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        parser.exit(2, f"stockroom: {error}\n")
    print(json.dumps(result, indent=2))
    return 1 if args.command == "check" and not result["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
