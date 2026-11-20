"""Command-line entry point for the Stockroom Ledger."""

import argparse
import json
from pathlib import Path
import sqlite3

from .environment import initialize_workspace, inspect_workspace, runtime_profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Identify Python's SQLite and the standalone CLI")
    workspace = commands.add_parser("workspace", help="Create an exclusive workspace")
    workspace.add_argument("--parent", type=Path, help="Existing directory for the new workspace")
    identify = commands.add_parser("identity", help="Identify an existing workspace")
    identify.add_argument("database", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "doctor":
            result = runtime_profile()
        elif args.command == "workspace":
            result = initialize_workspace(args.parent)
        else:
            result = inspect_workspace(args.database)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        parser.exit(2, f"stockroom: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
