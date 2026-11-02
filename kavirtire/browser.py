"""Persistent Chromium lifecycle; profile-bound, cookie-only optional backup."""
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Awaitable, Callable
import json
import os
from pathlib import Path
import tempfile
from typing import TypeVar
from playwright.async_api import BrowserContext, Error, Page, async_playwright
from config import Config
from kavirtire.diagnostics import LOG
from kavirtire.errors import BotError, SafetyError
from kavirtire.security import merchant_url, gateway_url

T = TypeVar('T')


async def retry_navigation(action: Callable[[], Awaitable[T]], attempts: int) -> T:
    for attempt in range(attempts):
        try:
            return await action()
        except Error:
            LOG.warning('Navigation failed (%s/%s).', attempt + 1, attempts)
            if attempt + 1 == attempts:
                raise BotError('Navigation failed after bounded retries.') from None
    raise AssertionError('attempts must be positive')


def session_path(config: Config) -> Path:
    return config.user_data_dir / '.kavir-session.json'


async def save_session(context: BrowserContext, config: Config) -> None:
    if not config.session_backup:
        return
    path = session_path(config)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        # Do not snapshot merchant origins or inspect payment-page storage.
        cookies = [c for c in await context.cookies()
                   if merchant_url('https://' + c['domain'].lstrip('.'))]
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.session-')
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump({'cookies': cookies}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        LOG.info('Profile-bound merchant cookie backup saved.')
    except (Error, OSError):
        LOG.warning('Cookie backup unavailable; previous backup/profile preserved where possible.')
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


async def restore_session_cookies(context: BrowserContext, config: Config) -> None:
    if not config.session_backup:
        return
    path = session_path(config)
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
            LOG.info('Profile session cookies restored; account confirmation still required.')
    except (ValueError, KeyError, TypeError, OSError, Error):
        LOG.warning('Cookie backup could not be restored; normal login may be required.')


@asynccontextmanager
async def persistent_browser(config: Config) -> AsyncIterator[tuple[BrowserContext, Page]]:
    config.user_data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.user_data_dir), headless=config.headless,
            channel=config.browser_channel,
            args=['--no-proxy-server'] if config.browser_direct_connection else [],
            viewport={'width': 1360, 'height': 900})
        context.set_default_timeout(config.timeout_ms)
        context.set_default_navigation_timeout(config.timeout_ms * 2)
        try:
            if any(gateway_url(p.url, config.gateway_hosts) for p in context.pages):
                raise SafetyError('An existing payment tab requires reconciliation before a new run.')
            await restore_session_cookies(context, config)
            page = next((p for p in context.pages if merchant_url(p.url) or p.url == 'about:blank'), None)
            if page is None:
                page = await context.new_page()
            yield context, page
        finally:
            async def cleanup():
                try:
                    await asyncio.wait_for(save_session(context, config), timeout=5)
                finally:
                    await asyncio.wait_for(context.close(), timeout=10)
            task = asyncio.create_task(cleanup())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.shield(task)
                raise
