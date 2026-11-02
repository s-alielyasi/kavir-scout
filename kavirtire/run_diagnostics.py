"""Shareable structured evidence, without exception payloads, credentials or DOM text."""
from contextvars import ContextVar
import asyncio
from datetime import datetime, timezone
from functools import wraps
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time
import traceback

from kavirtire.orchestration.scheduling import TEHRAN
from kavirtire.security import merchant_url, safe_url

CURRENT = ContextVar('kavir_diagnostics', default=None)


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        descriptor = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        if os.name != 'nt':
            os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, self.mode, encoding=self.encoding, errors=self.errors)


class RunDiagnostics:
    def __init__(self, root: Path, run_id: str | None = None):
        self.root, self.run_id, self.page = root, run_id, None

    def event(self, event: str, **details):
        try:
            self._write(event, details)
        except OSError:
            logging.getLogger('kavir').warning('Diagnostic file unavailable; check disk space and permissions. Payload omitted.')

    def _write(self, event: str, details: dict):
        folder = self.root / 'logs/diagnostics'
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = folder / 'workflow.jsonl'
        # Only fixed schema fields chosen by the caller, never arbitrary payloads.
        record = {'time_tehran': datetime.now(TEHRAN).isoformat(),
                  'time_utc': datetime.now(timezone.utc).isoformat(),
                  'run_id': self.run_id, 'event': event, **details}
        # Open per record so tests/short-lived runs do not leak file descriptors.
        handler = PrivateRotatingFileHandler(path, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
        try:
            if os.name != 'nt':
                path.chmod(0o600)
            handler.emit(logging.LogRecord('diagnostics', logging.INFO, '', 0,
                json.dumps(record, ensure_ascii=False), (), None))
        finally:
            handler.close()

    def error(self, operation: str, error: BaseException):
        frames = []
        for frame in traceback.extract_tb(error.__traceback__):
            path = Path(frame.filename)
            try:
                name = str(path.relative_to(self.root))
            except ValueError:
                name = path.name
            frames.append({'file': name, 'line': frame.lineno, 'function': frame.name})
        self.event('exception', operation=operation, error_type=type(error).__name__,
                   frames=frames, payload='omitted: may contain credentials or payment data')

    async def capture(self, reason: str):
        from kavirtire import selectors as selectors
        page = self.page
        if page is None or page.is_closed():
            self.event('page_evidence', reason=reason, available=False)
            return
        if not merchant_url(page.url):
            self.event('page_evidence', reason=reason, surface='external', dom_inspected=False)
            return
        try:
            # No values, HTML, screenshots, cookies, text, labels, arbitrary
            # attributes, or network bodies. Bank DOM is never inspected.
            async with asyncio.timeout(2):
                evidence = await page.evaluate('''(selectors) => {
                if (location.protocol !== 'https:' || !(location.hostname === 'kavirtire.ir' || location.hostname.endsWith('.kavirtire.ir'))) return null;
                return ({
                ready_state: document.readyState,
                controls: [...document.querySelectorAll('input,select,button')].slice(0,100).map(el => ({
                    tag: el.tagName, type: ['text','password','number','tel','email','hidden','checkbox','radio','submit','button'].includes(el.type) ? el.type : 'other',
                    visible: !!el.getClientRects().length, disabled: !!el.disabled,
                    required: !!el.required, invalid: el.getAttribute('aria-invalid') === 'true'
                })),
                products: document.querySelectorAll('.product').length,
                refresh_present: !!document.querySelector('#refresh-availability'),
                refresh_disabled: !!document.querySelector('#refresh-availability:disabled'),
                otp_present: !!document.querySelector('#code-verification,[autocomplete="one-time-code"]'),
                selector_counts: selectors.map(selector => {
                    try { return {selector, count: document.querySelectorAll(selector).length}; }
                    catch (_) { return {selector, unsupported: true}; }
                })
            }); }''', list(dict.fromkeys(selectors.NATIONAL_ID_CSS + selectors.OTP_CSS
                + selectors.PRODUCT_CONTAINERS + selectors.ORDER_CONTAINERS + selectors.QUANTITY_CSS)))
            self.event('page_evidence', reason=reason, origin=safe_url(page.url), evidence=evidence)
        except Exception as error:
            self.error('page_evidence', error)


def diagnostic_step(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        diagnostic = CURRENT.get()
        if diagnostic is None:
            return await function(*args, **kwargs)
        operation = function.__qualname__
        started = time.monotonic()
        diagnostic.event('operation_started', operation=operation)
        try:
            result = await function(*args, **kwargs)
        except asyncio.CancelledError:
            diagnostic.event('operation_cancelled', operation=operation)
            raise
        except Exception as error:
            diagnostic.error(operation, error)
            await diagnostic.capture(operation)
            raise
        diagnostic.event('operation_completed', operation=operation,
                         elapsed_ms=round((time.monotonic()-started)*1000))
        return result
    return wrapped
