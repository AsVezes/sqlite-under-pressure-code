"""L24/C22: distinguish file-format, foreign-key and business-rule failures.

Only TemporaryDirectory fixtures are modified; no real damaged file or power-loss simulation.
"""
import hashlib
import json
import platform
import shutil
import sqlite3
import tempfile
from pathlib import Path


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe(path):
    with sqlite3.connect(path) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        quick = db.execute("PRAGMA quick_check").fetchone()[0]
        fk = db.execute("PRAGMA foreign_key_check").fetchall()
        balance = db.execute("SELECT balance FROM account WHERE id=1").fetchone()[0]
        total = db.execute("SELECT COALESCE(SUM(delta),0) FROM ledger WHERE account_id=1").fetchone()[0]
    return {"integrity": integrity, "quick": quick, "foreign_keys": fk,
            "balance": balance, "ledger_sum": total, "business_ok": balance == total}


def main():
    with tempfile.TemporaryDirectory(prefix="sqlite-l24-") as tmp:
        root = Path(tmp)
        original = root / "original.db"
        with sqlite3.connect(original) as db:
            db.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE account(id INTEGER PRIMARY KEY, balance INTEGER NOT NULL);
                CREATE TABLE ledger(id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL
                    REFERENCES account(id), delta INTEGER NOT NULL);
                INSERT INTO account VALUES(1,10);
                INSERT INTO ledger VALUES(1,1,10);
            """)
        original_sha = sha(original)
        baseline = probe(original)
        require(baseline["integrity"] == baseline["quick"] == "ok"
                and not baseline["foreign_keys"] and baseline["business_ok"], "baseline invalid")

        orphan = root / "orphan.db"
        shutil.copyfile(original, orphan)
        with sqlite3.connect(orphan) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("INSERT INTO ledger VALUES(2,999,0)")
            db.commit()
        fk = probe(orphan)
        require(fk["integrity"] == fk["quick"] == "ok", "FK case structural check")
        require(len(fk["foreign_keys"]) == 1
                and fk["foreign_keys"][0][:2] == ("ledger", 2), "expected FK orphan")

        semantic = root / "semantic.db"
        shutil.copyfile(original, semantic)
        with sqlite3.connect(semantic) as db:
            db.execute("UPDATE account SET balance=11 WHERE id=1")
            db.commit()
        business = probe(semantic)
        require(business["integrity"] == business["quick"] == "ok"
                and not business["foreign_keys"] and not business["business_ok"],
                "expected semantic discrepancy")

        invalid = root / "invalid_header.db"
        shutil.copyfile(original, invalid)
        with invalid.open("r+b") as file:
            file.write(b"INVALID SQLITE!!")
        try:
            with sqlite3.connect(invalid) as db:
                db.execute("PRAGMA quick_check").fetchall()
        except sqlite3.DatabaseError as exc:
            error = {"code": getattr(exc, "sqlite_errorcode", None),
                     "name": getattr(exc, "sqlite_errorname", None)}
            require(error["code"] == sqlite3.SQLITE_NOTADB, "unexpected header error")
        else:
            raise RuntimeError("invalid header unexpectedly accepted")

        require(sha(original) == original_sha, "original changed")
        with sqlite3.connect(original) as db:
            version, source = db.execute("SELECT sqlite_version(),sqlite_source_id()").fetchone()
        print(json.dumps({"python": platform.python_version(), "platform": platform.platform(),
                          "sqlite_version": version, "sqlite_source_id": source,
                          "baseline_sha256": original_sha, "baseline": baseline,
                          "foreign_key": fk, "semantic": business, "header": error,
                          "original_preserved": True}, sort_keys=True))


if __name__ == "__main__":
    main()
