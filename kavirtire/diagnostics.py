"""Console/file logging and best-effort sanitized debug artifacts."""
from datetime import datetime
import logging
from pathlib import Path
import re
from playwright.async_api import Page, Error
from kavirtire import selectors as S
from kavirtire.security import SecretFilter, safe_url, merchant_url

LOG = logging.getLogger('kavir')


def setup_logging(root: Path, secrets: SecretFilter, *, tehran: bool = False) -> None:
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    class TehranFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            from kavirtire.orchestration.scheduling import TEHRAN
            return datetime.fromtimestamp(record.created, TEHRAN).strftime('%Y-%m-%d %H:%M:%S %Z')
    formatter = (TehranFormatter('[%(asctime)s] %(message)s') if tehran else
                 logging.Formatter('[%(asctime)s] %(message)s', '%H:%M:%S'))
    for handler in (logging.StreamHandler(), logging.FileHandler(
            root / 'logs/kavirtire.log', encoding='utf-8')):
        handler.setFormatter(formatter)
        handler.addFilter(secrets)
        LOG.addHandler(handler)


async def capture_debug(page: Page, root: Path, secrets: SecretFilter,
                        label: str = 'error') -> None:
    """Mask controls, known secrets and numeric identity text before persistence.

    Artifacts can still contain names/addresses. Keep them local and inspect
    before sharing. Never call on a gateway page.
    """
    if page.is_closed() or (page.url != 'about:blank' and not merchant_url(page.url)):
        return
    folder = root / 'debug'
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / f'{datetime.now():%Y%m%d_%H%M%S_%f}_{label}'
    try:
        title = secrets.redact(await page.title())
        LOG.error('Unexpected state; URL=%s; title=%s', safe_url(page.url), title)
        masks = [page.locator(S.SENSITIVE_FIELDS), page.get_by_text(re.compile(r'[\d۰-۹٠-٩]{4,}'))]
        masks += [page.get_by_text(secret, exact=False) for secret in secrets.secrets if secret]
        await page.screenshot(path=str(stem.with_suffix('.png')), full_page=True,
                              mask=masks, timeout=10000)
        html = await page.evaluate(S.SANITIZE_HTML_JS)
        html = secrets.redact(html)
        html = re.sub(r'[\d۰-۹٠-٩]{4,}', '[REDACTED]', html)
        stem.with_suffix('.html').write_text(html, encoding='utf-8')
        LOG.info('Sanitized debug artifacts saved under debug/.')
    except Error:
        LOG.warning('Could not capture all debug artifacts (page changed or closed).')
