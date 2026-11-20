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

**Status:** L01 and F1/O1 pilot support code are present. L05/L08/L10–L12/L20/L22–L23/L25/L27 remain planned E1 pilots, not yet executed or claimed complete. There is no release tag or approved distribution license for an edition at this stage.
