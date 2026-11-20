"""Shared command-line conventions for the cumulative project."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument("database", type=Path, help="Existing Stockroom Ledger database")
    return result


def execute(operation):
    try:
        result = operation()
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        detail = {"error": str(exc)}
        if getattr(exc, "sqlite_errorcode", None) is not None:
            detail.update(code=exc.sqlite_errorcode, name=exc.sqlite_errorname)
        if hasattr(exc, "events"):
            detail["events"] = exc.events
        print(json.dumps(detail), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
