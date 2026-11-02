"""Explicit workflow states and a single order attempt per process."""
from enum import Enum, auto
import re
from uuid import uuid4
from playwright.async_api import Error
from config import Config
from kavirtire import selectors as S
from kavirtire.browser import persistent_browser, retry_navigation
from kavirtire.checkout import Checkout
from kavirtire.diagnostics import LOG, capture_debug
from kavirtire.errors import BotError, QuantityLimit, SafetyError, SessionExpired
from kavirtire.guard import HumanGuard
from kavirtire.login import Login
from kavirtire.security import SecretFilter, merchant_url
from kavirtire.shop import Shop
from kavirtire.text import normalize_text
from kavirtire.ui import terminal
from kavirtire.orchestration.order_attempts import OrderAttemptStore
from kavirtire.orchestration.scheduling import TehranClock


class State(Enum):
    START = auto()
    CHECK_SESSION = auto()
    LOGIN = auto()
    PROFILE = auto()
    SHOP = auto()
    MONITOR_STOCK = auto()
    SELECT_PRODUCT = auto()
    SET_QUANTITY = auto()
    CHECKOUT = auto()
    PAYMENT_GATEWAY = auto()
    DONE = auto()


def enforce_published_limit(text: str, quantity: int) -> None:
    """Stop at an explicit site-published purchase cap, including the current 2-tire cap."""
    caps = re.findall(S.PURCHASE_LIMIT_PATTERN, normalize_text(text))
    if caps and quantity > min(map(int, caps)):
        raise QuantityLimit('Published site purchase limit is below TARGET_QUANTITY. '
                            'No login or order attempted. Review the current site terms; '
                            'the bot will not bypass the limit.')


async def run(config: Config, secrets: SecretFilter) -> None:
    state = State.START
    attempts = OrderAttemptStore(config.root / 'data/order_attempt.json')
    if attempts.blocked():
        raise SafetyError('An unresolved order attempt blocks a new CLI run. See the recovery guide.')
    run_id = uuid4().hex

    def transition(next_state: State) -> None:
        nonlocal state
        state = next_state
        LOG.info('State: %s', state.name)

    async with persistent_browser(config) as (context, page):
        guard = HumanGuard(page)
        login = Login(page, config, guard, secrets)
        shop = Shop(page, config, guard)
        checkout = Checkout(page, config, guard, secrets)
        try:
            LOG.info('Opening %s', config.store_url)
            await retry_navigation(lambda: page.goto(config.store_url, wait_until='domcontentloaded'),
                                   config.max_retries)
            await guard.check()
            enforce_published_limit(await page.locator('body').inner_text(), config.target_quantity)
            while True:
                transition(State.CHECK_SESSION)
                transition(State.LOGIN)
                await login.ensure()
                transition(State.PROFILE)
                transition(State.SHOP)
                try:
                    await shop.open()
                except BotError:
                    await capture_debug(page, config.root, secrets, 'shop')
                    await terminal('صفحه خرید را در مرورگر باز کنید و سپس Enter بزنید: ')
                transition(State.MONITOR_STOCK)
                try:
                    await shop.monitor()
                    break
                except SessionExpired:
                    LOG.info('Session expired. Monitoring paused; re-authenticating.')
                except BotError:
                    await capture_debug(page, config.root, secrets, 'inventory')
                    await terminal('صفحه موجودی قابل تشخیص نیست؛ آن را بررسی/باز کنید و سپس Enter بزنید: ')
            transition(State.SELECT_PRODUCT)
            await guard.check()
            # A product's buy button may itself create an order. If quantity is
            # already offered here, set and verify it before even selecting.
            candidate = await shop.find_target_product()
            if candidate and (await checkout.quantity_control(candidate)
                              or await checkout.read_quantity(candidate) is not None):
                await checkout.set_quantity(candidate)
                await checkout.verify_candidate(candidate)
            await checkout.watcher.prepare()
            attempts.begin(run_id, TehranClock().now().date())
            verified_purchase = await shop.select_target_product(checkout.verify_candidate)
            transition(State.SET_QUANTITY)
            if await checkout.watcher.find():
                # No interaction with a gateway, and no false success for a
                # selection that bypassed a verified order summary.
                if not verified_purchase:
                    raise SafetyError('Unexpected gateway after product selection. Inspect the order manually; '
                                      'do not start another order.')
                await checkout.capture_gateway(await checkout.watcher.find())
            else:
                await guard.check()
                await checkout.set_quantity(await shop.find_target_product())
                transition(State.CHECKOUT)
                await checkout.run()
            attempts.handed_off(run_id)
            transition(State.PAYMENT_GATEWAY)
            await terminal('Payment URL captured. Press Enter to close browser... ')
            transition(State.DONE)
        except Exception:
            if config.debug_artifacts and state not in (State.LOGIN, State.CHECK_SESSION) and merchant_url(page.url):
                await capture_debug(page, config.root, secrets)
            raise
