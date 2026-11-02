"""Browser adapter owned exclusively by the admitted workflow task."""
from contextlib import asynccontextmanager
import re

from kavirtire import selectors as S
from kavirtire.browser import persistent_browser, retry_navigation
from kavirtire.checkout import Checkout
from kavirtire.errors import BotError, QuantityLimit, SafetyError, SessionExpired
from kavirtire.guard import HumanGuard
from kavirtire.login import Login
from kavirtire.orchestration.models import PaymentResult
from kavirtire.security import SecretFilter, merchant_url
from kavirtire.shop import Shop, product_container
from kavirtire.text import normalize_text
from kavirtire.ui import button
from kavirtire.workflow import enforce_published_limit


class RetailerSession:
    def __init__(self, config, page, interactions, *, dry_run):
        self.config, self.page, self.interactions = config, page, interactions
        self.dry_run = dry_run
        self.secrets = SecretFilter()
        self.guard = HumanGuard(page, interactions)
        self.login = Login(page, config, self.guard, self.secrets, interactions)
        self.shop = Shop(page, config, self.guard)
        self.order = Checkout(page, config, self.guard, self.secrets)
        self.opened = False
        self.published_cap = None
        self.policy_disallowed = False

    async def _policy(self):
        if not merchant_url(self.page.url):
            raise SafetyError('Purchase policy cannot be read outside the merchant.')
        text = await self.page.locator('body').inner_text()
        caps = re.findall(S.PURCHASE_LIMIT_PATTERN, normalize_text(text))
        if caps:
            self.published_cap = min(map(int, caps))
        try:
            enforce_published_limit(text, self.config.target_quantity)
        except QuantityLimit:
            self.policy_disallowed = True
            if not self.dry_run:
                raise

    async def authenticate(self, identity):
        try:
            if not self.opened:
                await retry_navigation(lambda: self.page.goto(self.config.store_url, wait_until='domcontentloaded'),
                                       self.config.max_retries)
                self.opened = True
            if await self.guard.blocked():
                identity = ''
            await self.guard.check()
            await self._policy()
            authentication = self.login.ensure(identity or None)
            identity = ''
            await authentication
            authentication = None
        finally:
            identity = ''
        while True:
            try:
                await self.shop.open()
                return
            except BotError:
                await self.interactions.request_manual_action('purchase_page_unknown')

    async def observe(self, *, refresh=False):
        await self.guard.check()
        if await self.shop.session_expired():
            raise SessionExpired('Session expired before stock observation.')
        if refresh:
            await self.shop.refresh_inventory()
        await self.guard.check()
        if await self.shop.session_expired():
            raise SessionExpired('Session expired during stock observation.')
        while not await self.shop.inventory_recognized():
            await self.interactions.request_manual_action('inventory_unknown')
            await self.guard.check()
            if await self.shop.session_expired():
                raise SessionExpired('Session expired at manual inventory checkpoint.')
        if await self.shop.is_target_in_stock():
            return 'available'
        return 'out_of_stock' if await self.shop.find_target_product() else 'target_absent'

    async def preflight_live(self):
        if self.dry_run:
            raise SafetyError('Dry run cannot enter checkout.')
        await self.guard.check()
        await self._policy()
        if self.published_cap is None or self.config.target_quantity > self.published_cap:
            raise QuantityLimit('A compatible current purchase policy has not been established.')
        if not await self.shop.is_target_in_stock():
            raise SafetyError('Target stock changed before order admission.')
        await self.order.watcher.find()

    async def checkout(self, *, before_selection):
        if self.dry_run:
            raise SafetyError('Dry run cannot select a product.')
        candidate = await self.shop.find_target_product()
        if candidate and (await self.order.quantity_control(candidate)
                          or await self.order.read_quantity(candidate) is not None):
            await self.order.set_quantity(candidate)
            await self.order.verify_candidate(candidate)
        before_selection()  # the last cutoff check before the first selection
        await self.order.watcher.prepare()
        self.shop.order_in_progress = True
        verified = await self.shop.select_target_product(self.order.verify_candidate)
        await self.order.watcher.wait_pending_navigation(self.config.timeout_ms)
        gateway = await self.order.watcher.find()
        if gateway:
            if not verified:
                raise SafetyError('Unexpected gateway before verified order selection.')
            return PaymentResult(await self.order.capture_gateway(gateway))
        if self.page.url != 'about:blank' and not merchant_url(self.page.url):
            return PaymentResult(await self.order.run())
        await self.guard.check()
        candidate = await product_container(self.page, S.ORDER_CONTAINERS, self.config)
        if candidate is None:
            candidate = await self.shop.find_target_product()
        await self.order.set_quantity(candidate)
        return PaymentResult(await self.order.run())


@asynccontextmanager
async def browser_session(config, interactions, *, dry_run=True):
    async with persistent_browser(config) as (context, page):
        yield RetailerSession(config, page, interactions, dry_run=dry_run)
