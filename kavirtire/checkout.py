"""One-way checkout with verified UI quantities; payment pages are never touched."""
import asyncio
from pathlib import Path
from playwright.async_api import BrowserContext, Error, Locator, Page, TimeoutError
from config import Config
from kavirtire import selectors as S
from kavirtire.diagnostics import LOG, capture_debug
from kavirtire.errors import BotError, QuantityLimit, SafetyError
from kavirtire.guard import HumanGuard
from kavirtire.security import SecretFilter, gateway_url, merchant_url
from kavirtire.shop import product_container
from kavirtire.text import matches_product, normalize_text, parse_quantity, text_pattern
from kavirtire.ui import button, field, has_text, settle, terminal, unique_visible


class GatewayWatcher:
    """Observe URLs of all tabs/popups, without reading or interacting with a gateway DOM."""
    def __init__(self, context: BrowserContext, hosts: tuple[str, ...]):
        self.context, self.hosts = context, hosts
        self.changed = asyncio.Event()
        self.new_pages: set[Page] = set()
        context.on('page', self.attach)
        for page in context.pages:
            self.attach(page, is_new=False)

    def attach(self, page: Page, is_new: bool = True) -> None:
        if is_new:
            self.new_pages.add(page)
        page.on('framenavigated', lambda _: self.changed.set())
        page.on('close', lambda _: self.changed.set())
        self.changed.set()

    async def wait_pending_navigation(self, timeout_ms: int) -> None:
        """A newly opened about:blank popup is not yet a payment decision."""
        for page in tuple(self.new_pages):
            if not page.is_closed() and page.url == 'about:blank':
                await page.wait_for_url(lambda url: str(url) != 'about:blank',
                                        wait_until='commit', timeout=timeout_ms)

    async def find(self) -> Page | None:
        for page in self.context.pages:
            if not page.is_closed() and gateway_url(page.url, self.hosts):
                return page
        return None

    async def wait(self, timeout_ms: int) -> Page | None:
        """Wait for navigation events, supporting redirects, tabs and window.open."""
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        while True:
            self.changed.clear()
            found = await self.find()
            if found:
                return found
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return await self.find()


class Checkout:
    def __init__(self, page: Page, config: Config, guard: HumanGuard, secrets: SecretFilter):
        self.page, self.config, self.guard, self.secrets = page, config, guard, secrets
        self.watcher = GatewayWatcher(page.context, config.gateway_hosts)
        self.attempted: set[str] = set()
        self.uncertain = False
        self.ui_changed = asyncio.Event()
        self.binding_ready = False

    async def arm_transition(self, snapshot: str) -> None:
        """Observe the current merchant document only, never evaluate on a gateway."""
        if not self.binding_ready:
            await self.page.expose_function('__kavir_checkout_changed', self.ui_changed.set)
            self.binding_ready = True
        self.ui_changed.clear()
        self.watcher.changed.clear()
        await self.page.evaluate(S.WATCH_CHECKOUT_JS, snapshot)

    async def wait_transition(self) -> bool:
        """Await DOM notification/navigation without polling a payment document."""
        tasks = [asyncio.create_task(self.ui_changed.wait()),
                 asyncio.create_task(self.watcher.changed.wait())]
        try:
            done, _ = await asyncio.wait(tasks, timeout=self.config.timeout_ms / 1000,
                                         return_when=asyncio.FIRST_COMPLETED)
            return bool(done)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def quantity_control(self, scope: Locator) -> Locator | None:
        candidate = await field(scope, S.QUANTITY_LABELS, S.QUANTITY_CSS)
        if candidate and await candidate.evaluate(S.IS_QUANTITY_CONTROL_JS):
            return candidate
        return await unique_visible(scope.locator(css) for css in S.QUANTITY_CSS)

    async def read_quantity(self, scope: Locator) -> int | None:
        """Read rendered form state, including Persian dropdown option labels."""
        control = await self.quantity_control(scope)
        if control:
            if await control.evaluate('(el) => el.tagName') == 'SELECT':
                options = control.locator('option:checked')
                return parse_quantity(await options.inner_text())
            return parse_quantity(await control.evaluate(S.QUANTITY_TEXT_JS) or '')
        display = await unique_visible(scope.locator(css) for css in S.QUANTITY_DISPLAY)
        if display:
            return parse_quantity(await display.evaluate(S.QUANTITY_TEXT_JS) or '')
        # Text-only order summaries need a labelled, unambiguous quantity.
        import re
        text = normalize_text(await scope.inner_text())
        values = re.findall(r'تعداد(?: حلقه| تایر)?\s*[:：]?\s*(\d+)\b', text)
        return int(values[0]) if len(values) == 1 else None

    async def set_quantity(self, scope: Locator | None) -> None:
        """Respect option availability, input constraints and disabled +/- buttons."""
        if not scope:
            raise SafetyError('SAFETY CHECK FAILED: no verified order row for quantity.')
        target = self.config.target_quantity
        control = await self.quantity_control(scope)
        if control:
            tag = await control.evaluate('(el) => el.tagName')
            if not await control.is_enabled():
                if await self.read_quantity(scope) != target:
                    raise QuantityLimit('Quantity is fixed by the site and differs from target.')
            elif tag == 'SELECT':
                options = control.locator('option')
                available = []
                for i in range(await options.count()):
                    option = options.nth(i)
                    if parse_quantity(await option.inner_text()) == target and await option.is_enabled():
                        available.append(await option.get_attribute('value'))
                if len(available) != 1 or available[0] is None:
                    raise QuantityLimit('Requested quantity is not an allowed unique option.')
                await control.select_option(value=available[0])
            else:
                for attribute, allowed in (('max', lambda n: target <= n), ('min', lambda n: target >= n)):
                    raw = await control.get_attribute(attribute)
                    if raw and not allowed(float(normalize_text(raw))):
                        raise QuantityLimit('Requested quantity exceeds the UI purchase limits.')
                if await control.is_editable():
                    await control.fill(str(target))
                    await control.press('Tab')
                elif await self.read_quantity(scope) != target:
                    await self.adjust_buttons(scope, target)
                if not await control.evaluate('(el) => !el.validity || el.validity.valid'):
                    raise QuantityLimit('Site validation rejected the requested quantity.')
        else:
            await self.adjust_buttons(scope, target)
        await settle(self.page)
        if await self.read_quantity(scope) != target or await has_text(self.page, S.QUANTITY_LIMIT):
            raise QuantityLimit('Site did not accept the requested quantity. No order submitted.')
        LOG.info('Quantity set to %s.', target)

    async def adjust_buttons(self, scope: Locator, target: int) -> None:
        current = await self.read_quantity(scope)
        if current is None or abs(target - current) > 100:
            raise QuantityLimit('Cannot safely read/change the quantity with +/- controls.')
        while current != target:
            action = await button(scope, S.PLUS if current < target else S.MINUS)
            if not action or not await action.is_enabled():
                raise QuantityLimit('Site quantity limit reached; no workaround attempted.')
            before = current
            await action.click()
            # Wait for actual displayed quantity update; no arbitrary sleeps.
            await scope.evaluate(S.WAIT_QUANTITY_JS, {'before': current,
                'selectors': list(S.QUANTITY_CSS + S.QUANTITY_DISPLAY), 'timeout': self.config.timeout_ms})
            current = await self.read_quantity(scope)
            if current is None or abs(current - target) >= abs(before - target):
                raise QuantityLimit('Quantity control did not move toward the requested value.')

    async def verify_candidate(self, scope: Locator | None) -> None:
        """Verify one selected candidate without treating the catalog as a cart."""
        if not scope or not matches_product(await scope.inner_text(), self.config.target_product,
                                            self.config.target_size):
            raise SafetyError('SAFETY CHECK FAILED: product or size differs/missing in order summary.')
        if await self.read_quantity(scope) != self.config.target_quantity:
            raise SafetyError('SAFETY CHECK FAILED: quantity differs/missing in order summary.')

    async def verify_order(self) -> Locator:
        """Re-read all three values and reject extra items before each cart submit."""
        region = await unique_visible(self.page.locator(css) for css in S.ORDER_REGIONS)
        root = region if region is not None else self.page
        scope = await product_container(root, S.ORDER_CONTAINERS, self.config)
        if scope is None and region is not None and await self.read_quantity(region) is not None:
            scope = region
        await self.verify_candidate(scope)
        # A matching target row is insufficient if another tire is also in the
        # same cart. Reject additional visible tire rows across supported markup.
        for selector in S.ORDER_CONTAINERS:
            rows = root.locator(selector)
            for i in range(await rows.count()):
                row = rows.nth(i)
                if not await row.is_visible():
                    continue
                text = normalize_text(await row.inner_text())
                import re
                if re.search(S.TIRE_SIZE_PATTERN, text, re.I) and not matches_product(
                        text, self.config.target_product, self.config.target_size):
                    raise SafetyError('SAFETY CHECK FAILED: another tire appears in the order/cart.')
        LOG.info('Order verified from UI: %s / %s / %s', self.config.target_product,
                 self.config.target_size, self.config.target_quantity)
        return scope

    async def manual(self, message: str) -> None:
        """No automatic resubmission after an uncertain mutating click."""
        LOG.warning(message)
        if merchant_url(self.page.url):
            await capture_debug(self.page, self.config.root, self.secrets, 'checkout')
        await terminal('مرحله را در مرورگر بررسی/تکمیل کنید؛ سفارش تازه نسازید. سپس Enter بزنید: ')

    async def capture_gateway(self, page: Page) -> str:
        """Persist just the latest URL; do not read, fill or click payment content."""
        url = page.url
        if not gateway_url(url, self.config.gateway_hosts):
            raise SafetyError('Unrecognized payment host.')
        (self.config.root / 'payment_url.txt').write_text(url + '\n', encoding='utf-8')
        LOG.info('Payment URL captured. Saved to payment_url.txt')
        # Gateway tokens deliberately do not enter the log file.
        print('\n========================================\nPAYMENT GATEWAY READY\n\n' + url +
              '\n\nOpen this URL to complete payment.\n========================================')
        return url

    async def run(self) -> str:
        """One-way transitions, with no retry of uncertain order submissions."""
        while True:
            gateway = await self.watcher.find()
            if gateway:
                return await self.capture_gateway(gateway)
            # Never interact with unknown external tabs, including a changed
            # payment provider or an identity-provider redirect.
            external = [p for p in self.page.context.pages if not p.is_closed()
                        and p.url != 'about:blank' and not merchant_url(p.url)]
            if external:
                await self.manual('External page detected. Automation paused; verify its purpose manually. '
                                  'If this is a gateway, update GATEWAY_HOSTS for a future run.')
                continue
            if self.uncertain:
                await self.manual('A checkout response was uncertain. Complete the existing checkout manually; '
                                  'no further automatic submissions will be made.')
                continue
            await self.guard.check()
            if await self.watcher.find():
                continue
            from kavirtire.shop import Shop
            if await Shop(self.page, self.config, self.guard).session_expired():
                await self.manual('Session expired after selection; inspect the existing order manually. '
                                  'Monitoring will not restart to avoid a duplicate order.')
                continue
            # Fail closed for a mismatched summary; never ask the user to approve
            # a robot submission with missing/wrong product, size or quantity.
            await self.verify_order()
            terms = await unique_visible(self.page.get_by_role('checkbox', name=text_pattern(t)) for t in S.TERMS)
            if terms and not await terms.is_checked():
                await terms.check()
            action = await button(self.page, S.CHECKOUT_NEXT)
            if not action or not await action.is_enabled():
                await self.manual('Complete required address/delivery or other human decisions in the browser.')
                continue
            await self.verify_order()
            text = normalize_text(await action.inner_text())
            snapshot = await self.page.locator('body').inner_text()
            # Body text, query strings and toast messages can change after a
            # failed submit. They must never re-arm an identical order action.
            signature = S.ACTION_PHASES.get(text, text)
            if signature in self.attempted:
                await self.manual('This checkout action was already attempted. No automatic repeat is permitted.')
                continue
            self.attempted.add(signature)  # mark BEFORE the side effect
            LOG.info('Continuing checkout: %s. Waiting for order/gateway transition.', text)
            try:
                await self.arm_transition(snapshot)
                await action.click()
                await self.watcher.wait_pending_navigation(self.config.timeout_ms)
                if await self.watcher.find() or not merchant_url(self.page.url):
                    continue
                if not await self.wait_transition():
                    self.uncertain = True
                    await self.manual('No confirmed checkout transition. Inspect the existing order manually.')
                    continue
                # Allow a navigation already in progress to finish, but never
                # read a gateway DOM or replay the action when uncertain.
                if not await self.watcher.find() and merchant_url(self.page.url):
                    await settle(self.page)
            except (Error, TimeoutError):
                if not await self.watcher.find():
                    self.uncertain = True
                    await self.manual('Checkout response uncertain. Check the existing order manually; '
                                      'the action will not be retried.')
