# F3 — Historical location-code preflight (pilot, not O3)

This isolated preflight reads the historical `location(id, code)` table from an
existing disposable F1 database. It does **not** migrate schema, change
`user_version`, merge locations, or establish a completed checkpoint.

Create a fresh disposable F1 using `python3 tools/e1.py create`, then run:

```sh
python3 fixtures/f3_preflight.py "/absolute/path/to/f1 stockroom.sqlite"
python3 -m unittest discover -s tests -p 'test_f3_preflight.py' -v
```

The preflight opens an existing file with SQLite URI `mode=ro`, sets
`query_only`, starts one read transaction, and returns JSON with the current
`user_version`, each stable location ID and proposed canonical code.
Exit 0 means the *location-code preflight only* passed; exit 1 means invalid
or colliding codes; exit 2 means the file could not be read or queried.

**Candidate normalization for F3:** trim ASCII space (U+0020) at both ends,
uppercase ASCII a–z, then permit only ASCII letters, digits and hyphen.
No Unicode case folding or locale-dependent rules. Empty, unsupported and
non-text values are invalid. Detect collisions across distinct IDs after
normalization, report both IDs, and refuse automatic merging. The F1
baseline maps `' North '` to `NORTH` and `'south'` to `SOUTH`.

The tests inject a collision and malformed codes into independent temporary
F1 databases, assert diagnostic categories and ensure a missing file is
never created. This is a **pre-migration gate**, not a full F3 fixture
matrix: dependent view, trigger, index, FK, historical projection, future
schema version, interrupted migration, and the full O3 oracle remain to be
built and independently verified before E1/E2 acceptance. The full
application schema and migration procedure are not frozen by this pilot.
