"""Short handlers: authorize, signal the owner task and return."""
from collections import deque
from datetime import datetime, timedelta, timezone
from telegram import ForceReply
from telegram.ext import ApplicationHandlerStop
from kavirtire.orchestration.input_broker import normalize_credential
from telegram_bot.authorization import authorized
from telegram_bot.notifications import TelegramNotifications

RECEIPTS = {
    'armed': 'اجرای امروز فعال شد. ورودی بعدی را در پاسخ به پیام خودش بفرستید.',
    'inventory_test_started': 'تست یک‌بارهٔ ورود و موجودی شروع شد؛ مستقل از ساعت و بدون سفارش است. ورودی را در پاسخ به پیام خودش بفرستید.',
    'test_requires_dry_run': 'تست موجودی فقط با DRY_RUN=true قابل اجراست؛ تنظیم محلی را بررسی کنید.',
    'already_active': 'یک اجرا از قبل فعال است؛ /status را ببینید.',
    'sale_window_ended': 'بازهٔ امروز پایان یافته است؛ مرورگر باز نشد.',
    'unresolved_order_attempt': 'تلاش سفارش قبلی تعیین تکلیف نشده است؛ راهنمای بازیابی محلی را بخوانید.',
    'cancellation_requested': 'درخواست توقف پذیرفته شد؛ پاک‌سازی در حال انجام است و نوبت خودکار امروز هم متوقف شد. /status همچنان در دسترس است.',
    'idle': 'اجرای فعالی وجود ندارد؛ نوبت خودکار امروز هم متوقف شد. برای شروع آگاهانه /arm بفرستید؛ فردا خودکار است.',
    'resume_requested': 'درخواست ادامه دریافت شد؛ وضعیت صفحه دوباره بررسی می‌شود.',
    'reply_to_current_checkpoint': 'به پیام مرحلهٔ فعلی /resume پاسخ دهید یا شناسهٔ فعلی را از /status بردارید.',
    'no_manual_checkpoint': 'مرحله‌ای برای ادامهٔ دستی وجود ندارد.',
}

STATES = {
    'IDLE': 'آمادهٔ دریافت دستور', 'WAITING_FOR_NATIONAL_ID': 'منتظر کد ملی',
    'CHECKING_SESSION': 'بررسی نشست', 'LOGIN_IN_PROGRESS': 'در حال ورود',
    'WAITING_FOR_OTP': 'منتظر کد پیامک', 'READY_FOR_SALE': 'آمادهٔ شروع بازهٔ فروش',
    'MONITORING': 'پایش موجودی', 'PRODUCT_FOUND': 'محصول پیدا شد', 'CHECKOUT': 'تکمیل سفارش',
    'WAITING_FOR_MANUAL_ACTION': 'منتظر اقدام دستی', 'PAYMENT_READY': 'آمادهٔ تحویل درگاه',
    'CANCELLING': 'در حال توقف و پاک‌سازی', 'COMPLETED': 'پایان‌یافته',
    'CANCELLED': 'متوقف‌شده', 'FAILED': 'نیازمند بررسی',
}


class Handlers:
    def __init__(self, controller, bot, *, started_at=None):
        self.controller, self.bot = controller, bot
        self.started_at = started_at or datetime.now(timezone.utc)
        self.notifications = TelegramNotifications(bot, controller.settings)
        self._seen = set()
        self._order = deque()
        self._identity_prompt = None

    async def gate(self, update, context):
        if not authorized(update, self.controller.owner, self.started_at):
            raise ApplicationHandlerStop

    def _admit(self, update):
        if not authorized(update, self.controller.owner, self.started_at) or update.update_id in self._seen:
            return False
        self._seen.add(update.update_id)
        self._order.append(update.update_id)
        if len(self._order) > 1024:
            self._seen.remove(self._order.popleft())
        return True

    async def start(self, update, context):
        if not self._admit(update):
            return
        config = self.controller.settings.retailer
        await self.notifications.send(
            f'دستیار کویرتایر\n{config.target_product} — {config.target_size} — تعداد {config.target_quantity}\n'
            f'حالت مشاهده: {"فعال" if self.controller.settings.dry_run else "غیرفعال"}\n'
            'زمان تهران: ۸:۰۰ تا ۸:۱۵؛ فاصله‌ها ۵، ۱۵ و ۳۰ ثانیه.\n'
            '/arm شروع یا تلاش مجدد امروز\n/status وضعیت\n/cancel توقف اجرا و نوبت خودکار امروز\n/resume ادامهٔ مرحلهٔ فعلی\n'
            '/set_national_id ثبت یا ویرایش کد ملی ذخیره‌شده\n'
            '/test_inventory تست یک‌بارهٔ ورود و موجودی، مستقل از ساعت و بدون سفارش\n'
            'ورود روزانه با کد ملی ذخیره‌شده به‌صورت خودکار در ساعت '
            f'{self.controller.settings.schedule.login:%H:%M} تهران آغاز می‌شود. سقف خرید سایت همیشه مقدم است.')
        try:
            registered = self.controller.profile.national_id() is not None
        except RuntimeError:
            registered = False
        if registered:
            await self.notifications.send('کد ملی قبلاً ذخیره شده است؛ برای تغییر /set_national_id بفرستید. ورود روزانه پس از راه‌اندازی مجدد نیز فعال می‌ماند.')
        else:
            await self._request_identity()

    async def _request_identity(self):
        self._identity_prompt = None
        if self.controller.active:
            await self.notifications.send('یک اجرا فعال است؛ برای ویرایش کد ملی ابتدا /cancel بفرستید و منتظر پایان اجرا بمانید.')
            return
        issued = datetime.now(timezone.utc)
        message = await self.notifications.send(
            'کد ملی ده‌رقمی را در پاسخ به همین پیام بفرستید. برای ورود خودکار روزانه در فایل خصوصی سرور ذخیره می‌شود؛ '
            'با /set_national_id می‌توانید آن را تغییر دهید. مهلت این پیام ده دقیقه است. پیام ورودی در حد امکان حذف می‌شود.',
            protect_content=True, reply_markup=ForceReply(selective=True))
        self._identity_prompt = (message.message_id, issued, issued + timedelta(minutes=10))

    async def set_national_id(self, update, context):
        if self._admit(update):
            await self._request_identity()

    async def _receipt(self, receipt):
        await self.notifications.send(RECEIPTS.get(receipt.reason, 'درخواست پذیرفته نشد؛ /status را بررسی کنید.'))

    async def arm(self, update, context):
        if self._admit(update):
            self._identity_prompt = None
            await self._receipt(await self.controller.arm(self.controller.owner))

    async def test_inventory(self, update, context):
        if self._admit(update):
            self._identity_prompt = None
            await self._receipt(await self.controller.test_inventory(self.controller.owner))

    async def cancel(self, update, context):
        if self._admit(update):
            self._identity_prompt = None
            await self._receipt(await self.controller.cancel(self.controller.owner))

    async def resume(self, update, context):
        if not self._admit(update):
            return
        args = context.args or []
        checkpoint = args[0] if len(args) == 1 else None
        reply = update.message.reply_to_message
        await self._receipt(await self.controller.resume(self.controller.owner, checkpoint,
                             reply.message_id if reply else None))

    async def status(self, update, context):
        if not self._admit(update):
            return
        status = self.controller.status()
        interval = 'یک بررسی بدون زمان‌بندی' if status.inventory_test else status.interval or 'خارج از بازه'
        try:
            registered = 'ثبت‌شده' if self.controller.profile.national_id() else 'ثبت‌نشده'
        except RuntimeError:
            registered = 'نیازمند ثبت دوباره با /set_national_id'
        await self.notifications.send(
            f'وضعیت: {STATES[status.state.name]}\nزمان تهران: {status.now:%Y-%m-%d %H:%M:%S}\n'
            f'محصول: {status.product} — {status.size} — تعداد {status.quantity}\n'
            f'حالت مشاهده: {"فعال" if status.dry_run else "غیرفعال"}\nفاصلهٔ فعلی: {interval}\n'
            f'آخرین نتیجه: {status.last_stock or "—"}\nآخرین بررسی: {status.last_check or "—"}\n'
            f'زمان اقدام بعدی: {status.next_action or "—"}\nنتیجه اجرا: {status.outcome or "—"}\n'
            f'مرحلهٔ قابل ادامه: {status.checkpoint_id or "—"}\n'
            f'کد ملی: {registered}\nورود خودکار روزانه: {self.controller.settings.schedule.login:%H:%M} تهران\n'
            'گزارش عیب‌یابی: /app/logs/diagnostics/workflow.jsonl در Docker')

    async def _delete_input(self, message):
        if self.controller.settings.delete_sensitive_messages:
            try:
                await self.bot.delete_message(chat_id=self.controller.owner.chat_id, message_id=message.message_id)
            except Exception as error:
                self.controller.diagnostics.error('delete_sensitive_input', error)
                try:
                    await self.notifications.publish('deletion_unavailable')
                except Exception:
                    pass

    async def text(self, update, context):
        if not self._admit(update):
            return
        broker = self.controller.broker
        pending = broker.pending
        message = update.message
        reply = message.reply_to_message
        if self._identity_prompt is not None and not self.controller.active:
            prompt_id, issued, deadline = self._identity_prompt
            now = datetime.now(timezone.utc)
            saved = False
            identity = ''
            try:
                if (now >= deadline or not reply or reply.message_id != prompt_id
                        or message.date < issued.replace(microsecond=0)):
                    raise ValueError
                identity = normalize_credential('national_id', message.text or '')
                self.controller.profile.save(identity)
                saved = True
            except ValueError:
                await self.notifications.send('کد ملی پذیرفته نشد؛ ده رقم را به پیام فعلی پاسخ دهید. اگر مهلت گذشته /set_national_id بفرستید.')
            finally:
                identity = ''
                await self._delete_input(message)
            if saved:
                self._identity_prompt = None
                await self.notifications.send('کد ملی ذخیره شد. ورود خودکار روزانه در ساعت '
                    f'{self.controller.settings.schedule.login:%H:%M} تهران انجام می‌شود؛ سپس در صورت نیاز OTP را درخواست می‌کنم. '
                    'برای تغییر کد ملی /set_national_id بفرستید.')
            return
        if pending is None or pending.kind == 'manual':
            return
        accepted = broker.offer(message.text or '', reply_to=reply.message_id if reply else None,
                                sent_at=message.date)
        await self._delete_input(message)
        if not accepted:
            await self.notifications.send('ورودی پذیرفته نشد؛ قالب و پاسخ به پیام فعلی را بررسی کنید. مقدار ورودی بازگو نمی‌شود.')
