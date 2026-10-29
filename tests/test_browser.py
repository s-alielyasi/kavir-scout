"""Real Chromium fixtures; no credentials, SMS, purchases or live API calls."""
import tempfile
import asyncio
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch
from playwright.async_api import async_playwright
from config import Config
from kavirtire.errors import AmbiguousElement, BotError, QuantityLimit, SafetyError
from kavirtire.guard import HumanGuard
from kavirtire.security import SecretFilter
from kavirtire.shop import Shop
from kavirtire.checkout import Checkout, GatewayWatcher
from kavirtire.login import Login
from kavirtire.workflow import enforce_published_limit
from kavirtire.ui import button

PRODUCT = 'Perfect (R14) KB27'
SIZE = '185/65R14'


def row(size=SIZE, quantity='4', maximum='4'):
    return (f'<article>{PRODUCT} <span>{size}</span>'
            f'<label>تعداد<input type="number" value="{quantity}" max="{maximum}"></label>'
            '<button>انتخاب</button></article>')


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.page.set_default_timeout(1000)
        self.tmp = tempfile.TemporaryDirectory()
        self.config = replace(Config.from_env({}), root=Path(self.tmp.name),
                              user_data_dir=Path(self.tmp.name) / 'profile', timeout_ms=1000)
        self.guard = HumanGuard(self.page)
        self.secrets = SecretFilter()
        self.shop = Shop(self.page, self.config, self.guard)
        self.checkout = Checkout(self.page, self.config, self.guard, self.secrets)
        self.input_patch = patch.object(self.guard.interactions, 'request_manual_action', new=AsyncMock(
            side_effect=AssertionError('Unexpected manual input in fixture')))
        self.input_patch.start()

    async def asyncTearDown(self):
        self.input_patch.stop()
        await self.browser.close()
        await self.playwright.stop()
        self.tmp.cleanup()

    async def test_session_requires_positive_dom_evidence(self):
        login = Login(self.page, self.config, self.guard, self.secrets)
        await self.page.set_content('<p>خوش آمدید</p>')
        self.assertFalse(await login.is_logged_in())
        await self.page.set_content('<button>خرید</button><a>خروج از حساب</a>')
        self.assertTrue(await login.is_logged_in())
        await self.page.set_content('<label>کد ملی<input></label><button>خرید</button>')
        self.assertFalse(await login.is_logged_in())

    async def test_button_with_fontawesome_icon_in_accessible_name(self):
        await self.page.set_content('<button aria-label="\uf00c ورود">ورود</button>')
        self.assertIsNotNone(await button(self.page, ('ورود',)))

    async def test_recaptcha_badge_is_not_an_interactive_challenge(self):
        await self.context.route('https://www.google.com/recaptcha/**', lambda route: route.fulfill(body='fixture'))
        await self.page.set_content('''<div class="grecaptcha-badge">
            <iframe src="https://www.google.com/recaptcha/api2/anchor" title="reCAPTCHA"></iframe>
            </div>''')
        self.assertFalse(await self.guard.blocked())
        await self.page.set_content('<iframe src="https://www.google.com/recaptcha/api2/bframe" title="challenge"></iframe>')
        self.assertTrue(await self.guard.blocked())

    async def test_target_must_be_one_container(self):
        await self.page.set_content(f'<article>{PRODUCT}</article><article>{SIZE}</article>')
        self.assertIsNone(await self.shop.find_target_product())
        await self.page.set_content(row())
        self.assertIsNotNone(await self.shop.find_target_product())

    async def test_live_div_product_structure(self):
        await self.page.set_content(f'''<div class="products"><div class="product">
            <div class="info"><h2 class="title">{PRODUCT}</h2><span>{SIZE}</span>
            <span>اتمام موجودی</span><button hidden>افزودن به سبد خرید</button></div>
            </div></div>''')
        self.assertIsNotNone(await self.shop.find_target_product())
        self.assertFalse(await self.shop.is_target_in_stock())

    async def test_duplicate_target_is_ambiguous(self):
        await self.page.set_content(row() + row())
        with self.assertRaises(AmbiguousElement):
            await self.shop.find_target_product()

    async def test_out_of_stock_overrides_enabled_button(self):
        await self.page.set_content(row().replace('</article>', '<span>ناموجود</span></article>'))
        self.assertFalse(await self.shop.is_target_in_stock())

    async def test_refresh_waits_for_new_inventory(self):
        await self.page.set_content('''<button onclick="setTimeout(() =>
            document.querySelector('article').outerHTML = window.updated, 180)">
            به روز رسانی موجودی</button>''' + row().replace('انتخاب', 'ناموجود'))
        await self.page.evaluate('(html) => window.updated = html', row())
        self.assertFalse(await self.shop.is_target_in_stock())
        await self.shop.refresh_inventory()
        self.assertTrue(await self.shop.is_target_in_stock())

    async def test_quantity_limit_prevents_purchase(self):
        await self.page.set_content(row(quantity='2', maximum='2'))
        target = await self.shop.find_target_product()
        with self.assertRaises(QuantityLimit):
            await self.checkout.set_quantity(target)
        self.assertEqual(await self.page.locator('input').input_value(), '2')

    async def test_wrong_summary_refuses_order(self):
        await self.page.set_content(row(size='195/65R14') + '<button>ثبت سفارش</button>')
        with self.assertRaises(SafetyError):
            await self.checkout.verify_order()

    async def test_quantity_is_set_and_read_back(self):
        await self.page.set_content(row(quantity='1'))
        await self.checkout.set_quantity(await self.shop.find_target_product())
        await self.checkout.verify_order()
        self.assertEqual(await self.page.locator('input').input_value(), '4')

    async def test_dropdown_quantity(self):
        await self.page.set_content(f'<article>{PRODUCT} {SIZE}<label>تعداد<select>'
                                    '<option value="two">۲ حلقه</option>'
                                    '<option value="four">۴ حلقه</option></select></label></article>')
        await self.checkout.set_quantity(await self.shop.find_target_product())
        await self.checkout.verify_order()
        self.assertEqual(await self.page.locator('select').input_value(), 'four')

    async def test_gateway_same_tab(self):
        watcher = GatewayWatcher(self.context, self.config.gateway_hosts)
        await self.page.route('https://bpm.shaparak.ir/**', lambda route: route.fulfill(body='<h1>Gateway</h1>'))
        await self.page.goto('https://bpm.shaparak.ir/pay?token=fake')
        self.assertEqual((await watcher.find()).url, self.page.url)

    async def test_gateway_new_tab_and_unknown_host(self):
        watcher = GatewayWatcher(self.context, self.config.gateway_hosts)
        await self.context.route('https://**/*', lambda route: route.fulfill(body='<h1>Fixture</h1>'))
        await self.page.goto('https://unknown.example/pay')
        self.assertIsNone(await watcher.find())
        other = await self.context.new_page()
        await other.goto('https://bpm.shaparak.ir/pay?token=fake')
        self.assertEqual((await watcher.find()).url, other.url)

    async def test_protection_is_detected(self):
        await self.page.set_content('<p>در صف انتظار</p>')
        self.assertTrue(await self.guard.blocked())

    async def test_published_limit_stops_four_tires(self):
        with self.assertRaises(QuantityLimit):
            enforce_published_limit('امکان ۲ حلقه تایر در ۶ ماه فراهم می باشد.', 4)
        enforce_published_limit('امکان ۲ حلقه تایر در ۶ ماه فراهم می باشد.', 2)

    async def test_plus_minus_quantity(self):
        await self.page.set_content(f'''<article>{PRODUCT} {SIZE}
            <span class="quantity-value">۱</span>
            <button aria-label="افزایش تعداد" onclick="const e=document.querySelector('.quantity-value');
                e.textContent=String(Number(e.textContent.replace('۱','1'))+1)">+</button>
            </article>''')
        await self.checkout.set_quantity(await self.shop.find_target_product())
        await self.checkout.verify_order()

    async def test_checkout_to_popup_does_not_fill_payment(self):
        await self.context.route('https://bpm.shaparak.ir/**', lambda route: route.fulfill(content_type='text/html; charset=utf-8',
            body='<label>شماره کارت<input id="card"></label>'))
        await self.context.route('https://kavirtire.ir/**', lambda route: route.fulfill(content_type='text/html; charset=utf-8', body=row() +
            '''<button onclick="window.open('https://bpm.shaparak.ir/pay?token=fixture')">ثبت سفارش</button>'''))
        await self.page.goto('https://kavirtire.ir/fixture')
        captured = await self.checkout.run()
        self.assertEqual(captured, 'https://bpm.shaparak.ir/pay?token=fixture')
        self.assertEqual((self.config.root / 'payment_url.txt').read_text().strip(), captured)
        gateway = await self.checkout.watcher.find()
        self.assertEqual(await gateway.locator('#card').input_value(), '')

    async def test_debug_masks_input_and_known_otp(self):
        from kavirtire.diagnostics import capture_debug
        self.secrets.secrets.extend(['0012345678', '12345'])
        await self.page.set_content('''<input value="0012345678"><span>12345</span>
            <script>const otp = '12345'</script><div data-secret="0012345678">کاربر</div>''')
        await capture_debug(self.page, self.config.root, self.secrets)
        html = next((self.config.root / 'debug').glob('*.html')).read_text(encoding='utf-8')
        self.assertNotIn('0012345678', html)
        self.assertNotIn('12345', html)
        self.assertNotIn('data-secret', html)

    async def test_extra_cart_item_refuses_order(self):
        await self.page.set_content(row() + row(size='195/65R14'))
        with self.assertRaises(SafetyError):
            await self.checkout.verify_order()

    async def test_uncertain_submit_cannot_repeat_after_toast(self):
        await self.context.route('https://kavirtire.ir/**', lambda route: route.fulfill(
            content_type='text/html; charset=utf-8', body=row() + '''
            <button onclick="window.clicks=(window.clicks||0)+1;
              document.querySelector('#toast').textContent='خطای موقت '+window.clicks">ثبت سفارش</button>
            <div id="toast"></div>'''))
        await self.page.goto('https://kavirtire.ir/fixture')
        with self.assertRaises(AssertionError):
            await self.checkout.run()
        self.assertEqual(await self.page.evaluate('window.clicks'), 1)

    async def test_buy_without_quantity_is_never_clicked(self):
        await self.page.set_content(f'''<article>{PRODUCT} {SIZE}
            <button onclick="window.clicked=true">خرید</button></article>''')
        with self.assertRaises(SafetyError):
            await self.shop.select_target_product(self.checkout.verify_candidate)
        self.assertFalse(await self.page.evaluate('!!window.clicked'))

    async def test_candidate_verification_does_not_reject_catalog(self):
        await self.page.set_content(row() + row(size='195/65R14'))
        await self.checkout.verify_candidate(await self.shop.find_target_product())

    async def test_order_summary_excludes_recommendations(self):
        await self.page.set_content('<section data-order-summary>' + row() + '</section>' + row(size='195/65R14'))
        await self.checkout.verify_order()

    async def test_alias_order_button_cannot_resubmit(self):
        await self.context.route('https://kavirtire.ir/**', lambda route: route.fulfill(
            content_type='text/html; charset=utf-8', body=row() + '''
            <button onclick="window.clicks=(window.clicks||0)+1;
              this.textContent='تایید سفارش'">ثبت سفارش</button>'''))
        await self.page.goto('https://kavirtire.ir/fixture')
        with self.assertRaises(AssertionError):
            await self.checkout.run()
        self.assertEqual(await self.page.evaluate('window.clicks'), 1)

    async def test_end_to_end_workflow_with_existing_session(self):
        from contextlib import asynccontextmanager
        from kavirtire.workflow import run
        await self.context.route('https://bpm.shaparak.ir/**', lambda route: route.fulfill(
            content_type='text/html; charset=utf-8', body='<input id="card">'))
        fixture = row(quantity='1').replace('<button>انتخاب</button>',
            '''<button onclick="this.remove(); document.querySelector('#submit').hidden=false">انتخاب</button>''')
        fixture += '''<button id="submit" hidden
            onclick="window.open('https://bpm.shaparak.ir/pay?token=workflow')">ثبت سفارش</button>'''
        await self.context.route('https://kavirtire.ir/esale', lambda route: route.fulfill(
            content_type='text/html; charset=utf-8', body='<a>خروج از حساب</a><a href="/shop">خرید</a>'))
        await self.context.route('https://kavirtire.ir/shop', lambda route: route.fulfill(
            content_type='text/html; charset=utf-8', body=fixture))

        @asynccontextmanager
        async def fixture_context(config):
            yield self.context, self.page

        with patch('kavirtire.interactions.TerminalInteraction.request_manual_action', new=AsyncMock()), \
             patch('kavirtire.workflow.persistent_browser', fixture_context), \
             patch('kavirtire.workflow.terminal', new=AsyncMock(return_value='')):
            await run(self.config, self.secrets)
        self.assertEqual((self.config.root / 'payment_url.txt').read_text().strip(),
                         'https://bpm.shaparak.ir/pay?token=workflow')

    async def test_persistent_context_exports_state(self):
        from kavirtire.browser import persistent_browser
        config = replace(self.config, headless=True, user_data_dir=self.config.root / 'profile')
        async with persistent_browser(config) as (context, page):
            await context.add_cookies([{'name': 'fixture', 'value': 'saved', 'url': 'https://kavirtire.ir'}])
        self.assertTrue((config.user_data_dir / '.kavir-session.json').is_file())
        async with persistent_browser(config) as (context, page):
            cookies = await context.cookies('https://kavirtire.ir')
            self.assertIn('fixture', [item['name'] for item in cookies])

    async def test_login_national_id_and_terminal_otp(self):
        config = self.config
        login = Login(self.page, config, self.guard, self.secrets)
        # A local fixture, not the site's SMS endpoint.
        await self.page.set_content('''<label>کد ملی<input name="n_code"></label>
            <button onclick="document.body.innerHTML=window.otpForm">ورود</button>''')
        otp_form = '''<label>کد تایید<input autocomplete="one-time-code"></label>
            <button onclick="document.body.innerHTML='<a>خروج از حساب</a><button>خرید</button>'">تایید</button>'''
        await self.page.evaluate('(html) => window.otpForm=html', otp_form)
        with patch.object(login.interactions, 'request_otp', new=AsyncMock(return_value='12345')):
            await login.ensure('0012345678')
        self.assertTrue(await login.is_logged_in())
        self.assertTrue((config.user_data_dir / '.kavir-session.json').exists())

    async def test_monitor_stops_on_session_expiration(self):
        from kavirtire.errors import SessionExpired
        self.shop.config = replace(self.config, poll_interval=0.01)
        await self.page.set_content('''<button onclick="document.body.innerHTML=window.loginForm">
            به روز رسانی موجودی</button>''' + row().replace('انتخاب', 'ناموجود'))
        await self.page.evaluate("() => window.loginForm='<label>کد ملی<input name=n_code></label>'")
        with self.assertRaises(SessionExpired):
            await self.shop.monitor()
        self.assertFalse(self.shop.order_in_progress)

    async def test_refresh_button_loading_does_not_count_as_inventory(self):
        await self.page.set_content('''<button onclick="this.disabled=true;
            setTimeout(() => document.querySelector('article').outerHTML = window.updated, 180)">
            به روز رسانی موجودی</button>''' + row())
        await self.page.evaluate('(html) => window.updated = html', row().replace('انتخاب', 'ناموجود'))
        await self.shop.refresh_inventory()
        self.assertFalse(await self.shop.is_target_in_stock())

    async def test_refresh_pauses_for_new_protection(self):
        await self.page.set_content('''<p>در صف انتظار</p><button
            onclick="window.refreshed=true; document.querySelector('article').textContent='updated'">
            به روز رسانی موجودی</button>''' + row())

        async def human_completes(prompt):
            self.assertFalse(await self.page.evaluate('!!window.refreshed'))
            await self.page.locator('p').evaluate('(el) => el.remove()')
            return ''

        with patch.object(self.guard.interactions, 'request_manual_action', side_effect=human_completes):
            await self.shop.refresh_inventory()
        self.assertTrue(await self.page.evaluate('window.refreshed'))

    async def test_unknown_inventory_page_needs_manual_inspection(self):
        await self.page.set_content('<h1>صفحه جدید و ناشناخته</h1>')
        with self.assertRaises(BotError):
            await asyncio.wait_for(self.shop.monitor(), timeout=1)
