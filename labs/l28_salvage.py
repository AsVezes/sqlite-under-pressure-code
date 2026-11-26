#!/usr/bin/env python3
"""L28/C25: compare verified restore with quarantined .recover output.

Requires a SQLite CLI supporting .recover. All paths are disposable.
"""
from contextlib import closing
import hashlib
import json
import platform
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cli(args, input_text=None):
    return subprocess.run(args, input=input_text, text=True, capture_output=True, check=False)


def inspect(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        fk = db.execute("PRAGMA foreign_key_check").fetchall()
        rows = db.execute("SELECT id, value FROM records ORDER BY id").fetchall()
        return {"integrity": integrity, "fk": fk, "rows": rows}


def main():
    executable = shutil.which("sqlite3")
    require(executable is not None, "SQLite CLI required: sqlite3 not found")
    version_cli = cli([executable, "-version"])
    require(version_cli.returncode == 0, "sqlite3 -version failed")
    help_recover = cli([executable, ":memory:", ".help recover"])
    require(help_recover.returncode == 0 and ".recover" in help_recover.stdout,
            "SQLite CLI lacks .recover; do not substitute .dump")
    with tempfile.TemporaryDirectory(prefix="sqlite-l28-") as temp:
        root = Path(temp)
        source, backup, damaged, restored, quarantine = (
            root / name for name in ("source.db", "backup.db", "damaged.db", "restored.db", "quarantine.db")
        )
        with closing(sqlite3.connect(source)) as db:
            version, source_id = db.execute("SELECT sqlite_version(), sqlite_source_id()").fetchone()
            db.execute("PRAGMA page_size=1024")
            db.execute("VACUUM")
            db.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            db.executemany("INSERT INTO records VALUES(?,?)",
                           [(i, "known-%04d-" % i + "x" * 800) for i in range(1, 21)])
            db.commit()
            with closing(sqlite3.connect(backup)) as dest:
                db.backup(dest)
        source_sha = sha(source)
        truth = inspect(backup)
        require(inspect(source) == truth, "backup does not match source records")
        require(truth["integrity"] == "ok" and not truth["fk"] and len(truth["rows"]) == 20,
                "verified backup prerequisite failed")
        expected = sha(backup)
        restored.write_bytes(backup.read_bytes())
        require(sha(restored) == expected and inspect(restored) == truth,
                "verified restore mismatch")
        # Synthetic, deliberate damage to a disposable clone only.
        damaged.write_bytes(source.read_bytes())
        with damaged.open("r+b") as handle:
            handle.seek(1024)  # B-tree page after page 1, not the database header
            handle.write(bytes(1024))
        require(sha(source) == source_sha, "source changed during damage injection")
        require(sha(backup) == expected, "backup changed during damage injection")
        damaged_state = None
        try:
            damaged_state = inspect(damaged)
        except sqlite3.DatabaseError as exc:
            damaged_state = {"read_error": type(exc).__name__, "code": getattr(exc, "sqlite_errorcode", None)}
        require(damaged_state != truth, "synthetic damage did not change fixture observations")
        recovered = cli([executable, "-batch", "-bail", "-readonly", str(damaged), ".recover --ignore-freelist"])
        require(recovered.returncode == 0 and "CREATE TABLE" in recovered.stdout,
                "recover failed; preserve output and do not promote candidate")
        # The generated SQL is untrusted. Import only into a disposable quarantine.
        imported = cli([executable, "-batch", "-bail", str(quarantine)], recovered.stdout)
        require(imported.returncode == 0, "quarantine import failed: " + imported.stderr[:300])
        with closing(sqlite3.connect(quarantine.as_uri() + "?mode=ro", uri=True)) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            require("records" in tables, "recovery candidate lacks records table")
            candidates = db.execute("SELECT id,value FROM records ORDER BY id").fetchall()
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            fk = db.execute("PRAGMA foreign_key_check").fetchall()
        truth_by_id = dict(truth["rows"])
        matched = [id for id, value in candidates if truth_by_id.get(id) == value]
        altered = [id for id, value in candidates if id in truth_by_id and truth_by_id[id] != value]
        unknown = [id for id, _ in candidates if id not in truth_by_id]
        missing = sorted(set(truth_by_id) - set(matched))
        require(sha(source) == source_sha and sha(backup) == expected
                and sha(restored) == expected and inspect(restored) == truth,
                "backup/restore mutated by salvage")
        require(integrity == "ok" and not fk, "quarantine failed structural/FK checks")
        # This lab performs no promotion, even if the quarantine passes structural checks.
        print(json.dumps({
            "lab": "L28", "python": platform.python_version(),
            "platform": platform.platform(), "sqlite_version": version,
            "sqlite_source_id": source_id, "sqlite_cli_version": version_cli.stdout.strip(),
            "source_sha256": source_sha, "backup_sha256": expected, "verified_restore_count": len(truth["rows"]),
            "damaged_read": damaged_state if isinstance(damaged_state, dict) else
                {"readable_rows": len(damaged_state["rows"]), "integrity": damaged_state["integrity"]},
            "recovery_exit": recovered.returncode, "import_exit": imported.returncode,
            "matched_ids": matched, "altered_ids": altered, "unknown_ids": unknown,
            "missing_or_unverified_ids": missing, "quarantine_integrity": integrity,
            "quarantine_fk": fk, "promoted": False,
            "limitations": "Synthetic page overwrite; .recover is best-effort, not provenance proof. No physical failure, no production promotion."
        }, sort_keys=True))


if __name__ == "__main__":
    main()
