"""Strict semantic lookup, cancellable terminal input and DOM readiness."""
import asyncio
import re
import threading
from collections.abc import Iterable
from playwright.async_api import Locator, Page, expect
from kavirtire.errors import AmbiguousElement, SafetyError
from kavirtire.text import text_pattern

Scope = Page | Locator


def require_merchant(scope: Scope) -> None:
    from kavirtire.security import merchant_url
    page = scope.page if isinstance(scope, Locator) else scope
    if page.url != 'about:blank' and not merchant_url(page.url):
        raise SafetyError('Merchant DOM operation refused on an external page.')


async def unique_visible(candidates: Iterable[Locator]) -> Locator | None:
    """Try strategies in order; never silently choose among visible duplicates."""
    for group in candidates:
        visible = []
        for i in range(await group.count()):
            item = group.nth(i)
            if await item.is_visible():
                visible.append(item)
        if len(visible) > 1:
            raise AmbiguousElement('Multiple matching controls; complete this step manually.')
        if visible:
            return visible[0]
    return None


async def button(scope: Scope, texts: tuple[str, ...]) -> Locator | None:
    require_merchant(scope)
    return await unique_visible(scope.get_by_role(role, name=re.compile(
                                    r'^[\s\u200c\u200d\ue000-\uf8ff]*' + text_pattern(text).pattern
                                    + r'[\s\u200c\u200d\ue000-\uf8ff]*$', re.I))
                                for text in texts for role in ('button', 'link'))


async def field(scope: Scope, labels: tuple[str, ...], css: tuple[str, ...]) -> Locator | None:
    require_merchant(scope)
    groups = [scope.get_by_label(text_pattern(label)) for label in labels]
    groups += [scope.get_by_placeholder(text_pattern(label)) for label in labels]
    groups += [scope.locator(selector) for selector in css]
    return await unique_visible(groups)


async def has_text(scope: Scope, texts: tuple[str, ...]) -> bool:
    require_merchant(scope)
    for text in texts:
        loc = scope.get_by_text(text_pattern(text))
        for i in range(await loc.count()):
            if await loc.nth(i).is_visible():
                return True
    return False


async def terminal(prompt: str) -> str:
    """Use input() without blocking Playwright or making Ctrl+C wait on stdin."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()

    def deliver(value: str | BaseException) -> None:
        if not future.done():
            if isinstance(value, BaseException):
                future.set_exception(value)
            else:
                future.set_result(value)

    def read() -> None:
        try:
            result: str | BaseException = input(prompt)
        except (EOFError, KeyboardInterrupt) as error:
            result = error
        try:
            loop.call_soon_threadsafe(deliver, result)
        except RuntimeError:
            pass  # loop already closed following Ctrl+C

    threading.Thread(target=read, daemon=True).start()
    return await future


async def settle(page: Page) -> None:
    """Wait for navigation and two rendering frames, without networkidle guesses."""
    await page.wait_for_load_state('domcontentloaded')
    from kavirtire.security import merchant_url
    if page.url != 'about:blank' and not merchant_url(page.url):
        return
    await page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


async def wait_loading(page: Page, timeout_ms: int) -> None:
    require_merchant(page)
    from kavirtire import selectors as S
    await expect(page.locator(S.LOADING)).to_have_count(0, timeout=timeout_ms)
