from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from .environment import connect, initialize_workspace
from .ledger import check_ledger, initialize_ledger
from .storage import profile
from .transfer import Transfer, transfer


class StorageTests(unittest.TestCase):
    def test_profiles_and_two_views_with_same_ledger(self):
        with TemporaryDirectory() as directory:
            path = Path(initialize_workspace(Path(directory))["database"])
            initialize_ledger(path)
            self.assertEqual(profile(path, "delete")["journal"], "delete")
            self.assertEqual(profile(path, "wal"),
                             {"journal": "wal", "synchronous": 2, "foreign_keys": 1})
            with closing(connect(path, read_only=True)) as reader:
                query = "SELECT quantity FROM stock_balance WHERE item_id='item-bolt' AND location_id='loc-north'"
                reader.execute("BEGIN")
                self.assertEqual(reader.execute(query).fetchone(), (10,))
                transfer(path, Transfer("t1", "item-bolt", "loc-north", "loc-south", 3))
                self.assertEqual(reader.execute(query).fetchone(), (10,))
                reader.execute("ROLLBACK")
                self.assertEqual(reader.execute(query).fetchone(), (7,))
            self.assertTrue(check_ledger(path)["ok"])
