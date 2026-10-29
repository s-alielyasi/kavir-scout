"""Exact product matching and sequential, UI-only stock polling."""
import asyncio
import re
from collections.abc import Awaitable, Callable
from playwright.async_api import Locator, Page, TimeoutError, expect
from config import Config
from kavirtire import selectors as S
from kavirtire.browser import retry_navigation
from kavirtire.diagnostics import LOG
from kavirtire.errors import AmbiguousElement, BotError, SessionExpired, SafetyError
from kavirtire.guard import HumanGuard
from kavirtire.text import matches_product, text_pattern, parse_quantity
from kavirtire.ui import Scope, button, field, has_text, settle, wait_loading, require_merchant
from kavirtire.text import normalize_text


async def product_container(page: Scope, selectors: tuple[str, ...], config: Config) -> Locator | None:
    """Find exactly one visible row/card containing both complete target identifiers."""
    require_merchant(page)
    # A CSS union deduplicates elements reached by several strategies. Prefer
    # the smallest matching container so a layout wrapper cannot hide siblings.
    candidates = page.locator(','.join(selectors))
    matches = []
    for index in range(await candidates.count()):
        item = candidates.nth(index)
        if await item.is_visible() and matches_product(await item.inner_text(),
                                                       config.target_product, config.target_size):
            matches.append(item)
    leaves = []
    for item in matches:
        contains_match = False
        for other in matches:
            if await item.evaluate('(el, other) => el !== other && el.contains(other)',
                                   await other.element_handle()):
                contains_match = True
                break
        if not contains_match:
            leaves.append(item)
    if len(leaves) > 1:
        raise AmbiguousElement('Multiple target rows found; no product will be selected.')
    return leaves[0] if leaves else None


class Shop:
    def __init__(self, page: Page, config: Config, guard: HumanGuard):
        self.page, self.config, self.guard = page, config, guard
        self.order_in_progress = False

    async def find_target_product(self) -> Locator | None:
        return await product_container(self.page, S.PRODUCT_CONTAINERS, self.config)

    async def inventory_recognized(self) -> bool:
        if await button(self.page, S.REFRESH) or await self.find_target_product():
            return True
        rows = self.page.locator(','.join(S.PRODUCT_CONTAINERS))
        for index in range(await rows.count()):
            item = rows.nth(index)
            if await item.is_visible() and re.search(S.TIRE_SIZE_PATTERN,
                    normalize_text(await item.inner_text()), re.I):
                return True
        return False

    async def session_expired(self) -> bool:
        # Only visible login DOM can send the workflow back to authentication.
        if await field(self.page, S.NATIONAL_ID_LABELS, S.NATIONAL_ID_CSS):
            return True
        if await field(self.page, S.OTP_LABELS, S.OTP_CSS):
            return True
        return bool(await button(self.page, S.LOGIN) and not await button(self.page, S.REFRESH))

    async def open(self) -> None:
        if await button(self.page, S.REFRESH) or await self.find_target_product():
            return
        purchase = await button(self.page, S.SHOP)
        if not purchase:
            raise BotError('Purchase page control not found; open the purchase page manually.')
        LOG.info('Opening shop...')
        await purchase.click()
        await settle(self.page)

    async def is_target_in_stock(self) -> bool:
        card = await self.find_target_product()
        if not card or await has_text(card, S.OUT_OF_STOCK):
            return False
        select = await button(card, S.SELECT_PRODUCT)
        if select:
            return await select.is_enabled()
        # A visible, enabled radio/checkbox can be the selection control.
        for role in ('radio', 'checkbox'):
            checks = card.get_by_role(role)
            if await checks.count() == 1 and await checks.is_visible():
                return await checks.is_enabled() and await has_text(card, S.IN_STOCK)
        return False  # missing evidence never means available

    async def refresh_inventory(self) -> None:
        """Wait for an observed inventory mutation, not the previous DOM snapshot."""
        await self.guard.check()
        if await self.session_expired():
            raise SessionExpired('Session expired before inventory refresh.')
        LOG.info('Refreshing inventory...')
        refresh = await button(self.page, S.REFRESH)
        while refresh and not await refresh.is_enabled():
            # Disabled controls may represent a site-enforced cooldown. Never
            # navigate around them; wait or return to a human checkpoint.
            try:
                await expect(refresh).to_be_enabled(timeout=self.config.timeout_ms)
            except AssertionError:
                await self.guard.interactions.request_manual_action('inventory_cooldown')
                await self.guard.check()
                if await self.session_expired():
                    raise SessionExpired('Session expired during inventory cooldown.')
                refresh = await button(self.page, S.REFRESH)
        if refresh and await refresh.is_enabled():
            # Watch the list parent, not the button or whole page. Replacing a
            # row with identical text is still a new inventory rendering.
            target = await self.find_target_product()
            root = None
            if target:
                # Watch only the product itself and its replacement. Its parent
                # can include the refresh button, whose spinner is not inventory.
                root = target
            else:
                for selector in S.PRODUCT_LIST:
                    lists = self.page.locator(selector)
                    if await lists.count() == 1 and await lists.is_visible():
                        root = lists
                        break
            if root:
                await root.evaluate(S.WATCH_INVENTORY_JS)
                await refresh.click()
                try:
                    await self.page.wait_for_function(S.WAIT_REFRESH_JS, timeout=self.config.timeout_ms)
                    await wait_loading(self.page, self.config.timeout_ms)
                    await settle(self.page)
                    return
                except (TimeoutError, AssertionError):
                    if await self.guard.blocked() or await self.session_expired():
                        return
                    # Unknown completion means stale inventory must not be used.
                    LOG.warning('No confirmed inventory update; reloading the purchase page.')
            # Without a confirmed inventory region, use a completed navigation.
        await retry_navigation(lambda: self.page.reload(wait_until='domcontentloaded'),
                               self.config.max_retries)
        await settle(self.page)

    async def monitor(self) -> None:
        """Stop polling before any selection or checkout operation begins."""
        if self.order_in_progress:
            raise SafetyError('Monitoring cannot restart after checkout began.')
        while True:
            await self.guard.check()
            if await self.session_expired():
                raise SessionExpired('Session expired while monitoring.')
            if not await button(self.page, S.REFRESH) and not await self.find_target_product():
                # No target is a normal stock condition only if a recognizable
                # product list is actually present. Never poll a changed/error page.
                recognized = False
                for selector in S.PRODUCT_CONTAINERS:
                    rows = self.page.locator(selector)
                    for index in range(await rows.count()):
                        item = rows.nth(index)
                        if await item.is_visible() and re.search(S.TIRE_SIZE_PATTERN,
                                normalize_text(await item.inner_text()), re.I):
                            recognized = True
                            break
                    if recognized:
                        break
                if not recognized:
                    raise BotError('Inventory page is not recognized. Manual inspection/selector adjustment required.')
            LOG.info('Checking %s - %s', self.config.target_product, self.config.target_size)
            if await self.is_target_in_stock():
                self.order_in_progress = True
                LOG.info('========================================\nTARGET PRODUCT IS AVAILABLE\n%s\n%s\n'
                         '========================================', self.config.target_product, self.config.target_size)
                return
            LOG.info('Out of stock.')
            await asyncio.sleep(self.config.poll_interval)
            await self.refresh_inventory()

    async def select_target_product(self, preflight: Callable[[Locator], Awaitable[None]] | None = None) -> bool:
        """Re-query and verify the exact card before one non-retried selection."""
        card = await self.find_target_product()
        if not card or not await self.is_target_in_stock():
            raise SafetyError('Target disappeared or is no longer in stock; no selection made.')
        LOG.info('Selected:\nProduct: %s\nSize: %s\nQuantity: %s',
                 self.config.target_product, self.config.target_size, self.config.target_quantity)
        select = await button(card, S.SELECT_PRODUCT)
        verified_purchase = False
        if select:
            name = normalize_text(await select.get_attribute('aria-label') or await select.inner_text())
            name = re.sub(r'[\ue000-\uf8ff]', '', name).strip()
            safe_select = any(text_pattern(t).fullmatch(name) for t in S.SAFE_SELECTION)
            # A generic 'Buy' may create an order immediately. Such actions
            # require the requested quantity to be readable before the click.
            if not safe_select:
                if preflight is None:
                    raise SafetyError('SAFETY CHECK FAILED: purchase control without quantity verification.')
                await preflight(card)
                verified_purchase = True
            await select.click()
        else:
            for role in ('radio', 'checkbox'):
                control = card.get_by_role(role)
                if await control.count() == 1:
                    await control.check()
                    break
            else:
                raise SafetyError('No unique product selection control.')
        await settle(self.page)
        return verified_purchase
