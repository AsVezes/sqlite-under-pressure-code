#!/usr/bin/env python3
"""Read-only F3 location-code preflight; not a schema migration or O3 acceptance."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys


def canonical(code):
    """Strip ASCII spaces and uppercase ASCII a-z; reject other characters."""
    if not isinstance(code, str):
        return None
    value = code.strip(" ")
    if not value or any(not ("A" <= ch <= "Z" or "a" <= ch <= "z" or "0" <= ch <= "9" or ch == "-") for ch in value):
        return None
    return "".join(chr(ord(ch) - 32) if "a" <= ch <= "z" else ch for ch in value)


def inspect(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            return {"fixture": "F3", "ok": False, "user_version": version,
                    "locations": [], "issues": [{"code": "F3_FUTURE_VERSION"}]}
        rows = con.execute("SELECT id, code FROM location ORDER BY id").fetchall()
        seen = {}
        issues = []
        normalized = []
        for identifier, code in rows:
            value = canonical(code)
            if value is None:
                issues.append({"code": "F3_INVALID_CODE", "location_id": identifier})
            else:
                if value in seen:
                    issues.append({"code": "F3_CODE_COLLISION", "location_id": identifier, "other_id": seen[value], "canonical": value})
                else:
                    seen[value] = identifier
            normalized.append({"location_id": identifier, "canonical": value})
        return {"fixture": "F3", "ok": not issues, "user_version": version,
                "locations": normalized, "issues": issues}
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    try:
        result = inspect(args.database)
    except (OSError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
