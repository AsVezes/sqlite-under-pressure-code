"""CP09: capture and validate an online snapshot before making it selectable."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import monotonic, time_ns
from uuid import uuid4

from tools.e1 import inspect_connection

from .environment import connect
from .ledger import require_ledger
from .operation import execute, parser
from .writer import require_receipt_trigger, watermark


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate(path, *, standalone=False):
    with closing(connect(path, read_only=True)) as db:
        db.execute("BEGIN")
        if standalone and db.execute("PRAGMA journal_mode").fetchone() != ("delete",):
            raise ValueError("bundle database must use DELETE journal mode")
        state = require_ledger(db)
        if state["schema_version"] != 2:
            raise ValueError("backup or restore requires schema v2")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("structural integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("foreign key check failed")
        require_receipt_trigger(db)
        state["watermark"] = watermark(db)
        # A rebuilt table can have valid pages and FKs but lack the original
        # uniqueness constraints. Check the receipt bijection in this snapshot.
        sequences = db.execute("""
            SELECT count(DISTINCT seq), count(CASE WHEN typeof(seq)='integer' THEN 1 END)
            FROM receipt
        """).fetchone()
        if sequences != (state["watermark"], state["watermark"]):
            raise ValueError("backup receipt sequence is not unique or contains noninteger values")
        if db.execute("""
            SELECT 1 FROM transfer AS t
            WHERE NOT EXISTS (SELECT 1 FROM receipt AS r WHERE r.transfer_id=t.id)
            LIMIT 1
        """).fetchone():
            raise ValueError("backup is missing a transfer receipt")
        state["source_id"] = db.execute("SELECT sqlite_source_id()").fetchone()[0]
        state["ledger"] = inspect_connection(db)
    if not state["ledger"]["ok"]:
        raise ValueError("ledger reconciliation failed")
    return state


def capture(path, parent, *, deadline_seconds=10, progress=None):
    parent = parent.resolve(strict=True)
    if not parent.is_dir() or not 0 < deadline_seconds <= 3600:
        raise ValueError("invalid backup directory or deadline")
    until = monotonic() + deadline_seconds
    steps = 0

    def observe(status, remaining, total):
        nonlocal steps
        steps += 1
        if monotonic() >= until:
            raise TimeoutError("backup deadline exceeded")
        if progress:
            progress(status, remaining, total)

    with TemporaryDirectory(dir=parent, prefix=".stockroom-stage-") as temp:
        stage = Path(temp) / "bundle"
        stage.mkdir()
        snapshot = stage / "ledger.db"
        with closing(connect(path, read_only=True, timeout=0)) as src:
            with closing(sqlite3.connect(snapshot, autocommit=True)) as dst:
                src.backup(dst, pages=1, progress=observe, sleep=0.01)
                if dst.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
                    raise ValueError("could not finalize standalone destination")
        state = validate(snapshot)
        manifest = {key: state[key] for key in ("schema_version", "workspace_id", "watermark", "source_id")}
        manifest.update(sha256=digest(snapshot), captured_at_ns=time_ns())
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        published = parent / f"stockroom-backup-{uuid4().hex}"
        # This is publication in a local directory, not an fsync durability protocol.
        stage.rename(published)
    return {"bundle": str(published), "steps": steps, "manifest": manifest}


def verify_bundle(bundle):
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("expected a bundle directory")
    file, metadata = bundle / "ledger.db", bundle / "manifest.json"
    if any(p.is_symlink() or not p.is_file() for p in (file, metadata)):
        raise ValueError("backup files must be regular files")
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = file.with_name(file.name + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise ValueError(f"unexpected SQLite sidecar in bundle: {sidecar.name}")
    manifest = json.loads(metadata.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or type(manifest.get("captured_at_ns")) is not int:
        raise ValueError("invalid manifest")
    if digest(file) != manifest.get("sha256"):
        raise ValueError("backup digest mismatch")
    state = validate(file, standalone=True)
    for key in ("schema_version", "workspace_id", "watermark"):
        if state[key] != manifest.get(key):
            raise ValueError(f"backup metadata mismatch: {key}")
    return state, manifest


def latest(parent, workspace_id):
    candidates = []
    for path in sorted(parent.glob("stockroom-backup-*")):
        try:
            state, manifest = verify_bundle(path)
        except (ValueError, sqlite3.Error, OSError):
            continue
        if state["workspace_id"] == workspace_id:
            candidates.append((state["watermark"], manifest["captured_at_ns"], path))
    return max(candidates)[2] if candidates else None


def main():
    args = parser(__doc__)
    args.add_argument("parent", type=Path, help="Existing directory where the verified bundle will appear")
    options = args.parse_args()
    return execute(lambda: capture(options.database, options.parent))


if __name__ == "__main__":
    raise SystemExit(main())
