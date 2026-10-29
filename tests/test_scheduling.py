from datetime import datetime, timezone
import unittest

from config import BotSettings
from kavirtire.orchestration.scheduling import Schedule, TEHRAN, get_poll_interval


class ScheduleTests(unittest.TestCase):
    def test_exact_boundaries_and_other_timezone(self):
        for stamp, expected in [('07:59:59', None), ('08:00:00', 5),
                                ('08:04:59', 5), ('08:05:00', 15),
                                ('08:09:59', 15), ('08:10:00', 30),
                                ('08:14:59', 30), ('08:15:00', None)]:
            now = datetime.fromisoformat('2026-10-29T' + stamp).replace(tzinfo=TEHRAN)
            with self.subTest(stamp=stamp):
                self.assertEqual(get_poll_interval(now), expected)
                self.assertEqual(get_poll_interval(now.astimezone(timezone.utc)), expected)
        with self.assertRaises(ValueError):
            get_poll_interval(datetime(2026, 10, 29, 8))

    def test_bound_date_and_next_boundary(self):
        now = datetime(2026, 10, 29, 8, 4, 59, tzinfo=TEHRAN)
        decision = Schedule().decide(now, now.date())
        self.assertEqual(decision.phase, 'open')
        self.assertEqual(decision.boundary.minute, 5)
        self.assertEqual(Schedule().decide(now, now.date().replace(day=28)).phase, 'closed')

    def test_bot_settings_are_private_and_fail_closed(self):
        env = {'TELEGRAM_BOT_TOKEN': '123456:fixture_token_abcdefghijklmnopqrstuvwxyz',
               'TELEGRAM_ALLOWED_USER_ID': '123', 'TELEGRAM_ALLOWED_CHAT_ID': '123'}
        settings = BotSettings.from_env(env)
        self.assertTrue(settings.dry_run)
        self.assertEqual(settings.retailer.target_quantity, 4)
        self.assertNotIn(env['TELEGRAM_BOT_TOKEN'], repr(settings))
        for override in ({'DRY_RUN': 'maybe'}, {'TELEGRAM_ALLOWED_USER_ID': ''},
                         {'TELEGRAM_ALLOWED_CHAT_ID': '-123'}, {'TELEGRAM_BOT_TOKEN': ''},
                         {'SALE_TIMEZONE': 'UTC'}, {'POLL_WINDOW_1_END': '08:20:00'},
                         {'POLL_WINDOW_2_INTERVAL': '0'}, {'OTP_INPUT_TIMEOUT_SECONDS': 'nan'},
                         {'DRY_RUN': 'false'}, {'DEBUG_ARTIFACTS_ENABLED': 'true'}):
            with self.subTest(override=tuple(override)), self.assertRaises(ValueError):
                BotSettings.from_env(env | override)

