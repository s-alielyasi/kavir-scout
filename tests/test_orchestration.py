import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from config import BotSettings
from kavirtire.orchestration.models import AuthorizedOwner, WorkflowState as S, PaymentResult
from kavirtire.orchestration.order_attempts import OrderAttemptStore
from kavirtire.orchestration.purchase_workflow import PurchaseOrchestrator
from kavirtire.orchestration.scheduling import TEHRAN


class FakeClock:
    def __init__(self, stamp='08:03:00'):
        self.current = datetime.fromisoformat('2026-10-29T' + stamp).replace(tzinfo=TEHRAN)
        self.elapsed = 0
    def now(self):
        return self.current
    def monotonic(self):
        return self.elapsed
    async def sleep(self, seconds):
        self.current += timedelta(seconds=seconds)
        self.elapsed += seconds
        await asyncio.sleep(0)


class OrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = BotSettings.from_env({'TELEGRAM_BOT_TOKEN': '123:fixture_abcdefghijklmnopqrstuvwxyz',
                                    'TELEGRAM_ALLOWED_USER_ID': '123', 'TELEGRAM_ALLOWED_CHAT_ID': '123'})
        self.settings = replace(base, retailer=replace(base.retailer, root=Path(self.tmp.name)), handoff_ttl=1)
        self.clock = FakeClock()
        self.owner = AuthorizedOwner(123, 123)
        self.transport = AsyncMock()
        self.transport.request_national_id.return_value = '0012345678'
        self.notifications = AsyncMock()
        self.service = AsyncMock()
        self.service.observe.return_value = 'available'
        self.service.checkout.return_value = PaymentResult('https://bpm.shaparak.ir/pay?token=fixture')
        self.entered = 0
        self.exit_gate = None
        self.observed = []
        async def observe(refresh=False):
            self.observed.append((self.clock.now(), refresh))
            return 'available'
        self.service.observe.side_effect = observe
        @asynccontextmanager
        async def factory(config, interactions):
            self.entered += 1
            try:
                yield self.service
            finally:
                if self.exit_gate:
                    await self.exit_gate.wait()
        self.controller = PurchaseOrchestrator(self.settings, lambda c: self.transport,
            self.notifications, factory, clock=self.clock)

    async def asyncTearDown(self):
        if self.exit_gate:
            self.exit_gate.set()
        await self.controller.close()
        self.tmp.cleanup()

    async def settle(self):
        for _ in range(1000):
            if not self.controller.active:
                return
            await asyncio.sleep(0)
        self.fail('Worker did not settle.')

    async def test_startup_is_idle_and_dry_run_never_selects(self):
        self.assertEqual(self.entered, 0)
        self.assertEqual(self.controller.status().state, S.IDLE)
        self.assertTrue((await self.controller.arm(self.owner)).accepted)
        await self.settle()
        self.assertEqual(self.controller.status().outcome, 'dry_run_target_found')
        self.service.checkout.assert_not_awaited()
        self.assertFalse(self.controller.attempts.blocked())

    async def test_unauthorized_and_late_arm_do_not_open_browser(self):
        self.assertFalse((await self.controller.arm(AuthorizedOwner(999, 123))).accepted)
        self.clock.current = self.clock.current.replace(hour=8, minute=15)
        self.assertFalse((await self.controller.arm(self.owner)).accepted)
        self.assertEqual(self.entered, 0)
        self.transport.request_national_id.assert_not_awaited()

    async def test_duplicate_arm_and_cancel_keep_status_responsive_during_cleanup(self):
        gate = asyncio.Event()
        async def authenticate(value):
            await gate.wait()
        self.service.authenticate.side_effect = authenticate
        self.exit_gate = asyncio.Event()
        receipts = await asyncio.gather(*(self.controller.arm(self.owner) for _ in range(5)))
        self.assertEqual(len({r.run_id for r in receipts}), 1)
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual(self.entered, 1)
        receipt = await asyncio.wait_for(self.controller.cancel(self.owner), .2)
        self.assertTrue(receipt.accepted)
        self.assertEqual(self.controller.status().state, S.CANCELLING)
        await asyncio.sleep(0)
        self.assertTrue(self.controller.active)
        self.exit_gate.set()
        await self.settle()
        self.assertEqual(self.controller.status().state, S.CANCELLED)

    async def test_cutoff_discards_late_stock_and_clock_rollback_fails_closed(self):
        async def late(refresh=False):
            self.clock.current = self.clock.current.replace(minute=15)
            return 'available'
        self.service.observe.side_effect = late
        await self.controller.arm(self.owner)
        await self.settle()
        self.assertEqual(self.controller.status().outcome, 'sale_window_ended')
        self.service.checkout.assert_not_awaited()

    async def test_live_order_barrier_survives_delivery_failure_and_restart(self):
        settings = replace(self.settings, dry_run=False, live_checkout_approved=True)
        self.controller.settings = settings
        self.notifications.payment.side_effect = RuntimeError('synthetic network outage')
        await self.controller.arm(self.owner)
        await self.settle()
        self.service.checkout.assert_awaited_once()
        self.assertTrue(self.controller.attempts.blocked())
        self.assertFalse((await self.controller.arm(self.owner)).accepted)
        self.assertNotIn('token=fixture', repr(self.controller.status()))

    async def test_wait_until_start_and_no_poll_after_cutoff(self):
        self.clock.current = self.clock.current.replace(hour=7, minute=59, second=59)
        await self.controller.arm(self.owner)
        await self.settle()
        self.assertEqual(self.observed[0][0].hour, 8)
        self.assertEqual(self.observed[0][0].minute, 0)

    async def test_clock_rollback_fails_without_order(self):
        async def backwards(refresh=False):
            self.clock.current -= timedelta(minutes=1)
            return 'available'
        self.service.observe.side_effect = backwards
        await self.controller.arm(self.owner)
        await self.settle()
        self.assertEqual(self.controller.status().outcome, 'clock_inconsistent')
        self.service.checkout.assert_not_awaited()

    async def test_pending_credentials_are_cancelled_at_cutoff(self):
        async def waiting():
            await asyncio.Event().wait()
        self.transport.request_national_id.side_effect = waiting
        await self.controller.arm(self.owner)
        await asyncio.sleep(0)
        self.clock.current = self.clock.current.replace(minute=15)
        await asyncio.wait_for(self.controller._task, 1)
        self.assertEqual(self.controller.state, S.COMPLETED)
        self.assertEqual(self.controller.outcome, 'sale_window_ended')
        self.assertIsNone(self.controller.broker.pending)
        self.assertEqual(self.entered, 0)

    async def test_successful_handoff_is_not_payment_confirmation(self):
        self.controller.settings = replace(self.settings, dry_run=False, live_checkout_approved=True)
        await self.controller.arm(self.owner)
        await self.settle()
        self.assertEqual(self.controller.outcome, 'payment_handoff_sent')
        self.assertEqual(self.controller.attempts.read()['status'], 'handed_off')
        self.notifications.payment.assert_awaited_once()
        self.service.checkout.assert_awaited_once()

    async def test_cancel_immediately_after_arm_opens_nothing(self):
        await self.controller.arm(self.owner)
        await self.controller.cancel(self.owner)
        await self.settle()
        self.assertEqual(self.entered, 0)
        self.assertEqual(self.controller.state, S.CANCELLED)

    async def test_shutdown_rejects_queued_arm_before_browser_or_prompt(self):
        self.controller.begin_shutdown()
        receipt = await self.controller.arm(self.owner)
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.reason, 'shutting_down')
        self.assertEqual(self.entered, 0)
        self.transport.request_national_id.assert_not_awaited()

    async def test_midnight_does_not_rearm_yesterdays_run(self):
        async def tomorrow(refresh=False):
            self.clock.current += timedelta(days=1)
            return 'available'
        self.service.observe.side_effect = tomorrow
        await self.controller.arm(self.owner)
        await self.settle()
        self.assertEqual(self.controller.outcome, 'sale_window_ended')
        self.service.checkout.assert_not_awaited()

    async def test_slow_poll_crossing_window_recomputes_spacing_without_overlap(self):
        self.clock.current = self.clock.current.replace(minute=4, second=59)
        starts = []
        async def slow(refresh=False):
            starts.append((self.clock.now(), refresh))
            if len(starts) == 1:
                await self.clock.sleep(10)
                return 'out_of_stock'
            return 'available'
        self.service.observe.side_effect = slow
        await self.controller.arm(self.owner)
        await self.settle()
        self.assertEqual((starts[1][0]-starts[0][0]).total_seconds(), 15)
        self.assertEqual([s[1] for s in starts], [False, True])

    async def test_login_reminder_is_once_per_run(self):
        self.clock.current = self.clock.current.replace(hour=7, minute=54, second=59)
        gate = asyncio.Event()
        async def authenticate(identity):
            await gate.wait()
        self.service.authenticate.side_effect = authenticate
        await self.controller.arm(self.owner)
        for _ in range(10):
            await asyncio.sleep(0)
        self.clock.current += timedelta(seconds=1)
        await asyncio.sleep(1.05)
        gate.set()
        await self.settle()
        reminders = [call for call in self.notifications.publish.await_args_list if call.args == ('login_reminder',)]
        self.assertEqual(len(reminders), 1)
