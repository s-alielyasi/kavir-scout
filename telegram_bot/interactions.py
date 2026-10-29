"""Correlated private prompts; only the broker briefly holds accepted values."""
from telegram import ForceReply
from telegram_bot.notifications import TelegramNotifications

MANUAL = {
    'otp_rejected_or_expired': 'کد رد یا منقضی شده است. فرم را بررسی کنید و در صورت نیاز فقط از دکمهٔ عادی ارسال مجدد سایت وقتی فعال است استفاده کنید. پس از ادامه، کد فعلی دوباره درخواست می‌شود.',
    'confirm_current_account': 'حساب بازشده در مرورگر را با هویت موردنظر تطبیق دهید. فقط پس از تطبیق ادامه دهید؛ در صورت مغایرت /cancel بزنید.',
    'site_protection': 'مرحله امنیتی، صف یا محدودیت سایت را در مرورگر بررسی کنید و زمان انتظار آن را رعایت کنید.',
    'inventory_cooldown': 'دکمه موجودی هنوز آماده نیست؛ منتظر پایان زمان انتظار سایت بمانید.',
    'checkout_reconciliation': 'سفارش فعلی را در مرورگر بررسی/تکمیل کنید؛ سفارش تازه نسازید.',
    'payment_delivery_retry': 'تحویل لینک ناموفق بود. ادامه فقط ارسال همان لینک را تکرار می‌کند.',
}


class TelegramInteractions:
    def __init__(self, bot, controller):
        self.controller = controller
        self.notifications = TelegramNotifications(bot, controller.settings)

    async def _request(self, kind: str, text: str) -> str:
        broker = self.controller.broker
        request = broker.open(kind, self.controller.run_id, self.controller.input_deadline())
        if kind == 'manual':
            text += '\nبرای ادامه به همین پیام /resume پاسخ دهید یا بنویسید:\n/resume ' + request.request_id
        try:
            message = await self.notifications.send(text, reply_markup=ForceReply(selective=True))
            broker.bind_prompt(request.request_id, message.message_id)
            message = None
            return await broker.wait(request.request_id)
        finally:
            if broker.pending and broker.pending.request_id == request.request_id:
                broker.cancel()

    async def request_national_id(self) -> str:
        return await self._request('national_id',
            'کد ملی ده‌رقمی را در پاسخ به همین پیام بفرستید. پیام پس از دریافت در حد امکان حذف می‌شود؛ تلگرام محل ورود کاملاً محرمانه یا سرتاسری نیست.')

    async def request_otp(self) -> str:
        return await self._request('otp',
            'کد فعلی پیامک را با حفظ بزرگی حروف در پاسخ به همین پیام بفرستید. کد قبلی یا پاسخ به پیام دیگر پذیرفته نمی‌شود.')

    async def request_manual_action(self, reason: str) -> None:
        await self._request('manual', MANUAL.get(reason, 'مرحله جاری را در مرورگر بررسی/تکمیل کنید؛ از ثبت سفارش تازه خودداری کنید.'))
