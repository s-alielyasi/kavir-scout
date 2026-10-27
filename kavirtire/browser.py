"""Persistent Chromium lifecycle and read-only navigation retries."""
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Awaitable, Callable
import json
from typing import TypeVar
from playwright.async_api import BrowserContext, Error, Page, async_playwright
from config import Config
from kavirtire.diagnostics import LOG
from kavirtire.errors import BotError
from kavirtire.security import merchant_url

T = TypeVar('T')


async def retry_navigation(action: Callable[[], Awaitable[T]], attempts: int) -> T:
    """Only caller-approved read-only navigation can be retried, never order clicks."""
    for attempt in range(attempts):
        try:
            return await action()
        except Error:
            LOG.warning('Navigation failed (%s/%s).', attempt + 1, attempts)
            if attempt + 1 == attempts:
                raise BotError('Navigation failed after bounded retries.') from None
    raise AssertionError('attempts must be positive')


async def save_session(context: BrowserContext, config: Config) -> None:
    path = config.root / 'data/storage_state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = await context.storage_state(indexed_db=True)
        state['cookies'] = [cookie for cookie in state['cookies']
                            if merchant_url('https://' + cookie['domain'].lstrip('.'))]
        state['origins'] = [origin for origin in state['origins'] if merchant_url(origin['origin'])]
        path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        LOG.info('Session saved.')
    except Error:
        LOG.warning('Storage-state export unavailable; persistent profile remains primary.')


async def restore_session_cookies(context: BrowserContext, config: Config) -> None:
    """Chromium may discard session cookies on close; restore only missing merchant ones.

    Never overwrite a current cookie, restore expired cookies, or import gateway
    credentials. LocalStorage/IndexedDB remain in the persistent profile itself.
    """
    path = config.root / 'data/storage_state.json'
    if not path.exists():
        return
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        current = {(c['name'], c['domain'], c['path']) for c in await context.cookies()}
        missing = []
        for cookie in state.get('cookies', []):
            key = (cookie['name'], cookie['domain'], cookie['path'])
            if (key not in current and cookie.get('expires') == -1
                    and merchant_url('https://' + cookie['domain'].lstrip('.'))):
                missing.append(cookie)
        if missing:
            await context.add_cookies(missing)
            LOG.info('Previous merchant session cookies restored; server validity will be checked via UI.')
    except (ValueError, KeyError, TypeError, OSError, Error):
        LOG.warning('Session-cookie backup could not be restored; normal login may be required.')


@asynccontextmanager
async def persistent_browser(config: Config) -> AsyncIterator[tuple[BrowserContext, Page]]:
    """Keep cookies/local storage in an isolated profile, export state on exit."""
    config.user_data_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.user_data_dir), headless=config.headless,
            viewport={'width': 1360, 'height': 900})
        context.set_default_timeout(config.timeout_ms)
        context.set_default_navigation_timeout(config.timeout_ms * 2)
        LOG.info('Browser started.')
        try:
            await restore_session_cookies(context, config)
            page = context.pages[0] if context.pages else await context.new_page()
            yield context, page
        finally:
            try:
                await save_session(context, config)
            finally:
                await context.close()
