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

This development checkpoint requires execution and independent review before acceptance.
