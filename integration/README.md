# E1 integration probes

Run from the repository root on Linux with Python 3.11+ and its standard-library SQLite binding.

~~~sh
python3 -m integration.e1_faults
python3 -m integration.e1_backup
python3 -m integration.e1_restore_drill
~~~

These commands create isolated disposable databases, accept no database paths, print JSON evidence and return nonzero if a required check fails. Record the commit, Python and SQLite identities, stdout, stderr and exit status. Repeat execution from a fresh tree for comparison.

| Experiment | Evidence and control |
| --- | --- |
| L22 process interruption | Spawned writer acknowledges statements and a returned SQL commit. Compare termination at the two boundaries with normal exit in DELETE and WAL using FULL. Reopen and reconcile F1/O1 and transfer/journal counts. |
| L23 portable subset | Set a logical page cap, induce SQLITE_FULL with a bounded payload, check persisted rows after reopen and reject a write through a read-only URI. Repeat with a larger cap where the same payload commits. |
| L25 backup | A WAL writer commits in a separate process after the first successful backup step. Observe the watermark, compare a no-writer control and abort a separate attempt before completion. |
| L27 restore validation | Restore to a fresh path, verify digest, version, integrity, foreign keys and F1/O1, and perform a reversible write. Reject a wrong digest, future version and valid-digest artifact with an inconsistent ledger. |
| L27 cutover and return | Reject a bad digest before switching. Select the verified restore, measure the gap between commit acknowledgments and time to smoke completion, then return to the original state before allowing committed writes. |

The backup and restore experiments use an enlarged F1 fixture. The cutover drill switches a local selection file in one process and measures that rehearsal. The complete F4/F5 run and F6/VFS error-injection cases need separate evidence. Process termination tests observe the running operating system and filesystem.
