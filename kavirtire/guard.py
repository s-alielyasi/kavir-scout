"""Pause for site protections; never solve or bypass them."""
from playwright.async_api import Page, Response
from kavirtire import selectors as S
from kavirtire.diagnostics import LOG
from kavirtire.security import merchant_url
from kavirtire.ui import has_text, terminal, settle


class HumanGuard:
    def __init__(self, page: Page):
        self.page = page
        self.blocked_status: int | None = None
        page.on('response', self.observe_response)

    def observe_response(self, response: Response) -> None:
        if merchant_url(response.url) and response.request.resource_type in ('document', 'xhr', 'fetch'):
            if response.status in (403, 429):
                self.blocked_status = response.status

    async def blocked(self) -> bool:
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
            await terminal('مرحله امنیتی/صف را در مرورگر دستی انجام دهید؛ پس از رفع آن Enter بزنید: ')
            self.blocked_status = None
            await settle(self.page)
        return handled
