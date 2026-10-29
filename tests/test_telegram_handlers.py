import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from telegram import Update
from config import BotSettings
from kavirtire.orchestration.input_broker import InputBroker
from kavirtire.orchestration.models import AuthorizedOwner, Receipt, StatusSnapshot, WorkflowState
from telegram_bot.authorization import authorized
from telegram_bot.handlers import Handlers
from telegram_bot.interactions import TelegramInteractions
from telegram_bot.notifications import TelegramNotifications


OWNER = AuthorizedOwner(123, 123)
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def update(text='/status', *, uid=123, cid=123, chat_type='private', stamp=None, extra=None, update_id=1, reply=None):
    stamp = stamp or datetime.now(timezone.utc).replace(microsecond=0)
    message = {'message_id': 50, 'date': int(stamp.timestamp()), 'text': text,
               'from': {'id': uid, 'is_bot': False, 'first_name': 'Fixture'},
               'chat': {'id': cid, 'type': chat_type}}
    if reply is not None:
        message['reply_to_message'] = {'message_id': reply, 'date': int(stamp.timestamp()),
            'chat': message['chat'], 'from': {'id': 987, 'is_bot': True, 'first_name': 'Bot'}}
    return Update.de_json({'update_id': update_id, 'message': message | (extra or {})}, None)


class TelegramTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = BotSettings.from_env({'TELEGRAM_BOT_TOKEN': '123:fixture_abcdefghijklmnopqrstuvwxyz',
            'TELEGRAM_ALLOWED_USER_ID': '123', 'TELEGRAM_ALLOWED_CHAT_ID': '123'})
        self.bot = AsyncMock()
        self.bot.send_message.return_value = SimpleNamespace(message_id=10)
        self.controller = SimpleNamespace(owner=OWNER, broker=InputBroker(), run_id='a'*32,
            settings=self.settings, input_deadline=lambda: datetime.now(timezone.utc)+timedelta(seconds=30),
            arm=AsyncMock(return_value=Receipt(True, 'armed')), cancel=AsyncMock(return_value=Receipt(True, 'cancellation_requested')),
            test_inventory=AsyncMock(return_value=Receipt(True, 'inventory_test_started')),
            resume=AsyncMock(return_value=Receipt(False, 'reply_to_current_checkpoint')))
        self.handlers = Handlers(self.controller, self.bot, started_at=NOW)

    def test_authorization_rejects_spoofs_and_old_or_edited_updates(self):
        self.assertTrue(authorized(update(), OWNER, NOW))
        for candidate in (update(uid=999), update(cid=999), update(chat_type='group'),
                          update(stamp=NOW-timedelta(days=1)),
                          update(extra={'sender_chat': {'id': -1, 'type': 'channel'}}),
                          update(extra={'forward_origin': {'type': 'hidden_user', 'date': int(NOW.timestamp()), 'sender_user_name': 'x'}}),
                          Update(update_id=9, edited_message=update().message),
                          update(extra={'from': {'id':123,'is_bot':True,'first_name':'Bot'}}),
                          Update(update_id=8)):
            with self.subTest(candidate=candidate.update_id):
                self.assertFalse(authorized(candidate, OWNER, NOW))

    async def test_unauthorized_commands_have_no_domain_or_reply_effect(self):
        for method in (self.handlers.arm, self.handlers.test_inventory, self.handlers.cancel, self.handlers.resume, self.handlers.status, self.handlers.text):
            await method(update(uid=999), SimpleNamespace(args=[]))
        self.controller.arm.assert_not_awaited()
        self.controller.test_inventory.assert_not_awaited()
        self.controller.cancel.assert_not_awaited()
        self.controller.resume.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()

    async def test_replayed_update_does_not_arm_twice(self):
        await self.handlers.arm(update('/arm'), SimpleNamespace(args=[]))
        await self.handlers.arm(update('/arm'), SimpleNamespace(args=[]))
        self.controller.arm.assert_awaited_once()

    async def test_inventory_command_is_deduplicated_and_reply_is_copyable(self):
        for _ in range(2):
            await self.handlers.test_inventory(update('/test_inventory'), None)
        self.controller.test_inventory.assert_awaited_once_with(OWNER)
        self.assertFalse(self.bot.send_message.await_args.kwargs['protect_content'])

    async def test_start_status_and_events_are_copyable(self):
        self.controller.status = lambda: StatusSnapshot(
            state=WorkflowState.IDLE, now=NOW, run_id=None, sale_date=None, dry_run=True,
            product=self.settings.retailer.target_product, size=self.settings.retailer.target_size,
            quantity=4, interval=None, checkpoint_id=None, outcome=None, last_stock=None, last_check=None)
        for i, (command, handler) in enumerate((('/start', self.handlers.start),
                                                ('/status', self.handlers.status)), 1):
            await handler(update(command, update_id=i), None)
            kwargs = self.bot.send_message.await_args.kwargs
            self.assertFalse(kwargs['protect_content'])
            self.assertEqual(kwargs['chat_id'], OWNER.chat_id)
            self.assertTrue(kwargs['link_preview_options'].is_disabled)
        await TelegramNotifications(self.bot, self.settings).publish('sale_window_ended')
        self.assertFalse(self.bot.send_message.await_args.kwargs['protect_content'])

    async def test_login_prompts_remain_protected(self):
        port = TelegramInteractions(self.bot, self.controller)
        for request in (port.request_national_id, port.request_otp):
            task = asyncio.create_task(request())
            try:
                await asyncio.sleep(0)
                self.assertTrue(self.bot.send_message.await_args.kwargs['protect_content'])
                self.assertIsNotNone(self.controller.broker.pending)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertIsNone(self.controller.broker.pending)

    async def test_credentials_need_reply_and_delete_failure_is_nonfatal(self):
        request = self.controller.broker.open('otp', 'a'*32, datetime.now(timezone.utc)+timedelta(seconds=30))
        self.controller.broker.bind_prompt(request.request_id, 10)
        self.bot.delete_message.side_effect = RuntimeError('deletion unavailable')
        await self.handlers.text(update('AbCd1234', reply=9), None)
        self.assertFalse(self.controller.broker._future.done())
        await self.handlers.text(update('AbCd1234', reply=10, update_id=2), None)
        self.assertEqual(await self.controller.broker.wait(request.request_id), 'AbCd1234')
        self.assertIsNone(self.controller.broker.pending)
        for call in self.bot.send_message.await_args_list:
            self.assertNotIn('AbCd1234', str(call))

    async def test_interaction_clears_request_after_send_failure(self):
        self.bot.send_message.side_effect = RuntimeError('transport failed')
        port = TelegramInteractions(self.bot, self.controller)
        with self.assertRaises(RuntimeError):
            await port.request_otp()
        self.assertIsNone(self.controller.broker.pending)

    async def test_payment_has_fixed_recipient_and_private_url_button(self):
        notifier = TelegramNotifications(self.bot, self.settings)
        await notifier.payment('https://bpm.shaparak.ir/pay?token=fixture')
        kwargs = self.bot.send_message.await_args.kwargs
        self.assertEqual(kwargs['chat_id'], 123)
        self.assertTrue(kwargs['protect_content'])
        self.assertTrue(kwargs['link_preview_options'].is_disabled)
        button = kwargs['reply_markup'].inline_keyboard[0][0]
        self.assertEqual(button.text, '💳 پرداخت سفارش')
        self.assertIsNone(button.callback_data)
        with self.assertRaises(ValueError):
            await notifier.payment('https://shaparak.ir.evil.test/pay')
