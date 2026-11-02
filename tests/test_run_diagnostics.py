import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from kavirtire.run_diagnostics import CURRENT, RunDiagnostics, diagnostic_step


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.report = RunDiagnostics(self.root, 'a'*32)

    def records(self):
        return [json.loads(line) for line in (self.root/'logs/diagnostics/workflow.jsonl').read_text().splitlines()]

    async def test_exception_has_locations_and_times_without_payload_or_locals(self):
        secret = '0012345678 OTP-AbCd1234 https://bpm.shaparak.ir/pay?token=secret'
        @diagnostic_step
        async def failing():
            raise RuntimeError(secret)
        token = CURRENT.set(self.report)
        try:
            with self.assertRaises(RuntimeError):
                await failing()
        finally:
            CURRENT.reset(token)
        records = self.records()
        error = next(item for item in records if item['event']=='exception')
        self.assertEqual(error['error_type'], 'RuntimeError')
        self.assertTrue(error['frames'])
        self.assertIn('line', error['frames'][-1])
        self.assertEqual(error['run_id'], 'a'*32)
        self.assertTrue(error['time_tehran'].endswith('+03:30'))
        self.assertTrue(error['time_utc'].endswith('+00:00'))
        output = json.dumps(records)
        for value in ('0012345678','AbCd1234','token=secret'):
            self.assertNotIn(value, output)
        if os.name != 'nt':
            self.assertEqual((self.root/'logs/diagnostics/workflow.jsonl').stat().st_mode & 0o777, 0o600)

    async def test_external_payment_page_never_has_dom_evaluated(self):
        self.report.page = Mock(url='https://bpm.shaparak.ir/pay?token=secret',
            is_closed=Mock(return_value=False), evaluate=AsyncMock())
        await self.report.capture('checkout')
        self.report.page.evaluate.assert_not_awaited()
        self.assertFalse(self.records()[0]['dom_inspected'])
        self.assertNotIn('token=secret', str(self.records()))

    async def test_successful_operation_has_start_end_and_elapsed_duration(self):
        @diagnostic_step
        async def operation():
            return 'value-not-to-be-logged'
        token = CURRENT.set(self.report)
        try:
            self.assertEqual(await operation(), 'value-not-to-be-logged')
        finally:
            CURRENT.reset(token)
        self.assertEqual([r['event'] for r in self.records()], ['operation_started','operation_completed'])
        self.assertIn('elapsed_ms', self.records()[-1])
        self.assertNotIn('value-not-to-be-logged', str(self.records()))

    def test_rotation_limits_file_size_and_preserves_private_modes(self):
        # Lower the real handler's size in this fixture, exercise actual rotation.
        from kavirtire.run_diagnostics import PrivateRotatingFileHandler
        def small_handler(path, **kwargs):
            return PrivateRotatingFileHandler(path, maxBytes=600, backupCount=2, encoding='utf-8')
        with patch('kavirtire.run_diagnostics.PrivateRotatingFileHandler', side_effect=small_handler):
            for _ in range(15):
                self.report.event('test')
        files = list((self.root/'logs/diagnostics').iterdir())
        self.assertEqual(len(files), 3)
        if os.name != 'nt':
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in files))

    def test_unwritable_report_does_not_break_cancellation_or_expose_error(self):
        with patch.object(self.report, '_write', side_effect=OSError('secret-file-name')):
            with self.assertLogs('kavir', level='WARNING') as output:
                self.report.event('cancelled')
        self.assertNotIn('secret-file-name', str(output.output))
