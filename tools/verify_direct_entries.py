#!/usr/bin/env python3
"""Offline check of historical CP08–CP11 snapshots after direct-entry repairs.

Supply an unpacked *historical* snapshot for the target CP, not the current
main checkout. The script never edits the input or any existing database.

Examples:
    python3 tools/verify_direct_entries.py --snapshot /tmp/cp10-archive --checkpoint 10
    python3 tools/verify_direct_entries.py --snapshot /tmp/cp11-archive --checkpoint 11 --run-tests
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile

if __package__:
    from .verify_patch_chain import run, safe_copy_starter
else:
    from verify_patch_chain import run, safe_copy_starter


SNAPSHOT_TREES = {
    8: "66a13661f1b55a9deb81f4e57fba58e19dd075a4",
    9: "bdcff530e365b2f31e35111f247a627e9f2b24a5",
    10: "833fa458917c91ca61312a4d0dcfc44384c0d7af",
    11: "a5e9cbc3d10b3df0f6d246fca8034ec2e5b7fa62",
}
EXPECTED_BLOBS = {
    "stockroom/ledger.py": "f14a100439c49e44e3ad50c18f351b19c8ee1544",
    "stockroom/writer.py": "735be4d1f011d37c6dcbe7ef2e112b0bccfbb54d",
    "stockroom/test_writer.py": "2719d98e87892b52c9491052266c842ac1d8545c",
    "stockroom/restore.py": "191e8a84e545d0f11265bef6ec55a052b609d091",
    "stockroom/test_restore_pointer_atomicity.py": "b81f3fe77519ec748b039ec4685ecceec3d15b06",
}
EARLY_WRITER = "670314106d80d102fee6f46578f590b601bfeb8d"


def verify(snapshot, checkpoint, patches, run_tests=False, timeout=120, log_dir=None):
    if checkpoint not in SNAPSHOT_TREES:
        raise ValueError("checkpoint must be one of CP08, CP09, CP10 or CP11")
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        if any(log_dir.iterdir()):
            raise ValueError("evidence directory must be empty")
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git executable not found")
    with closing(sqlite3.connect(":memory:")) as db:
        source_id = db.execute("SELECT sqlite_source_id()").fetchone()[0]
    evidence = {
        "checkpoint": checkpoint,
        "archive_tree_expected": SNAPSHOT_TREES[checkpoint],
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "source_id": source_id,
        "status": "failed",
        "repairs": [],
        "tests_requested": run_tests,
    }
    with tempfile.TemporaryDirectory(prefix="sqlite-direct-entry-") as tmp:
        work = Path(tmp) / "checkout"
        work.mkdir()
        safe_copy_starter(snapshot, work)
        evidence["git_version"] = run([git, "--version"], work, timeout)[0].strip()
        run([git, "init", "-q"], work, timeout)
        run([git, "-c", "core.autocrlf=false", "add", "-A"], work, timeout)
        actual_tree = run([git, "write-tree"], work, timeout)[0].strip()
        evidence["archive_tree_observed"] = actual_tree
        if actual_tree != SNAPSHOT_TREES[checkpoint]:
            raise RuntimeError("wrong historical source snapshot; tree mismatch")
        for repair in range(8, min(checkpoint, 10) + 1):
            patch = patches / f"cp{repair:02d}-repair.patch"
            if not patch.is_file() or patch.is_symlink():
                raise ValueError(f"missing/unsafe repair patch: {patch}")
            run([git, "apply", "--check", str(patch)], work, timeout)
            run([git, "apply", str(patch)], work, timeout)
            run([git, "-c", "core.autocrlf=false", "add", "-A"], work, timeout)
            step = {"repair": repair, "tree": run([git, "write-tree"], work, timeout)[0].strip(),
                    "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest()}
            evidence["repairs"].append(step)
        expected = {"stockroom/ledger.py": EXPECTED_BLOBS["stockroom/ledger.py"]}
        if checkpoint == 8:
            expected["stockroom/writer.py"] = EARLY_WRITER
        else:
            expected["stockroom/writer.py"] = EXPECTED_BLOBS["stockroom/writer.py"]
            expected["stockroom/test_writer.py"] = EXPECTED_BLOBS["stockroom/test_writer.py"]
        if checkpoint >= 10:
            for key in ("stockroom/restore.py", "stockroom/test_restore_pointer_atomicity.py"):
                expected[key] = EXPECTED_BLOBS[key]
        observed = {}
        for relpath, sha in expected.items():
            actual = run([git, "hash-object", relpath], work, timeout)[0].strip()
            observed[relpath] = actual
            if actual != sha:
                raise RuntimeError(f"repair mismatch {relpath}: expected {sha}, got {actual}")
        evidence["critical_file_blobs"] = observed
        if run_tests:
            stdout, stderr = run([sys.executable, "-m", "unittest", "discover",
                                  "-s", "stockroom", "-t", ".", "-v"], work, timeout)
            evidence["tests"] = "passed"
            evidence["test_stdout_tail"] = stdout[-1500:]
            evidence["test_stderr_tail"] = stderr[-1500:]
            if log_dir is not None:
                (log_dir / "test.stdout.log").write_text(stdout, encoding="utf-8")
                (log_dir / "test.stderr.log").write_text(stderr, encoding="utf-8")
        evidence["status"] = "passed"
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--checkpoint", type=int, required=True, choices=sorted(SNAPSHOT_TREES))
    parser.add_argument("--patches", type=Path,
                        default=Path(__file__).resolve().parents[1] / "stockroom" / "steps")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    try:
        result = verify(args.snapshot.resolve(), args.checkpoint,
                        args.patches.resolve(), args.run_tests, args.timeout,
                        args.log_dir.resolve() if args.log_dir else None)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2),
              file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
