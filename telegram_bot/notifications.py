"""Allowlisted messages and a dedicated private payment sink; no URL logging."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.error import RetryAfter, TelegramError
from kavirtire.security import gateway_url

EVENTS = {
    'login_reminder': 'یادآوری ورود: اجرای امروز فعال است و ورود هنوز کامل نشده است.',
    'requested_quantity_disallowed': 'تعداد درخواستی با سقف مشاهده‌شدهٔ سایت سازگار نیست. حالت مشاهده ادامه دارد و هیچ انتخاب یا سفارشی انجام نمی‌شود.',
    'dry_run_target_found': 'DRY RUN\nمحصول هدف پیدا شد. انتخاب محصول و ثبت سفارش انجام نشد.',
    'sale_window_ended': 'بازهٔ پایش امروز پایان یافت؛ بررسی یا سفارش تازه‌ای آغاز نمی‌شود.',
    'payment_handoff_sent': 'لینک پرداخت تحویل شد؛ این پیام به معنی تأیید پرداخت نیست.',
    'cancelled': 'اجرای خودکار متوقف و منابع آن آزاد شدند.',
    'cancelled_order_may_exist': 'اجرای خودکار متوقف شد. سفارش ممکن است ثبت شده باشد؛ سفارش‌های سایت را بررسی کنید.',
    'order_requires_reconciliation': 'نتیجهٔ سفارش نیازمند بررسی دستی است. تلاش تازه تا تعیین تکلیف محلی مسدود است.',
    'clock_inconsistent': 'ساعت یا تاریخ ناسازگار تشخیص داده شد؛ اجرا متوقف شد.',
    'workflow_failed': 'اجرا متوقف شد؛ وضعیت و راهنمای محلی را بررسی کنید.',
    'deletion_unavailable': 'حذف پیام ورودی ممکن نشد؛ آن را در تلگرام بررسی کنید.',
}


class DeliveryFailure(RuntimeError):
    def __init__(self, retry_after=2):
        super().__init__('Telegram delivery unavailable.')
        self.retry_after = retry_after


class TelegramNotifications:
    def __init__(self, bot, settings):
        self.bot, self.settings = bot, settings

    async def send(self, text: str, *, protect_content: bool = False, **kwargs):
        try:
            return await self.bot.send_message(chat_id=self.settings.allowed_chat_id, text=text,
                protect_content=protect_content, link_preview_options=LinkPreviewOptions(is_disabled=True), **kwargs)
        except RetryAfter as error:
            raise DeliveryFailure(error.retry_after) from None
        except TelegramError:
            raise DeliveryFailure() from None

    async def publish(self, event: str) -> None:
        await self.send(EVENTS.get(event, 'اجرای امروز پایان یافت؛ /status را بررسی کنید.'))

    async def payment(self, url: str) -> None:
        if not gateway_url(url, self.settings.retailer.gateway_hosts):
            raise ValueError('Unrecognized payment origin.')
        markup = InlineKeyboardMarkup([[InlineKeyboardButton('💳 پرداخت سفارش', url=url)]])
        await self.send('درگاه سفارش آماده است. پرداخت را شخصاً انجام دهید. ممکن است لینک فقط در مرورگر اصلی کار کند.',
                        protect_content=True, reply_markup=markup)
