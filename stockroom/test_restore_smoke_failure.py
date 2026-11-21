"""CP10 negative control: a failed restore smoke must not leave a selectable candidate."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from .backup import capture, validate
from .restore import rehearse
from .test_backup import ready


class RestoreSmokeFailureTests(TestCase):
    def test_smoke_failure_cleans_candidate_and_preserves_source(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            live = ready(root)
            before = validate(live)
            bundle = Path(capture(live, root)["bundle"])
            with patch("stockroom.restore.smoke", side_effect=ValueError("injected smoke failure")) as smoke:
                with self.assertRaisesRegex(ValueError, "injected smoke failure"):
                    rehearse(live, bundle, root)
            smoke.assert_called_once()
            self.assertEqual(list(root.glob("stockroom-restore-*")), [])
            self.assertEqual(validate(live), before)
