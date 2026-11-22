# Stockroom Ledger checkpoint snapshots

These immutable commits record the original CP00–CP02 source snapshots. The SQLite source, CLI profile and full replay are recorded separately during validation.

| Step | Entrance | Output commit | Chapter | Observable state |
| --- | --- | --- | --- | --- |
| CP00 | [Kit before the project](https://github.com/AsVezes/sqlite-under-pressure-code/commit/26b6888f3ab74fb47248dfde7a113b2afd78b46d) | [34a0abc](https://github.com/AsVezes/sqlite-under-pressure-code/commit/34a0abc192df4e45bae08343f3cd49debe7de4ac) | C01 | Two processes identify the same exclusive workspace and its schema version 0. |
| CP01 | CP00 database | [8c468f6](https://github.com/AsVezes/sqlite-under-pressure-code/commit/8c468f602177de7fdaf3061141404019136ee50a) | C03 | Schema v1 in the same file, opening quantities 10/2 and 4/8, no movements, O1 passes. |
| CP02 | CP01 database | [5292d39](https://github.com/AsVezes/sqlite-under-pressure-code/commit/5292d3944ed2ece7f93327fa93496acfe949f748) | C05 | Moving three bolts leaves 7/5, one transfer and two journal legs. Negative controls preserve the prior state. |

For direct entry, download the relevant output commit and follow its [command guide](README.md) from the repository root. Keep the database in a separate disposable directory and carry the same absolute path across all three states. At each stage run `python3 -m unittest discover -s stockroom -t . -v`. CP02 also provides the entry points needed to build all three states directly from a fresh workspace.

These development snapshots require execution and independent review.

## CP03 patch: historical integration versus the chapter exercise

The CP03 build-along patch is an **exact integration delta**, not a list of
seventeen new concepts to learn in C08. It includes work that landed in the
public kit between the CP02 and CP03 source snapshots. Preserve those files
when applying the patch: deleting them or applying only the three Ledger
modules would produce a different tree from the published checkpoint and
invalidate the later patch chain.

For the **C08/CP03 exercise**, focus on `stockroom/storage.py`,
`stockroom/environment.py`, `stockroom/operation.py` and
`stockroom/test_storage.py`: choose the journal mode, observe the resulting
mode, and verify that the existing Ledger still passes its checks. The patch
also updates this checkpoint guide.

The remaining files are **integration prerequisites, not CP03 learning
objectives**:

- `labs/l08_rollback_recovery.py`, `labs/l08_spill_controls.py`, their
  tests and `labs/run_e1.py`/`labs/test_run_e1.py` support the separate
  L08 pilot and its runner. They are not extra CP03 implementation steps.
- `labs/l12_busy_locked.py` and `labs/test_l12_busy_locked.py` support
  L12, taught with contention/retry later in the course (C11/CP04).
- `fixtures/F3_INTERFACE.md`, `fixtures/f3_preflight.py`,
  `tests/test_f3_nontext.py` and `tests/test_f3_preflight.py` are
  historical-code migration **preflight** materials. They are not a
  completed migration, O3 acceptance, or a requirement to teach migration
  in C08. Migration belongs to C19/CP08.

The build-along rule is therefore: **apply the complete CP03 patch exactly
once, run the available checks, but explain and exercise only the C08
journal-profile changes here**. Do not silently remove the incidental files
or relabel their exercises as CP03. They remain in the tree for later use.
The recorded patch/tree chain has not been rewritten by this clarification.
Passing the tests in one environment is not independent acceptance of CP03.

## CP03–CP11 · Continue with the same database

Start from the CP02 database and keep its absolute path. Use the build-along below, or use an output snapshot for direct entry. Run the command from that snapshot's repository root.

| Step | Output snapshot | Chapter | Observable task |
| --- | --- | --- | --- |
| CP03 | [`124e8d0`](https://github.com/AsVezes/sqlite-under-pressure-code/tree/124e8d093b8c5d393a565c1422de42aae07c7949) | C08 | Set WAL or rollback journal |
| CP04 | [`73c704f`](https://github.com/AsVezes/sqlite-under-pressure-code/tree/73c704f740739f845537b2959a7aa2c567f50122) | C11 | Observe passive checkpoint and failure phases |
| CP05 | [`efdf110`](https://github.com/AsVezes/sqlite-under-pressure-code/tree/efdf110c61ad6f8485a5006590402e855089ca1c) | C13 | Install receipts and retry by the exact operation ID |
| CP06 | [`f00d0c6`](https://github.com/AsVezes/sqlite-under-pressure-code/tree/f00d0c655abe9f10c3b6242332b68cab28797c9e) | C14 | Record deterministic report rows and raw timing samples |
| CP07 | [`2a18aa9`](https://github.com/AsVezes/sqlite-under-pressure-code/tree/2a18aa9ed543cac9033b2f900e2f445a1027ce7a) | C17 | Compare indexing on paired copies, then install the teaching index |
| CP08 | [`a7274aa`](https://github.com/AsVezes/sqlite-under-pressure-code/tree/a7274aaaa885258fd9dcdd2b05227414de9219b9) | C19 | Stage, resume, and atomically rebuild schema v2 |
| CP09 | [`2957869`](https://github.com/AsVezes/sqlite-under-pressure-code/tree/295786957a72d2124384ccb46b1e423d4b7a5c55) | C23 | Publish a validated online backup |
| CP10 | [`ee54941`](https://github.com/AsVezes/sqlite-under-pressure-code/tree/ee54941da1c9cc61a43e2b1b7a1fb6325713e280) | C24 | Verify restore and rehearse cutover and return |
| CP11 | [`0645ed3`](https://github.com/AsVezes/sqlite-under-pressure-code/tree/0645ed34e32cc8e40d3b40e2998cbe0e5c77dc7d) | C28 | Replay and reconcile a combined incident |

`DB` is the absolute database filename in a disposable Stockroom workspace. This route is intended for a POSIX shell with Python 3.12 or newer. Copy the existing database path before changing directories. Each snapshot can run `python3 -m unittest discover -s stockroom -t . -v`.

~~~sh
# CP03
python3 -m stockroom.storage "$DB" --journal wal
# CP04
python3 -m stockroom.observe "$DB"
# CP05
python3 -m stockroom.writer "$DB" install
python3 -m stockroom.writer "$DB" submit tx-001 item-bolt loc-north loc-south 3
# CP06
python3 -m stockroom.report "$DB" item-bolt --repeats 5
# CP07
python3 -m stockroom.tune "$DB" compare
python3 -m stockroom.tune "$DB" install
# CP08 (two existing locations in F1)
python3 -m stockroom.migrate "$DB" --batch-size 1
python3 -m stockroom.migrate "$DB" --batch-size 1
python3 -m stockroom.migrate "$DB" --batch-size 1
# CP09
BACKUPS="${DB%/*}/backups"
mkdir -p "$BACKUPS"
BACKUP_JSON=$(python3 -m stockroom.backup "$DB" "$BACKUPS")
printf '%s\n' "$BACKUP_JSON"
BUNDLE=$(printf '%s\n' "$BACKUP_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["bundle"])')
# CP10 (BUNDLE is the verified bundle path returned by CP09)
python3 -m stockroom.writer "$DB" submit tx-after-cut item-bolt loc-north loc-south 1
python3 -m stockroom.restore "$DB" "$BUNDLE" "$BACKUPS"
# CP11
python3 -m stockroom.drill "$DB"
python3 -m stockroom check "$DB"
~~~

Use the CP03 WAL profile when timing the regular writer. CP05 retries contention within a wait budget, and replay of the same ID checks the full payload. The migration preserves the original location labels and requires the input rows to stay unchanged between staging calls. The recovery drill creates an exclusive temporary copy of the project ledger, and its selection file belongs to the rehearsal. Run it with other writers paused if comparing a known receipt boundary.

The commands and tests have been exercised on Linux with Python 3.12.3 and SQLite 3.45.1 from the Python standard library. Platform variants, the official standalone shell, and independent acceptance have their own checks.


## Build the project in one directory

The original snapshots document how the project evolved. For the build-along,
download commit [26b6888](https://github.com/AsVezes/sqlite-under-pressure-code/tree/26b6888f3ab74fb47248dfde7a113b2afd78b46d)
as a ZIP and extract it once. Keep the database and downloaded patches outside
that source directory. The [steps directory](steps/) contains the exact deltas
from each input to the next checkpoint, including the corrected CP08–CP10 gates.

From the source root, apply each chapter's numbered patch and run that chapter's
checks before advancing. For example, at CP00:

```sh
git apply --check "/absolute/path/to/cp00.patch"
git apply "/absolute/path/to/cp00.patch"
python3 -m unittest discover -s stockroom -t . -v
```

A ZIP checkout does not require `git init`. Inspect the `diff --git` headers and
the added and removed lines before applying each patch. You can implement the
listed changes in an editor and use the patch as the exact reference for any
supporting code. Apply a step once. Follow the chapter's own database commands
and keep its exit state before moving on. The [tree manifest](steps/trees.json)
gives the expected source tree after every step. Its `archive_commit` values
identify historical direct-entry snapshots; its `input_tree` and `output_tree`
identify the **numbered-patch build-along** source states. In particular,
CP08–CP11 include repairs folded into the numbered patches, whereas their
historical snapshot commits predate those repairs. Do not equate the manifest's
`output_tree` with the Git root tree of an `archive_commit`, or treat a missing
GitHub tree-object URL as proof that the patch cannot be applied. To validate
an `output_tree`, apply the patches cumulatively to the stated entrance in a
disposable source copy, initialize Git if starting from a ZIP, and stage the
complete source state with `git add -A` before running `git write-tree`.
`git apply` without `--index` changes the worktree but does **not** stage those
changes: running `git write-tree` immediately afterward hashes the old index,
not the reconstructed checkpoint. Compare the resulting tree ID with the
manifest's `output_tree` at each step. Keep the database and downloaded patch
files outside the source tree so they cannot contaminate the staged tree.
This comparison has not been independently replayed here.

For direct entry into the historical CP08 snapshot, apply
[`cp08-repair.patch`](steps/cp08-repair.patch) before running the chapter.
For CP09, also apply [`cp09-repair.patch`](steps/cp09-repair.patch).
For CP10 or CP11, apply all three repair patches, ending with
[`cp10-repair.patch`](steps/cp10-repair.patch). These repair files are for
direct entry only. The numbered build-along patches already include the
corresponding repairs.
