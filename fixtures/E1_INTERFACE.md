# E1/F1 — shared fixture and O1 oracle

These are **pilot-only** assets for the book's E1 mechanism experiments. They are not a finished CP00/CP01 or a complete implementation of Stockroom Ledger.

## Interface for laboratory authors

- `fixtures/e1_f1.sql`: deterministic disposable F1 fixture. Two locations (`loc-north`, `loc-south`), two items (`item-bolt`, `item-nut`), four positions, no transfers. Run it **only against a fresh empty database**. `location.code` intentionally has historical mixed formatting.
- `python3 tools/e1.py create`: creates a uniquely named temporary directory and a database named `f1 stockroom.sqlite`; prints their **absolute** paths, engine version and SOURCE_ID. It does not delete or overwrite existing data.
- `python3 tools/e1.py check "<path-to-database>"`: opens an existing file read-only, prints canonical JSON and exits 0 for O1 pass, 1 for O1 violation, or 2 for input/SQLite error.
- `python3 -m unittest discover -s tests -v`: test suite, including intended O1 failures.

Expected baseline in order `(item_id, location_id, quantity)`:

| Item | Location | Units |
| --- | --- | ---: |
| item-bolt | loc-north | 10 |
| item-bolt | loc-south | 2 |
| item-nut | loc-north | 4 |
| item-nut | loc-south | 8 |

## Transfer example for pilots

Transfer `tx-001`: move 3 units of `item-bolt` from `loc-north` to `loc-south`. The committed result must be (7, 5) for that item's two positions, unchanged (4, 8) for the other item, one `transfer` row and **two** `journal_entry` rows with signed deltas -3 and +3. The per-item total stays 12.

O1 checks:

1. `PRAGMA quick_check` and `PRAGMA foreign_key_check` (additional structural and referential signals).
2. The set of positions and the quantity at **every** position against opening quantity plus signed journal deltas.
3. Exactly the expected two journal entries for every transfer, matching its item, origin, destination and quantity.
4. Conservation of total units **per item** across locations.

For a negative control, update one nonnegative stock balance without updating the journal. SQLite may accept the update, but O1 must fail. Also test an incomplete debit, even when the database itself still opens. The oracle is **not** the transfer implementation and cannot enforce all invariants at write time; it is an independent postcondition checker.

R1 can create independent copies, use separate connections and coordinate barriers/ACKs without modifying this fixture or inventing a passing result. Record actual Python/SQLite runtime identity; do not extrapolate this pilot to power-loss guarantees, WAL/rollback behavior, or an approved baseline. The full E1 laboratory acceptance requires R1/R4 independent evidence.

The prospective application schema, receipt contract, migrations and checkpoint tags are **not frozen by this pilot**. Do not import editorial records into the public kit. License selection remains with the author.
