"""CP03: select a journal profile and verify its effective connection settings."""
from contextlib import closing

from .environment import connect
from .ledger import require_ledger
from .operation import execute, parser


def current(db):
    return dict(db.execute("SELECT 'journal',journal_mode FROM pragma_journal_mode "
                           "UNION ALL SELECT 'synchronous',synchronous FROM pragma_synchronous "
                           "UNION ALL SELECT 'foreign_keys',foreign_keys FROM pragma_foreign_keys"))


def profile(path, journal=None):
    with closing(connect(path)) as db:
        require_ledger(db)
        if journal is not None:
            if journal not in ("delete", "wal"):
                raise ValueError("expected delete or wal")
            actual = db.execute(f"PRAGMA journal_mode={journal}").fetchone()[0]
            if actual != journal:
                raise RuntimeError(f"requested {journal}, obtained {actual}")
        return current(db)


def main():
    args = parser(__doc__)
    args.add_argument("--journal", choices=("delete", "wal"))
    options = args.parse_args()
    return execute(lambda: profile(options.database, options.journal))


if __name__ == "__main__":
    raise SystemExit(main())
