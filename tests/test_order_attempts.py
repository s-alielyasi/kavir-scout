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


class EntryBarrierTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_cannot_bypass_an_unresolved_telegram_attempt(self):
        from dataclasses import replace
        from unittest.mock import patch
        from config import Config
        from kavirtire.errors import SafetyError
        from kavirtire.security import SecretFilter
        from kavirtire.workflow import run
        with tempfile.TemporaryDirectory() as directory:
            config = replace(Config.from_env({}), root=Path(directory))
            store = OrderAttemptStore(config.root / 'data/order_attempt.json')
            store.begin('a' * 32, date(2026, 10, 29))
            with patch('kavirtire.workflow.persistent_browser') as browser:
                with self.assertRaises(SafetyError):
                    await run(config, SecretFilter())
                browser.assert_not_called()

