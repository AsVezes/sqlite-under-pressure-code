# SQLite Under Pressure — Companion Code (Work in Progress)

Public companion code for the planned *SQLite Under Pressure: Transactions, Concurrency, Performance, and Failure Recovery* book. This repository is in **technical prototyping**, not a validated release or a finished reader checkpoint. The manuscript and internal editorial records are not published here.

## L01 — Two Sessions, Two Paths

The independent L01 probe has no third-party dependencies, needs only Python 3.9+ with its standard-library SQLite binding, and **never accepts the path to an existing database**. It creates and deletes its own exclusive disposable workspace with spaces in path components.

From the repository root:

~~~sh
python3 labs/l01_identity.py
python3 -m unittest discover -s tests -v
~~~

The probe emits JSON containing:

- the **actual** Python executable, SQLite version, source ID from sqlite_source_id() and PRAGMA compile_options;
- the CLI identity **separately**, if sqlite3 is found on PATH (otherwise explicit unavailable, never guessed);
- database paths reported by PRAGMA database_list, a row read by two connections, a child process resolving a relative filename from another working directory, and two isolated in-memory handles;
- a read-only open failure against a nonexistent disposable path, with runtime error code/name;
- five named Boolean oracles and known limits.

Exit code **0** means all five L01 oracles passed in that environment; any failed oracle returns **1**. This is a functional smoke test, not proof of WAL, transactional durability, concurrency ordering, or power-loss guarantees.

Use only the disposable fixtures created by the probe. Do not adapt fault-oriented exercises to live databases.

## Shared E1/F1 fixture and O1 oracle

R2's independent `fixtures/e1_f1.sql` and `tools/e1.py` provide a disposable two-item/two-location stockroom fixture and a read-only postcondition checker. See [the F1/O1 interface](fixtures/E1_INTERFACE.md). To create a fresh database, run `python3 tools/e1.py create`; copy the JSON `database` path into `python3 tools/e1.py check "<absolute-database-path>"`. Tests for both the correct transfer and intentionally inconsistent states are in `tests/test_e1_oracle.py`. **These are pilot assets, not checkpoints or laboratory acceptance evidence.**

## Additional E1 laboratory pilots and tests

The runner covers **L05 atomicity, L09 WAL visibility, L10 WAL checkpoint progress, and L11 stale snapshots**, plus a separate writer-contention probe with the legacy filename `l10_writer_busy.py`. [Additional E1 integration probes](integration/README.md) cover process interruption, logical capacity, and selected backup/restore cases. The full E1 gate and cumulative checkpoints require further evidence.

From the repository root, in a local environment suitable for the experiments:

~~~sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s labs -p 'test_*.py' -v
python3 labs/run_e1.py
~~~

The runner emits JSON with per-pilot evidence and exit status. Preserve raw output, stderr, return codes, OS/filesystem, Python and SQLite identities, and the source revision for review. Its supervisor tests include mocks and **do not** by themselves prove SQLite concurrency behavior. The standalone probes use disposable workspaces; do not point fault experiments at personal or production databases. CLI and Python SQLite engines must be identified independently. Run and review the missing E1 pilots and the complete acceptance matrix before promoting any checkpoint.

**Status:** implementation/prototyping only; no E1 laboratory, checkpoint, platform matrix, release tag, or edition license is approved merely because these files exist.
