# Stockroom Ledger

The cumulative teaching project uses Python 3.12 or later and its standard-library SQLite binding. Run the commands from the repository root. Use the standalone SQLite CLI for the book's shell exercises.

## CP00 · Identify the runtime and open the same workspace twice

```sh
python3 -m stockroom doctor
python3 -m stockroom workspace
python3 -m stockroom identity "/absolute/path/to/stockroom ledger.sqlite3"
python3 -m unittest discover -s stockroom -t . -v
```

Use the exact database path returned by `workspace`. It creates a new directory each time. The second connection reports the same workspace ID, database path and schema version 0. Try a path in a different directory to see the refusal without creating a second database. The `doctor` output identifies the shell and Python's embedded SQLite separately.

## CP01 · Install schema v1 in the CP00 database

```sh
python3 -m stockroom init "/absolute/path/to/stockroom ledger.sqlite3"
python3 -m stockroom check "/absolute/path/to/stockroom ledger.sqlite3"
python3 -m unittest discover -s stockroom -t . -v
```

Pass the same workspace path from CP00. One transaction creates schema v1 and populates F1 with quantities 10/2 for bolts and 4/8 for nuts. The O1 check opens the database read-only and reconciles every position, movement and journal entry. It exits 1 if balances do not reconcile and 2 if the database or invocation is invalid.

Quantity columns use `ANY` in STRICT tables, with explicit integer and bounds checks. This preserves the bound SQLite value's type so a REAL value or numeric text cannot pass as an integer. F1 retains historical location codes for the later migration exercise.

## CP02 · Transfer stock and reconcile the journal

In the same disposable CP01 workspace, run:

```sh
python3 -m stockroom transfer "/absolute/path/to/stockroom ledger.sqlite3" tx-001 item-bolt loc-north loc-south 3
python3 -m stockroom check "/absolute/path/to/stockroom ledger.sqlite3"
python3 -m unittest discover -s stockroom -t . -v
```

The expected bolt balances are 7 and 5. Nuts stay at 4 and 8. O1 expects one transfer and two journal entries. A duplicate ID is an error at this stage.

Try a different ID with `--fail-after-debit` in the disposable workspace. The command should exit nonzero. Run `check` again and compare the balances and journal counts with the previous check. An excessive quantity, unknown position or identical source and destination also fails without moving stock. The savepoint regression verifies that the caller can keep earlier work in the same transaction after a single failed move. Closing or rolling back the outer transaction still controls durability.

These development checkpoints require execution and independent review before acceptance.
