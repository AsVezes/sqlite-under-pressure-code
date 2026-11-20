"""CP00: workspace ownership and separate SQLite runtime identities."""

from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid


DATABASE_NAME = "stockroom ledger.sqlite3"
APPLICATION_ID = 0x534C4544


def connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open an existing database with SQL-controlled transactions."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected an existing, regular database file: {path}")
    mode = "ro" if read_only else "rw"
    uri = path.resolve(strict=True).as_uri() + "?mode=" + mode
    db = sqlite3.connect(uri, uri=True, autocommit=True)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise RuntimeError("SQLite foreign key enforcement is unavailable")
    except BaseException:
        db.close()
        raise
    return db


def identity(db: sqlite3.Connection) -> dict:
    if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ValueError("The database is not a Stockroom Ledger workspace")
    row = db.execute(
        "SELECT identity FROM workspace_identity WHERE slot=1"
    ).fetchone()
    if row is None:
        raise ValueError("The workspace identity is missing")
    return {
        "workspace_id": row[0],
        "database": db.execute("PRAGMA database_list").fetchone()[2],
        "schema_version": db.execute("PRAGMA user_version").fetchone()[0],
    }


def initialize_workspace(parent: Path | None = None) -> dict:
    """Create a new exclusive directory and put one identifiable database in it."""
    directory = Path(tempfile.mkdtemp(prefix="stockroom-", dir=parent)).resolve()
    path = directory / DATABASE_NAME
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with closing(connect(path)) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute(
                "CREATE TABLE workspace_identity("
                "slot INTEGER PRIMARY KEY CHECK(slot=1), identity TEXT NOT NULL)"
            )
            db.execute("INSERT INTO workspace_identity VALUES(1,?)", (str(uuid.uuid4()),))
            db.execute("COMMIT")
            return {"workspace": str(directory), **identity(db)}
    except BaseException:
        # The directory was created exclusively by this invocation.
        shutil.rmtree(directory)
        raise


def inspect_workspace(path: Path) -> dict:
    with closing(connect(path, read_only=True)) as db:
        return identity(db)


def runtime_profile() -> dict:
    with closing(sqlite3.connect(":memory:", autocommit=True)) as db:
        lib = {
            "version": db.execute("SELECT sqlite_version()").fetchone()[0],
            "source_id": db.execute("SELECT sqlite_source_id()").fetchone()[0],
            "compile_options": [row[0] for row in db.execute("PRAGMA compile_options")],
        }
    cli_path = shutil.which("sqlite3")
    cli = {"available": False}
    if cli_path:
        executable = str(Path(cli_path).resolve())
        argv = [
            executable, "-batch", "-bail", "-noheader", "-init", os.devnull,
            ":memory:", "SELECT sqlite_version(); SELECT sqlite_source_id(); PRAGMA compile_options;",
        ]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            lines = result.stdout.splitlines()
            if result.returncode == 0 and len(lines) >= 2:
                cli = {"available": True, "executable": executable, "version": lines[0],
                       "source_id": lines[1], "compile_options": lines[2:]}
            else:
                cli.update(executable=executable, exit_code=result.returncode, error=result.stderr)
        except (OSError, subprocess.TimeoutExpired) as error:
            cli.update(executable=executable, error=str(error))
    return {"python": sys.version, "python_executable": sys.executable,
            "sqlite_library": lib, "sqlite_cli": cli}
