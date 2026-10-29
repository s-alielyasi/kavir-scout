"""Normal site login with short-lived credentials and transport-neutral prompts."""
import asyncio
from playwright.async_api import Page, TimeoutError, Error
from config import Config
from kavirtire import selectors as S
from kavirtire.browser import save_session
from kavirtire.diagnostics import LOG
from kavirtire.errors import AmbiguousElement
from kavirtire.guard import HumanGuard
from kavirtire.interactions import InteractionPort
from kavirtire.orchestration.input_broker import normalize_credential
from kavirtire.security import SecretFilter, merchant_url
from kavirtire.text import text_pattern
from kavirtire.ui import button, field, has_text, settle, unique_visible


class Login:
    def __init__(self, page: Page, config: Config, guard: HumanGuard, secrets: SecretFilter,
                 interactions: InteractionPort | None = None):
        self.page, self.config, self.guard, self.secrets = page, config, guard, secrets
        self.interactions = interactions or guard.interactions

    async def login_form_visible(self) -> bool:
        if await field(self.page, S.NATIONAL_ID_LABELS, S.NATIONAL_ID_CSS):
            return True
        if await field(self.page, S.OTP_LABELS, S.OTP_CSS):
            return True
        if await self.page.locator(S.OTP_SPLIT + ':visible').count():
            return True
        terms = await button(self.page, S.LOGIN)
        return bool(terms and not await has_text(self.page, S.PROFILE_SIGNALS))

    async def is_logged_in(self) -> bool:
        if await self.login_form_visible():
            return False
        profile = await has_text(self.page, S.PROFILE_SIGNALS)
        shop = await button(self.page, S.SHOP)
        refresh = await button(self.page, S.REFRESH)
        return bool((profile and shop) or refresh)

    async def manual(self, reason: str) -> None:
        # Auth/profile dumps are deliberately disabled, even in CLI mode.
        await self.interactions.request_manual_action(reason)
        await settle(self.page)

    async def accept_terms(self) -> bool:
        checks = [self.page.locator(S.LOGIN_TERMS_CSS)]
        checks += [self.page.get_by_role('checkbox', name=text_pattern(t)) for t in S.TERMS]
        checkbox = await unique_visible(checks)
        if checkbox:
            await checkbox.check()
        enter = await button(self.page, S.LOGIN)
        if enter and await enter.is_enabled():
            await enter.click()
            await settle(self.page)
            return True
        return False

    async def await_auth_response(self, submitted: str) -> None:
        """A slow AJAX response is never permission to request SMS/code again."""
        deadline = asyncio.get_running_loop().time() + self.config.timeout_ms / 1000
        while asyncio.get_running_loop().time() < deadline:
            await self.guard.check()
            if await self.is_logged_in():
                return
            if submitted == 'national_id' and (
                    await field(self.page, S.OTP_LABELS, S.OTP_CSS)
                    or await self.page.locator(S.OTP_SPLIT + ':visible').count()):
                return
            if await has_text(self.page, S.AUTH_REJECTION):
                if submitted == 'otp':
                    await self.manual('otp_rejected_or_expired')
                return
            await asyncio.sleep(0.1)
        await self.manual('authentication_response_uncertain')

    async def submit_national_id(self, national_id: str | None = None) -> bool:
        target = await field(self.page, S.NATIONAL_ID_LABELS, S.NATIONAL_ID_CSS)
        if not target:
            return False
        if national_id is None:
            national_id = await self.interactions.request_national_id()
        try:
            national_id = normalize_credential('national_id', national_id)
        except ValueError:
            national_id = ''
            await self.manual('national_id_format')
            return True
        try:
            with self.secrets.register(national_id):
                await target.fill(national_id)
                national_id = ''
            if await self.guard.check():
                return True
            submit = await button(self.page, S.LOGIN_NEXT + S.LOGIN_ID_SUBMIT)
            if not submit or not await submit.is_enabled():
                await self.manual('national_id_submission')
                return True
            await submit.click()  # never retried automatically
            LOG.info('Identity submitted; waiting for site response.')
            await self.await_auth_response('national_id')
        finally:
            national_id = ''
            await self.scrub(target)
        return True

    async def scrub(self, target) -> None:
        if self.page.url != 'about:blank' and not merchant_url(self.page.url):
            return
        try:
            if await target.count() == 1 and await target.is_visible() and await target.is_editable():
                await target.fill('')
        except Error:
            pass

    async def submit_otp(self) -> bool:
        target = await field(self.page, S.OTP_LABELS, S.OTP_CSS)
        split = self.page.locator(S.OTP_SPLIT + ':visible')
        split_count = await split.count()
        if not target and not split_count:
            return False
        await self.guard.check()
        otp = await self.interactions.request_otp()
        try:
            otp = normalize_credential('otp', otp)
        except ValueError:
            return True  # request a fresh value without echoing the invalid one
        try:
            if await self.guard.blocked():
                otp = ''
                await self.guard.check()
                return True
            if split_count and not target and split_count != len(otp):
                otp = ''
                await self.manual('otp_form_changed')
                return True
            with self.secrets.register(otp):
                if split_count and not target:
                    for index, char in enumerate(otp):
                        await split.nth(index).fill(char)
                    char = ''
                else:
                    await target.fill(otp)
                otp = ''
            if not await self.is_logged_in():
                submit = await button(self.page, S.OTP_SUBMIT)
                if submit and await submit.is_enabled():
                    await submit.click()
                elif not split_count:
                    await self.manual('otp_submission')
                    return True
            await self.await_auth_response('otp')
        finally:
            otp = ''
            if target:
                await self.scrub(target)
            elif self.page.url == 'about:blank' or merchant_url(self.page.url):
                for index in range(await split.count()):
                    await self.scrub(split.nth(index))
        return True

    async def ensure(self, national_id: str | None = None) -> None:
        if await self.guard.blocked():
            national_id = None
        await self.guard.check()
        if await self.is_logged_in():
            # There is no verified live account-ID selector. The owner must
            # confirm the current account instead of silently trusting a cookie.
            national_id = ''
            await self.manual('confirm_current_account')
            if not await self.is_logged_in():
                return await self.ensure()
            LOG.info('Existing account confirmed; login skipped.')
            return
        id_submitted = False
        terms_clicked = False
        try:
            while not await self.is_logged_in():
                await self.guard.check()
                try:
                    if await self.submit_otp():
                        continue
                    if await field(self.page, S.NATIONAL_ID_LABELS, S.NATIONAL_ID_CSS):
                        if not id_submitted:
                            submission = self.submit_national_id(national_id)
                            national_id = None
                            await submission
                            submission = None
                            id_submitted = True
                        else:
                            await self.manual('identity_response_uncertain')
                            id_submitted = False
                        continue
                    if not terms_clicked and await self.accept_terms():
                        terms_clicked = True
                        continue
                    await self.manual('authentication_page_unknown')
                    id_submitted = False
                except (AmbiguousElement, TimeoutError):
                    await self.manual('authentication_controls_changed')
        finally:
            national_id = ''
        LOG.info('Login successful.')
        await save_session(self.page.context, self.config)
