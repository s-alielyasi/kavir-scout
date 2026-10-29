"""Pause for site protections; never solve or bypass them."""
from playwright.async_api import Page, Response
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from kavirtire import selectors as S
from kavirtire.diagnostics import LOG
from kavirtire.security import merchant_url
from kavirtire.errors import SafetyError
from kavirtire.interactions import InteractionPort, TerminalInteraction
from kavirtire.ui import has_text, terminal, settle


class HumanGuard:
    def __init__(self, page: Page, interactions: InteractionPort | None = None):
        self.page = page
        self.interactions = interactions or TerminalInteraction()
        self.blocked_status: int | None = None
        self.blocked_request: str | None = None
        self.retry_after = 0.0
        page.on('response', self.observe_response)

    def observe_response(self, response: Response) -> None:
        if merchant_url(response.url) and response.request.resource_type in ('document', 'xhr', 'fetch'):
            if response.status in (403, 429):
                self.blocked_status = response.status
                self.blocked_request = response.url
                raw = response.headers.get('retry-after', '')
                try:
                    seconds = float(raw)
                except ValueError:
                    try:
                        seconds = (parsedate_to_datetime(raw)-datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        seconds = 0
                self.retry_after = asyncio.get_running_loop().time() + max(0, seconds)
            elif (200 <= response.status < 300 and response.url == self.blocked_request
                  and asyncio.get_running_loop().time() >= self.retry_after):
                self.blocked_status = None
                self.blocked_request = None

    async def blocked(self) -> bool:
        if self.page.url != 'about:blank' and not merchant_url(self.page.url):
            raise SafetyError('External page: merchant DOM inspection refused.')
        for selector in S.PROTECTION_WIDGETS:
            loc = self.page.locator(selector)
            if await loc.count():
                return True
        return self.blocked_status is not None or await has_text(self.page, S.PROTECTION_TEXT)

    async def check(self) -> bool:
        """Return whether a human intervention occurred; callers must re-query UI."""
        handled = False
        while await self.blocked():
            handled = True
            LOG.warning('CAPTCHA / queue / rate limit / access restriction detected. '
                        'Automation paused; complete or wait through it in the browser.')
            await self.interactions.request_manual_action('site_protection')
            await settle(self.page)
        return handled
