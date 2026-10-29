"""Human interaction ports; retailer code does not know Telegram objects."""
from typing import Protocol


class InteractionPort(Protocol):
    async def request_national_id(self) -> str: ...
    async def request_otp(self) -> str: ...
    async def request_manual_action(self, reason: str) -> None: ...


class NotificationPort(Protocol):
    async def publish(self, event: str) -> None: ...
    async def payment(self, url: str) -> None: ...


class TerminalInteraction:
    async def request_national_id(self) -> str:
        from kavirtire.ui import terminal
        return await terminal('کد ملی ده‌رقمی را وارد کنید: ')

    async def request_otp(self) -> str:
        from kavirtire.ui import terminal
        return await terminal('کد پیامک را با حفظ بزرگی حروف وارد کنید: ')

    async def request_manual_action(self, reason: str) -> None:
        from kavirtire.ui import terminal
        from kavirtire.diagnostics import LOG
        LOG.warning('Manual action required: %s', reason)
        await terminal('مرحله را در مرورگر بررسی/تکمیل کنید؛ سفارش تازه نسازید. سپس Enter بزنید: ')
