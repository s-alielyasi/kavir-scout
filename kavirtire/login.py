"""DOM-based session recognition and terminal-assisted login."""
import re
from playwright.async_api import Page, TimeoutError
from config import Config
from kavirtire import selectors as S
from kavirtire.browser import save_session
from kavirtire.diagnostics import LOG, capture_debug
from kavirtire.errors import AmbiguousElement, BotError
from kavirtire.guard import HumanGuard
from kavirtire.security import SecretFilter
from kavirtire.text import normalize_text, text_pattern
from kavirtire.ui import button, field, has_text, settle, terminal, unique_visible


class Login:
    def __init__(self, page: Page, config: Config, guard: HumanGuard, secrets: SecretFilter):
        self.page, self.config, self.guard, self.secrets = page, config, guard, secrets

    async def login_form_visible(self) -> bool:
        """A URL alone never establishes session expiration."""
        if await field(self.page, S.NATIONAL_ID_LABELS, S.NATIONAL_ID_CSS):
            return True
        if await field(self.page, S.OTP_LABELS, S.OTP_CSS):
            return True
        split = self.page.locator(S.OTP_SPLIT)
        if await split.count() and await split.first.is_visible():
            return True
        terms = await button(self.page, S.LOGIN)
        return bool(terms and not await has_text(self.page, S.PROFILE_SIGNALS))

    async def is_logged_in(self) -> bool:
        """Require positive account/shop DOM evidence, with no visible login form."""
        if await self.login_form_visible():
            return False
        profile = await has_text(self.page, S.PROFILE_SIGNALS)
        shop = await button(self.page, S.SHOP)
        refresh = await button(self.page, S.REFRESH)
        # An authenticated inventory UI is also positive session evidence.
        return bool((profile and shop) or refresh)

    async def manual(self, message: str) -> None:
        LOG.warning(message)
        await capture_debug(self.page, self.config.root, self.secrets, 'login')
        await terminal('این مرحله ورود را در مرورگر انجام دهید و سپس Enter بزنید: ')
        await settle(self.page)

    async def accept_terms(self) -> bool:
        """Accept only visibly labelled, ordinary login terms checkboxes."""
        checks = [self.page.locator(S.LOGIN_TERMS_CSS)]
        checks += [self.page.get_by_role('checkbox', name=text_pattern(t)) for t in S.TERMS]
        checkbox = await unique_visible(checks)
        if checkbox:
            await checkbox.check()
            LOG.info('Accepting login terms...')
        enter = await button(self.page, S.LOGIN)
        if enter and await enter.is_enabled():
            await enter.click()
            await settle(self.page)
            return True
        return False

    async def submit_national_id(self) -> bool:
        target = await field(self.page, S.NATIONAL_ID_LABELS, S.NATIONAL_ID_CSS)
        if not target:
            return False
        if not self.config.national_id:
            await self.manual('NATIONAL_ID is empty; enter your ID manually in the browser.')
            return True
        await target.fill(self.config.national_id)
        if await self.guard.check():
            return True  # human may already have submitted this step
        submit = await button(self.page, S.LOGIN_NEXT + S.LOGIN_ID_SUBMIT)
        if not submit or not await submit.is_enabled():
            await self.manual('National ID form could not be submitted safely.')
            return True
        await submit.click()  # SMS request is not retried automatically
        LOG.info('National ID submitted. SMS verification code requested.')
        await settle(self.page)
        return True

    async def submit_otp(self) -> bool:
        target = await field(self.page, S.OTP_LABELS, S.OTP_CSS)
        split = self.page.locator(S.OTP_SPLIT)
        split_count = await split.count()
        if not target and not (split_count and await split.first.is_visible()):
            return False
        LOG.info('Waiting for OTP (never logged or saved).')
        otp = normalize_text(await terminal('کد تایید پیامک‌شده را وارد کنید: ')).replace(' ', '')
        if not re.fullmatch(S.OTP_VALUE_PATTERN, otp):
            LOG.warning('Enter the SMS code exactly, preserving letter case (8 characters on the live site).')
            return True
        self.secrets.secrets.append(otp)
        if split_count and not target:
            if split_count != len(otp):
                LOG.warning('OTP length does not match the visible code fields.')
                return True
            for index, char in enumerate(otp):
                await split.nth(index).fill(char)
        else:
            await target.fill(otp)
        otp = ''
        if await self.is_logged_in():  # split boxes can submit automatically
            return True
        submit = await button(self.page, S.OTP_SUBMIT)
        if submit and await submit.is_enabled():
            await submit.click()
            await settle(self.page)
        else:
            await self.manual('Complete verification manually in the browser.')
        return True

    async def ensure(self) -> None:
        """Keep human-required steps alive; only return after positive login evidence."""
        await self.guard.check()
        if await self.is_logged_in():
            LOG.info('Session found. Skipping login...')
            return
        LOG.info('Login required.')
        id_submitted = False
        terms_clicked = False
        while not await self.is_logged_in():
            await self.guard.check()
            try:
                if await self.submit_otp():
                    continue
                if await field(self.page, S.NATIONAL_ID_LABELS, S.NATIONAL_ID_CSS):
                    if not id_submitted:
                        await self.submit_national_id()
                        id_submitted = True
                    else:
                        await self.manual('ID submission not completed. Inspect validation or wait for the OTP page.')
                    continue
                if not terms_clicked and await self.accept_terms():
                    terms_clicked = True
                    continue
                await self.manual('Login state unknown or form rejected. Please complete the current step.')
                id_submitted = False  # explicit human intervention permits a new attempt
            except (AmbiguousElement, TimeoutError):
                await self.manual('Login controls changed or are ambiguous; manual action required.')
        LOG.info('Login successful.')
        await save_session(self.page.context, self.config)
