#!/usr/bin/env python3
"""Offline replay of CP00..CP11 from a public starter checkout.

The input starter is copied into an isolated temporary Git repository; the
source tree, user databases, and public repository are never modified. This
verifies real git-apply behavior and measured trees, not patch-header claims.

Example, from the public kit root:
    python3 tools/verify_patch_chain.py --starter /path/to/starter --run-tests

No network, GitHub Actions, external Python packages, or credentials required.
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


def run(args, cwd, timeout):
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"timeout after {timeout}s: {args!r}") from exc
    if done.returncode:
        detail = (done.stdout + "\n" + done.stderr)[-3000:]
        raise RuntimeError(f"exit {done.returncode}: {args!r}\n{detail}")
    return done.stdout, done.stderr


def safe_copy_starter(source, target):
    if not source.is_dir():
        raise ValueError("--starter must be an unpacked directory")
    if source.is_symlink():
        raise ValueError("starter must not be a symlink")
    for item in source.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"starter contains a symlink: {item.relative_to(source)}")
    for item in source.iterdir():
        if item.name == ".git":
            continue
        target_item = target / item.name
        if item.is_dir():
            shutil.copytree(item, target_item)
        elif item.is_file():
            shutil.copy2(item, target_item)
        else:
            raise ValueError(f"unsupported starter entry: {item}")


def verify(starter, patches, manifest, run_tests=False, timeout=120, log_dir=None):
    records = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("manifest must be a nonempty list")
    if [r.get("checkpoint") for r in records] != list(range(len(records))):
        raise ValueError("manifest checkpoints are not contiguous from CP00")
    for i, record in enumerate(records):
        if i and records[i-1]["output_tree"] != record["input_tree"]:
            raise ValueError(f"manifest chain broken between CP{i-1:02d} and CP{i:02d}")
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        if any(log_dir.iterdir()):
            raise ValueError("--log-dir must be empty; refusing to overwrite prior evidence")
    with closing(sqlite3.connect(":memory:")) as identity_db:
        source_id = identity_db.execute("SELECT sqlite_source_id()").fetchone()[0]
    result = {"starter": str(starter), "manifest": str(manifest),
              "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
              "sqlite_source_id": source_id,
              "git": None, "tests_requested": run_tests, "checkpoints": [],
              "status": "failed"}
    with tempfile.TemporaryDirectory(prefix="sqlite-cp-replay-") as tmp:
        work = Path(tmp) / "checkout"
        work.mkdir()
        safe_copy_starter(starter, work)
        git = shutil.which("git")
        if not git:
            raise RuntimeError("Git executable not found")
        result["git"] = run([git, "--version"], work, timeout)[0].strip()
        run([git, "init", "-q"], work, timeout)
        run([git, "-c", "core.autocrlf=false", "add", "-A"], work, timeout)
        first = run([git, "write-tree"], work, timeout)[0].strip()
        result["initial_tree"] = first
        if first != records[0]["input_tree"]:
            raise RuntimeError(f"wrong starter: expected {records[0]['input_tree']}, got {first}")
        for record in records:
            i = record["checkpoint"]
            patch = patches / f"cp{i:02d}.patch"
            if not patch.is_file() or patch.is_symlink():
                raise ValueError(f"missing/unsafe patch CP{i:02d}: {patch}")
            before = run([git, "write-tree"], work, timeout)[0].strip()
            if before != record["input_tree"]:
                raise RuntimeError(f"CP{i:02d} input mismatch: {before}")
            run([git, "apply", "--check", str(patch)], work, timeout)
            run([git, "apply", str(patch)], work, timeout)
            run([git, "-c", "core.autocrlf=false", "add", "-A"], work, timeout)
            after = run([git, "write-tree"], work, timeout)[0].strip()
            if after != record["output_tree"]:
                raise RuntimeError(f"CP{i:02d} output mismatch: expected {record['output_tree']}, got {after}")
            entry = {"cp": i, "input_tree": before, "output_tree": after,
                     "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
                     "tests": "not requested"}
            if run_tests:
                stdout, stderr = run([sys.executable, "-m", "unittest", "discover",
                                      "-s", "stockroom", "-t", ".", "-v"], work, timeout)
                entry["tests"] = "passed"
                if log_dir is not None:
                    (log_dir / f"cp{i:02d}.stdout.log").write_text(stdout, encoding="utf-8")
                    (log_dir / f"cp{i:02d}.stderr.log").write_text(stderr, encoding="utf-8")
                entry["test_stdout_tail"] = stdout[-1000:]
                entry["test_stderr_tail"] = stderr[-1000:]
            result["checkpoints"].append(entry)
            if log_dir is not None:
                (log_dir / f"cp{i:02d}.json").write_text(
                    json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result["status"] = "passed"
    return result


def main():
    default = Path(__file__).resolve().parents[1] / "stockroom" / "steps"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--starter", required=True, type=Path,
                        help="unpacked root of the public starter archive, without .git")
    parser.add_argument("--patches", type=Path, default=default)
    parser.add_argument("--manifest", type=Path, default=default / "trees.json")
    parser.add_argument("--run-tests", action="store_true",
                        help="also run Stockroom unittest discovery after each checkpoint")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--log-dir", type=Path, help="empty output directory for evidence logs")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    try:
        answer = verify(args.starter.resolve(), args.patches.resolve(),
                        args.manifest.resolve(), args.run_tests, args.timeout,
                        args.log_dir.resolve() if args.log_dir else None)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2),
              file=sys.stderr)
        return 1
    print(json.dumps(answer, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
