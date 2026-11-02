from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from config import BotSettings
from kavirtire.orchestration.daily_login import DailyLogin
from kavirtire.orchestration.models import Receipt
from kavirtire.orchestration.owner_profile import DailyAdmission, OwnerProfile
from kavirtire.orchestration.scheduling import TEHRAN
from kavirtire.run_diagnostics import RunDiagnostics


class DailyLoginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        base = BotSettings.from_env({'TELEGRAM_BOT_TOKEN': '123:fixture_abcdefghijklmnopqrstuvwxyz',
            'TELEGRAM_ALLOWED_USER_ID': '123', 'TELEGRAM_ALLOWED_CHAT_ID': '123'})
        self.settings = replace(base, retailer=replace(base.retailer, root=self.root))
        self.now = datetime(2026, 11, 2, 7, 49, 59, tzinfo=TEHRAN)
        self.controller = SimpleNamespace(settings=self.settings, _closing=False, active=False,
            automatic_suppressed_date=None, owner='owner',
            clock=SimpleNamespace(now=lambda: self.now),
            profile=OwnerProfile(self.root, 123, 123), daily_admissions=DailyAdmission(self.root),
            arm=AsyncMock(return_value=Receipt(True, 'armed')),
            _notify=AsyncMock(), diagnostics=RunDiagnostics(self.root))
        self.scheduler = DailyLogin(self.controller)

    async def test_exact_login_boundary_and_restart_use_one_durable_daily_slot(self):
        self.controller.profile.save('0012345678')
        await self.scheduler.tick()
        self.controller.arm.assert_not_awaited()
        self.now += timedelta(seconds=1)
        await self.scheduler.tick()
        await self.scheduler.tick()
        await DailyLogin(self.controller).tick()
        self.controller.arm.assert_awaited_once_with('owner')
        self.assertEqual(json.loads((self.root/'data/daily_start.json').read_text())['date'], '2026-11-02')
        self.now += timedelta(days=1)
        await self.scheduler.tick()
        self.assertEqual(self.controller.arm.await_count, 2)

    async def test_missing_profile_cutoff_cancel_and_shutdown_cannot_start(self):
        self.now = self.now.replace(hour=8, minute=0)
        await self.scheduler.tick()
        self.controller.profile.save('0012345678')
        self.controller.automatic_suppressed_date = self.now.date()
        await self.scheduler.tick()
        self.controller.automatic_suppressed_date = None
        self.controller._closing = True
        await self.scheduler.tick()
        self.controller._closing = False
        self.now = self.now.replace(minute=15)
        await self.scheduler.tick()
        self.controller.arm.assert_not_awaited()

    async def test_late_start_before_cutoff_runs_once_and_refusal_is_not_retried(self):
        self.controller.profile.save('0012345678')
        self.now = self.now.replace(hour=8, minute=10)
        self.controller.arm.return_value = Receipt(False, 'unresolved_order_attempt')
        await self.scheduler.tick()
        await self.scheduler.tick()
        self.controller.arm.assert_awaited_once()
        self.controller._notify.assert_awaited_once_with('unresolved_order_attempt')

    async def test_manual_daily_run_consumes_slot_but_inventory_test_defers_it(self):
        self.controller.profile.save('0012345678')
        self.now = self.now.replace(minute=50)
        self.controller.active = True
        self.controller.status = lambda: SimpleNamespace(inventory_test=True)
        await self.scheduler.tick()
        self.assertFalse(self.controller.daily_admissions.path.exists())
        self.controller.status = lambda: SimpleNamespace(inventory_test=False)
        await self.scheduler.tick()
        self.controller.active = False
        await self.scheduler.tick()
        self.controller.arm.assert_not_awaited()

    async def test_european_summer_and_winter_clock_and_utc_use_tehran_date(self):
        self.controller.profile.save('0012345678')
        for month, zone in ((1, 'Europe/Berlin'), (7, 'Europe/Berlin'), (11, 'UTC')):
            with self.subTest(month=month, zone=zone):
                self.controller.daily_admissions.path.unlink(missing_ok=True)
                tehran = datetime(2026, month, 2, 7, 50, tzinfo=TEHRAN)
                self.now = tehran.astimezone(ZoneInfo(zone))
                self.assertEqual(tehran.astimezone(timezone.utc).strftime('%H:%M'), '04:20')
                before = self.controller.arm.await_count
                await self.scheduler.tick()
                self.assertEqual(self.controller.arm.await_count, before+1)
                self.assertEqual(json.loads(self.controller.daily_admissions.path.read_text())['date'], tehran.date().isoformat())

    async def test_corrupt_profile_and_daily_journal_fail_closed(self):
        self.now = self.now.replace(minute=50)
        self.controller.profile.save('0012345678')
        self.controller.profile.path.write_text('{bad')
        with self.assertRaises(RuntimeError):
            await self.scheduler.tick()
        self.controller.profile.save('0012345678')
        self.controller.daily_admissions.path.write_text('{bad')
        with self.assertRaises(RuntimeError):
            await self.scheduler.tick()
        self.controller.arm.assert_not_awaited()

    def test_profile_is_private_and_bound_to_configured_owner(self):
        profile = self.controller.profile
        profile.save('۰۰۱۲۳۴۵۶۷۸')
        self.assertEqual(OwnerProfile(self.root, 123, 123).national_id(), '0012345678')
        if os.name != 'nt':
            self.assertEqual(profile.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(RuntimeError):
            OwnerProfile(self.root, 999, 123).national_id()
        with self.assertRaises(ValueError):
            profile.save('invalid')
        self.assertEqual(profile.national_id(), '0012345678')

    def test_daily_journal_refuses_clock_rollback(self):
        journal = self.controller.daily_admissions
        self.assertTrue(journal.claim(self.now.date()))
        self.assertFalse(journal.claim(self.now.date()-timedelta(days=1)))
