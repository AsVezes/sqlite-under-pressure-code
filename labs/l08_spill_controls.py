"""L08 adjunct: prove spill and recovery using owned, disposable SQLite files."""
import hashlib
import json
import platform
import selectors
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROWS = 64
SIZE = 4096
WORKER = """
import sqlite3,sys
c=sqlite3.connect(sys.argv[1],isolation_level=None)
c.execute('PRAGMA synchronous=FULL')
c.execute('PRAGMA cache_size=10')
c.execute('PRAGMA cache_spill='+sys.argv[2])
c.execute('BEGIN IMMEDIATE')
for i in range(1,65):
    c.execute('UPDATE payload SET data=? WHERE id=?',(bytes([i+64])*4096,i))
print('READY',flush=True)
if sys.argv[3]=='commit':
    c.execute('COMMIT')
    print('COMMITTED',flush=True)
else:
    sys.stdin.buffer.read(1)
"""

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def ack(child, expected):
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout, selectors.EVENT_READ)
        if not selector.select(timeout=15):
            raise RuntimeError("worker ACK timeout")
        actual = child.stdout.readline().strip()
        if actual != expected:
            raise RuntimeError("expected %s, received %r" % (expected, actual))

def case(root, name, spill, commit):
    folder = root / name
    folder.mkdir()
    db = folder / "fixture.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("PRAGMA journal_mode=DELETE")
        c.execute("PRAGMA synchronous=FULL")
        c.execute("CREATE TABLE payload(id INTEGER PRIMARY KEY,data BLOB NOT NULL)")
        c.executemany("INSERT INTO payload VALUES(?,?)", [(i,b"0"*SIZE) for i in range(1,ROWS+1)])
    baseline = digest(db)
    child = subprocess.Popen(
        [sys.executable,"-c",WORKER,str(db),spill,"commit" if commit else "interrupt"],
        cwd=folder, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    try:
        ack(child,"READY")
        if commit:
            ack(child,"COMMITTED")
            child.communicate(timeout=10)
            if child.returncode != 0:
                raise RuntimeError("worker commit failed")
        else:
            child.kill()  # Only our child, after READY.
            child.communicate(timeout=10)
        journal = folder / "fixture.sqlite3-journal"
        exists = journal.exists()
        size = journal.stat().st_size if exists else 0
        changed = digest(db) != baseline
        # Capture a quiescent pair before SQLite can recover the original.
        copy_dir = folder / "recovery-copy"
        copy_dir.mkdir()
        recovered = copy_dir / db.name
        shutil.copy2(db,recovered)
        if exists:
            shutil.copy2(journal,copy_dir / journal.name)
        with sqlite3.connect(recovered) as c:
            counts = c.execute(
                "SELECT SUM(data=?),SUM(data<>?) FROM payload",
                (b"0"*SIZE,b"0"*SIZE)).fetchone()
            integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
            source_id = c.execute("SELECT sqlite_source_id()").fetchone()[0]
        return dict(scenario=name,spill_setting=spill,committed=commit,
                    baseline_sha256=baseline,main_file_changed_before_recovery=changed,
                    journal_present_before_recovery=exists,journal_bytes=size,
                    recovered_baseline_rows=counts[0],recovered_modified_rows=counts[1],
                    integrity_check=integrity,sqlite_source_id=source_id)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)

def main():
    if len(sys.argv) != 1:
        print("L08 spill controls accept no arguments or external paths",file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="sqlite-l08-spill-") as temp:
        root = Path(temp).resolve()
        (root / ".owned-disposable-l08").write_text("L08 only")
        cases = [case(root,"spill_interrupted","ON",False),
                 case(root,"no_spill_interrupted","OFF",False),
                 case(root,"committed","ON",True)]
    spill, no_spill, committed = cases
    oracles = {
        "spill_changed_main_file": spill["main_file_changed_before_recovery"],
        "spill_journal_preserved": spill["journal_present_before_recovery"] and spill["journal_bytes"] > 0,
        "spill_recovered_baseline": spill["recovered_baseline_rows"] == ROWS and spill["recovered_modified_rows"] == 0,
        "no_spill_main_unchanged": not no_spill["main_file_changed_before_recovery"],
        "no_spill_recovered_baseline": no_spill["recovered_baseline_rows"] == ROWS and no_spill["recovered_modified_rows"] == 0,
        "commit_persisted_changes": committed["recovered_modified_rows"] == ROWS and committed["recovered_baseline_rows"] == 0,
        "all_integrity_checks_ok": all(c["integrity_check"] == "ok" for c in cases),
        "same_effective_source_id": len({c["sqlite_source_id"] for c in cases}) == 1,
    }
    evidence = {
        "lab":"L08","variant":"spill-controls",
        "status":"pass" if all(oracles.values()) else "fail",
        "sqlite_version":sqlite3.sqlite_version,
        "sqlite_source_id":spill["sqlite_source_id"],
        "python":sys.version,"platform":platform.platform(),
        "commands":["python3 labs/l08_spill_controls.py"],
        "inputs":{"rows":ROWS,"bytes_per_row":SIZE,"journal_mode":"DELETE",
                  "synchronous":"FULL","cache_size_pages":10,
                  "cache_spill_variants":["ON","OFF"]},
        "events":["parent committed fixture","worker READY after 64 updates",
                  "parent killed owned interrupted worker or received COMMITTED",
                  "parent copied quiescent database and journal",
                  "parent opened recovery copy"],
        "observed":cases,"oracles":oracles,
        "limitations":["Process interruption, not power failure",
                       "Main-file hash change is an indirect spill indicator, not a VFS xWrite trace",
                       "Journal presence alone does not prove hot-journal state",
                       "Recovery applies to copied quiescent pair on this host only",
                       "Filesystem and sync guarantees not independently verified"],
    }
    print(json.dumps(evidence,indent=2))
    return 0 if all(oracles.values()) else 1

if __name__ == "__main__":
    raise SystemExit(main())
