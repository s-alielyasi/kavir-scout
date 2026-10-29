import asyncio
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from config import BotSettings
from telegram_bot.app import build_application, serve
from telegram_bot.notifications import DeliveryFailure, TelegramNotifications
from telegram.error import NetworkError


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    def settings(self):
        return BotSettings.from_env({'TELEGRAM_BOT_TOKEN': '123:fixture_abcdefghijklmnopqrstuvwxyz',
            'TELEGRAM_ALLOWED_USER_ID': '123', 'TELEGRAM_ALLOWED_CHAT_ID': '123'})

    async def test_build_does_not_initialize_bot_or_construct_browser(self):
        factory = AsyncMock(side_effect=AssertionError('Browser started at boot'))
        runtime = build_application(self.settings(), service_factory=factory)
        self.assertFalse(runtime.controller.active)
        self.assertIsNone(runtime.controller.broker.pending)
        self.assertIsNone(runtime.application.persistence)
        self.assertEqual(runtime.application.concurrent_updates, 1)
        factory.assert_not_called()
        # Construction allocates both HTTP clients, without initializing a bot.
        await asyncio.gather(*(request.shutdown() for request in runtime.application.bot._request))

    async def test_explicit_proxy_reaches_both_telegram_http_clients(self):
        settings = replace(self.settings(), proxy_url='http://127.0.0.1:8889')
        with patch('httpx.AsyncClient', wraps=httpx.AsyncClient) as clients:
            runtime = build_application(settings, service_factory=AsyncMock())
        try:
            self.assertEqual(clients.call_count, 2)
            for call in clients.call_args_list:
                self.assertEqual(call.kwargs['proxy'], settings.proxy_url)
            self.assertFalse(runtime.controller.active)
        finally:
            await asyncio.gather(*(request.shutdown() for request in runtime.application.bot._request))

    async def test_lifecycle_stops_polling_then_worker_then_application(self):
        calls = []
        class Updater:
            running = False
            async def start_polling(self, **kwargs):
                self.running = True
                self.kwargs = kwargs
                calls.append('poll')
            async def stop(self):
                self.running = False
                calls.append('poll_stop')
        class Application:
            running = False
            updater = Updater()
            async def __aenter__(self):
                calls.append('initialize')
            async def __aexit__(self, *args):
                calls.append('shutdown')
            async def start(self):
                self.running = True
                calls.append('app_start')
            async def stop(self):
                self.running = False
                calls.append('app_stop')
        async def close():
            calls.append('worker_close')
        app = Application()
        stop = asyncio.Event()
        stop.set()
        await serve(SimpleNamespace(application=app, controller=SimpleNamespace(close=close)), stop)
        self.assertTrue(app.updater.kwargs['drop_pending_updates'])
        self.assertEqual(app.updater.kwargs['allowed_updates'], ['message'])
        self.assertEqual(calls, ['initialize', 'app_start', 'poll', 'poll_stop', 'worker_close', 'app_stop', 'shutdown'])

    async def test_transport_exception_does_not_expose_original_body(self):
        bot = AsyncMock()
        bot.send_message.side_effect = NetworkError('secret-fixture-URL-and-token')
        with self.assertRaises(DeliveryFailure) as error:
            await TelegramNotifications(bot, self.settings()).payment('https://bpm.shaparak.ir/pay?token=fixture')
        self.assertNotIn('secret-fixture', str(error.exception))

    async def test_cleanup_failure_still_stops_sdk_and_discards_queued_commands(self):
        app = MagicMock()
        app.__aenter__ = AsyncMock(return_value=app)
        app.__aexit__ = AsyncMock(return_value=False)
        app.running = True
        app.start = AsyncMock()
        app.stop = AsyncMock()
        app.updater = SimpleNamespace(running=False, start_polling=AsyncMock(), stop=AsyncMock())
        app.update_queue = asyncio.Queue()
        await app.update_queue.put('queued-arm-fixture')
        controller = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError('cleanup failed')))
        stop = asyncio.Event()
        stop.set()
        with self.assertRaises(RuntimeError):
            await serve(SimpleNamespace(application=app, controller=controller), stop)
        app.stop.assert_awaited_once()
        app.__aexit__.assert_awaited_once()
        self.assertTrue(app.update_queue.empty())
