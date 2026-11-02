import asyncio
from datetime import datetime, timedelta, timezone
import unittest

from kavirtire.orchestration.input_broker import InputBroker, normalize_credential


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_shot_reply_correlation_and_cleanup(self):
        now = datetime.now(timezone.utc)
        broker = InputBroker()
        request = broker.open('national_id', 'fixture', now + timedelta(seconds=30))
        broker.bind_prompt(request.request_id, 10)
        self.assertFalse(broker.offer('0012345678', reply_to=9, sent_at=now))
        self.assertTrue(broker.offer('۰۰۱۲۳۴۵۶۷۸', reply_to=10, sent_at=now))
        self.assertFalse(broker.offer('0012345678', reply_to=10, sent_at=now))
        self.assertEqual(await broker.wait(request.request_id), '0012345678')
        self.assertIsNone(broker.pending)

    async def test_stale_input_timeout_and_cancel(self):
        now = datetime.now(timezone.utc)
        broker = InputBroker()
        request = broker.open('otp', 'fixture', now + timedelta(seconds=30))
        broker.bind_prompt(request.request_id, 20)
        self.assertFalse(broker.offer('AbCd1234', reply_to=20, sent_at=now-timedelta(days=1)))
        task = asyncio.create_task(broker.wait(request.request_id))
        await asyncio.sleep(0)
        broker.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(broker.pending)
        request = broker.open('otp', 'fixture', now - timedelta(seconds=1))
        with self.assertRaises(TimeoutError):
            await broker.wait(request.request_id)
        self.assertIsNone(broker.pending)

    async def test_old_manual_checkpoint_cannot_resume_new_pause(self):
        broker = InputBroker()
        deadline = datetime.now(timezone.utc) + timedelta(seconds=30)
        first = broker.open('manual', 'fixture', deadline)
        broker.cancel()
        second = broker.open('manual', 'fixture', deadline)
        self.assertFalse(broker.resume(first.request_id))
        self.assertFalse(broker.resume(None))
        self.assertTrue(broker.resume(second.request_id))
        self.assertEqual(await broker.wait(second.request_id), '')

    def test_credentials_preserve_case_and_reject_internal_whitespace(self):
        self.assertEqual(normalize_credential('otp', ' AbCd۱۲۳۴ '), 'AbCd1234')
        for kind, text in [('otp', 'Ab Cd1234'), ('national_id', '123'), ('otp', 'abcd')]:
            with self.assertRaises(ValueError):
                normalize_credential(kind, text)

