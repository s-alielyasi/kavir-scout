"""Regressions from the local audit; synthetic pages, no live retailer calls."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from playwright.async_api import async_playwright

from config import Config
from kavirtire.checkout import Checkout
from kavirtire.errors import AmbiguousElement, SafetyError
from kavirtire.guard import HumanGuard
from kavirtire.security import SecretFilter
from kavirtire.shop import Shop
from tests.test_browser import row, PRODUCT, SIZE
from contextlib import asynccontextmanager
from datetime import timezone
from types import SimpleNamespace
from telegram import Update
from config import BotSettings
from kavirtire.orchestration.models import AuthorizedOwner, WorkflowState
from kavirtire.orchestration.purchase_workflow import PurchaseOrchestrator
from kavirtire.orchestration.retailer import RetailerSession
from tests.test_orchestration import FakeClock
from telegram_bot.handlers import Handlers
from telegram_bot.interactions import TelegramInteractions
from telegram_bot.notifications import TelegramNotifications


class SafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.tmp = tempfile.TemporaryDirectory()
        self.config = replace(Config.from_env({}), root=Path(self.tmp.name),
                              user_data_dir=Path(self.tmp.name) / 'profile', timeout_ms=1000)
        self.page.set_default_timeout(1000)
        self.guard = HumanGuard(self.page)
        self.secrets = SecretFilter()
        self.shop = Shop(self.page, self.config, self.guard)
        self.checkout = Checkout(self.page, self.config, self.guard, self.secrets)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.pw.stop()
        self.tmp.cleanup()

    async def merchant(self, body):
        await self.context.route('https://kavirtire.ir/**', lambda r: r.fulfill(
            content_type='text/html; charset=utf-8', body=body))
        await self.page.goto('https://kavirtire.ir/fixture')

    async def test_icon_cannot_rearm_order_creation(self):
        await self.merchant(row() + '''<button onclick="window.clicks=(window.clicks||0)+1;
            this.textContent='تایید سفارش'">&#xf00c; ثبت سفارش</button>''')
        with patch.object(self.checkout, 'manual', new=AsyncMock(side_effect=EOFError)):
            with self.assertRaises(EOFError):
                await self.checkout.run()
        self.assertEqual(await self.page.evaluate('window.clicks'), 1)

    async def test_secondary_safe_button_cannot_waive_buy_preflight(self):
        await self.page.set_content(f'''<article>{PRODUCT} {SIZE}
            <button onclick="window.bought=true">خرید</button>
            <button>افزودن به سبد خرید</button></article>''')
        preflight = AsyncMock(side_effect=SafetyError('Missing quantity.'))
        with self.assertRaises(SafetyError):
            await self.shop.select_target_product(preflight)
        self.assertFalse(await self.page.evaluate('!!window.bought'))

    async def test_unknown_extra_item_and_mixed_summary_are_rejected(self):
        for html in ('<section data-order-summary>' + row() +
                     '<div class="product">Other Tire 195/65R14 تعداد 2</div></section>',
                     f'''<section data-order-summary><div>{PRODUCT} 195/65R14
                     <label>تعداد<input name="quantity" value="4"></label></div>
                     <div>Other Tire {SIZE}</div></section>'''):
            await self.page.set_content(html)
            with self.subTest(html=html[:30]), self.assertRaises(SafetyError):
                await self.checkout.verify_order()

    async def test_mixed_selector_duplicates_are_ambiguous(self):
        await self.page.set_content(row() + row().replace('<article>', '<div class="product">').replace('</article>', '</div>'))
        with self.assertRaises(AmbiguousElement):
            await self.shop.find_target_product()

    async def test_old_or_unrelated_gateway_is_not_a_checkout_result(self):
        await self.merchant(row())
        await self.context.route('https://bpm.shaparak.ir/**', lambda r: r.fulfill(body='fixture'))
        old = await self.context.new_page()
        await old.goto('https://bpm.shaparak.ir/pay?token=old-fixture')
        with self.assertRaises(SafetyError):
            await self.checkout.run()

    async def test_disabled_refresh_waits_instead_of_reloading(self):
        visits = []
        async def serve(route):
            visits.append(route.request.url)
            await route.fulfill(content_type='text/html; charset=utf-8', body='''
                <button disabled onclick="document.querySelector('article').textContent='ناموجود'">بروزرسانی موجودی</button>
                <script>setTimeout(()=>document.querySelector('button').disabled=false,200)</script>''' + row())
        await self.context.route('https://kavirtire.ir/**', serve)
        await self.page.goto('https://kavirtire.ir/fixture')
        await self.shop.refresh_inventory()
        self.assertEqual(len(visits), 1)

    async def test_refresh_metadata_is_not_inventory_completion(self):
        await self.page.set_content('''<button onclick="document.querySelector('article').dataset.refreshing='true';
            setTimeout(()=>{document.querySelector('article').innerHTML='ناموجود';window.finished=true},300)">
            بروزرسانی موجودی</button>''' + row())
        await self.shop.refresh_inventory()
        self.assertTrue(await self.page.evaluate('!!window.finished'))
        self.assertFalse(await self.shop.is_target_in_stock())

    async def test_negative_quantity_is_not_the_target(self):
        await self.page.set_content(f'<article>{PRODUCT} {SIZE}<span class="quantity-value">-4</span></article>')
        with self.assertRaises(SafetyError):
            await self.checkout.verify_order()

    async def bot_flow(self, live):
        quantity = 2 if live else 4
        base = BotSettings.from_env({'TELEGRAM_BOT_TOKEN': '123:fixture_abcdefghijklmnopqrstuvwxyz',
            'TELEGRAM_ALLOWED_USER_ID': '123', 'TELEGRAM_ALLOWED_CHAT_ID': '123',
            'TARGET_QUANTITY': str(quantity)})
        config = replace(base.retailer, root=self.config.root, user_data_dir=self.config.user_data_dir,
                         timeout_ms=1000)
        settings = replace(base, retailer=config, dry_run=not live, live_checkout_approved=live, handoff_ttl=1)
        clock = FakeClock()
        fixture = row(quantity='1', maximum='4').replace('<button>انتخاب</button>',
            '<button onclick="window.selected=(window.selected||0)+1;this.remove();document.querySelector(\'#submit\').hidden=false">انتخاب</button>')
        shop = '<button>بروزرسانی موجودی</button>' + fixture + '''<button id="submit" hidden
            onclick="window.submitted=(window.submitted||0)+1;window.open('https://bpm.shaparak.ir/pay?token=bot-fixture')">ثبت سفارش</button>'''
        auth = '''<p>امکان ۲ حلقه تایر در ۶ ماه فراهم است.</p><label>کد ملی<input name="n_code"></label>
            <button onclick="document.body.innerHTML=window.otpForm">ورود</button>'''
        otp = '''<label>کد تایید<input autocomplete="one-time-code"></label>
            <button onclick="document.body.innerHTML=window.shop">تایید</button>'''
        import json
        html = auth + '<script>window.otpForm=' + json.dumps(otp) + ';window.shop=' + json.dumps(shop) + '</script>'
        await self.context.route('https://kavirtire.ir/**', lambda r: r.fulfill(content_type='text/html; charset=utf-8', body=html))
        await self.context.route('https://bpm.shaparak.ir/**', lambda r: r.fulfill(
            content_type='text/html; charset=utf-8', body='<input id="card">'))
        bank_queries = []
        original_locator = self.page.locator
        def track(selector, *args, **kwargs):
            if 'shaparak.ir' in self.page.url:
                bank_queries.append(selector)
            return original_locator(selector, *args, **kwargs)
        bot = AsyncMock()
        next_message = 0
        async def send(**kwargs):
            nonlocal next_message
            next_message += 1
            return SimpleNamespace(message_id=next_message)
        bot.send_message.side_effect = send
        session = None
        @asynccontextmanager
        async def factory(config, interactions):
            nonlocal session
            session = RetailerSession(config, self.page, interactions, dry_run=not live)
            yield session
        controller = PurchaseOrchestrator(settings, lambda c: TelegramInteractions(bot, c),
            TelegramNotifications(bot, settings), factory, clock=clock)
        handlers = Handlers(controller, bot, started_at=clock.now())
        update_id = 10
        async def respond(kind, value):
            nonlocal update_id
            for _ in range(300):
                pending = controller.broker.pending
                if pending and pending.kind == kind and pending.prompt_id:
                    break
                await asyncio.sleep(.01)
            else:
                self.fail('Expected correlated prompt was not produced: ' + kind)
            update_id += 1
            message = {'message_id': update_id, 'date': int(clock.now().timestamp()), 'text': value,
                'from': {'id':123,'is_bot':False,'first_name':'Fixture'}, 'chat': {'id':123,'type':'private'},
                'reply_to_message': {'message_id':pending.prompt_id, 'date':int(clock.now().timestamp()),
                    'chat':{'id':123,'type':'private'}, 'from':{'id':987,'is_bot':True,'first_name':'Bot'}}}
            await handlers.text(Update.de_json({'update_id':update_id,'message':message}, None), None)
        try:
            with patch.object(self.page, 'locator', side_effect=track):
                await controller.arm(AuthorizedOwner(123,123))
                await respond('national_id', '0012345678')
                await respond('otp', 'AbCd1234')
                await asyncio.wait_for(asyncio.shield(controller._task), 10)
            self.assertEqual(controller.state, WorkflowState.COMPLETED)
            self.assertIsNone(controller.broker.pending)
            self.assertEqual(session.secrets.secrets, [])
            self.assertEqual(bank_queries, [])
            self.assertFalse((config.root / 'payment_url.txt').exists())
            self.assertFalse((config.root / 'debug').exists())
            if live:
                self.assertEqual(await self.page.evaluate('window.selected'), 1)
                self.assertEqual(await self.page.evaluate('window.submitted'), 1)
                self.assertTrue(controller.attempts.blocked())
                gateway = await session.order.watcher.find()
                self.assertEqual(await gateway.locator('#card').input_value(), '')
                self.assertEqual(controller.outcome, 'payment_handoff_sent')
            else:
                self.assertEqual(await self.page.evaluate('window.selected||0'), 0)
                self.assertEqual(await self.page.evaluate('window.submitted||0'), 0)
                self.assertFalse(controller.attempts.blocked())
                self.assertTrue(session.policy_disallowed)
            for call in bot.send_message.await_args_list:
                self.assertNotIn('0012345678', str(call))
                self.assertNotIn('AbCd1234', str(call))
        finally:
            await controller.close()

    async def test_telegram_login_to_dry_run_uses_real_browser_without_selection(self):
        await self.bot_flow(live=False)

    async def test_telegram_login_to_single_fixture_order_and_private_gateway(self):
        await self.bot_flow(live=True)

    async def test_same_tab_direct_buy_observes_only_gateway_url(self):
        await self.merchant(row().replace('<button>انتخاب</button>',
            '<button onclick="location.href=\'https://bpm.shaparak.ir/pay?token=same-tab-fixture\'">خرید</button>'))
        await self.context.route('https://bpm.shaparak.ir/**', lambda r: r.fulfill(
            content_type='text/html', body='<input id="card">'))
        session = RetailerSession(replace(self.config, gateway_output=False), self.page, AsyncMock(), dry_run=False)
        original = self.page.locator
        bank_queries = []
        def track(selector, *args, **kwargs):
            if 'shaparak.ir' in self.page.url:
                bank_queries.append(selector)
            return original(selector, *args, **kwargs)
        with patch.object(self.page, 'locator', side_effect=track):
            result = await session.checkout(before_selection=lambda: None)
        self.assertEqual(result.url, 'https://bpm.shaparak.ir/pay?token=same-tab-fixture')
        self.assertEqual(bank_queries, [])

    async def test_cookie_backup_has_no_origin_storage_and_cannot_cross_profiles(self):
        from kavirtire.browser import save_session, restore_session_cookies, session_path
        await self.merchant('<p>Storage fixture</p>')
        await self.page.evaluate("localStorage.setItem('fixture_identity','fixture-private-storage')")
        await self.context.add_cookies([{'name':'fixture_session','value':'fixture-cookie','url':'https://kavirtire.ir'}])
        await save_session(self.context, self.config)
        self.assertNotIn('fixture-private-storage', session_path(self.config).read_text())
        await self.context.clear_cookies()
        other = replace(self.config, user_data_dir=self.config.root / 'other-profile')
        await restore_session_cookies(self.context, other)
        self.assertEqual(await self.context.cookies(), [])
        await restore_session_cookies(self.context, self.config)
        self.assertIn('fixture_session', [c['name'] for c in await self.context.cookies()])

    async def test_existing_session_requires_account_confirmation(self):
        from kavirtire.login import Login
        await self.page.set_content('<a>خروج از حساب</a><button>خرید</button>')
        interactions = AsyncMock()
        login = Login(self.page, self.config, self.guard, self.secrets, interactions)
        await login.ensure('0012345678')
        interactions.request_manual_action.assert_awaited_once_with('confirm_current_account')
        interactions.request_otp.assert_not_awaited()

    async def test_otp_reference_is_cleared_before_uncertain_response_manual_pause(self):
        from kavirtire.login import Login
        await self.page.set_content('<label>کد تایید<input autocomplete="one-time-code"></label>')
        interactions = AsyncMock()
        interactions.request_otp.return_value = 'AbCd1234'
        async def manual(reason):
            self.assertEqual(self.secrets.secrets, [])
        interactions.request_manual_action.side_effect = manual
        login = Login(self.page, self.config, self.guard, self.secrets, interactions)
        await login.submit_otp()
        self.assertEqual(self.secrets.secrets, [])

    async def test_rejected_otp_pauses_for_manual_resend_without_replay(self):
        from kavirtire.login import Login
        await self.page.set_content('''<label>کد تایید<input autocomplete="one-time-code"></label>
            <button onclick="window.submits=(window.submits||0)+1;document.querySelector('p').textContent='کد تایید نامعتبر'">تایید</button><p></p>''')
        interactions = AsyncMock()
        interactions.request_otp.return_value = 'AbCd1234'
        async def manual(reason):
            self.assertEqual(reason, 'otp_rejected_or_expired')
            self.assertEqual(self.secrets.secrets, [])
        interactions.request_manual_action.side_effect = manual
        login = Login(self.page, self.config, self.guard, self.secrets, interactions)
        await login.submit_otp()
        self.assertEqual(await self.page.evaluate('window.submits'), 1)
        interactions.request_otp.assert_awaited_once()
        interactions.request_manual_action.assert_awaited_once()
