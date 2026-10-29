from datetime import date
from pathlib import Path
import tempfile
import unittest

from kavirtire.orchestration.order_attempts import OrderAttemptStore, AttemptBlocked


class AttemptTests(unittest.TestCase):
    def test_restart_does_not_clear_guard_and_resolution_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'attempt.json'
            store = OrderAttemptStore(path)
            store.begin('a' * 32, date(2026, 10, 29))
            restarted = OrderAttemptStore(path)
            self.assertTrue(restarted.blocked())
            with self.assertRaises(AttemptBlocked):
                restarted.begin('b' * 32, date(2026, 10, 30))
            with self.assertRaises(AttemptBlocked):
                restarted.resolve('b' * 32, 'no_order')
            restarted.resolve('a' * 32, 'no_order')
            self.assertFalse(restarted.blocked())
            restarted.begin('b' * 32, date(2026, 10, 30))
            self.assertTrue(store.blocked())

    def test_corrupt_guard_blocks_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'attempt.json'
            path.write_text('{broken')
            self.assertTrue(OrderAttemptStore(path).blocked())

