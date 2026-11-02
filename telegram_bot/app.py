"""Explicit PTB lifecycle; startup remains idle and discards queued updates."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import signal

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, TypeHandler, filters
from kavirtire.orchestration.purchase_workflow import PurchaseOrchestrator
from telegram_bot.handlers import Handlers
from telegram_bot.interactions import TelegramInteractions
from telegram_bot.notifications import TelegramNotifications

LOG = logging.getLogger('kavir')


def quiet_framework_logs():
    # A parent logger's level alone does not suppress propagated child records.
    for name in ('telegram', 'httpx', 'httpcore', 'playwright'):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        logger.disabled = True


@dataclass
class BotRuntime:
    application: object
    controller: PurchaseOrchestrator
    handlers: Handlers


def build_application(settings, *, service_factory=None, clock=None) -> BotRuntime:
    quiet_framework_logs()
    builder = (Application.builder().token(settings.token).concurrent_updates(False)
               .job_queue(None).persistence(None).connect_timeout(10).read_timeout(10).write_timeout(10))
    if settings.proxy_url:
        builder = builder.proxy(settings.proxy_url).get_updates_proxy(settings.proxy_url)
    app = builder.build()
    if service_factory is None:
        # Only this composition root knows the browser adapter. Handlers and
        # Telegram transport modules never access Page, Locator or Playwright.
        from kavirtire.orchestration.retailer import browser_session
        service_factory = lambda config, interactions: browser_session(config, interactions, dry_run=settings.dry_run)
    notifier = TelegramNotifications(app.bot, settings)
    controller = PurchaseOrchestrator(settings, lambda c: TelegramInteractions(app.bot, c),
                                      notifier, service_factory, clock=clock)
    handlers = Handlers(controller, app.bot, started_at=datetime.now(timezone.utc))
    app.add_handler(TypeHandler(Update, handlers.gate), group=-100)
    for name in ('start', 'arm', 'test_inventory', 'status', 'cancel', 'resume'):
        app.add_handler(CommandHandler(name, getattr(handlers, name)), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text), group=0)

    async def error_handler(update, context):
        # No exception body, update, traceback, URL or token is logged.
        LOG.warning('Telegram update processing failed; payload omitted.')
        try:
            await notifier.publish('workflow_failed')
        except Exception:
            pass
    app.add_error_handler(error_handler)
    return BotRuntime(app, controller, handlers)


async def serve(runtime: BotRuntime, stop: asyncio.Event | None = None, *, test_inventory: bool = False):
    app = runtime.application
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
            installed.append(signum)
        except (NotImplementedError, RuntimeError):
            pass  # Windows Ctrl+C cancels asyncio.run and still executes finally.

    def polling_error(error):
        LOG.warning('Telegram polling unavailable; transport details omitted.')

    try:
        async with app:
            try:
                await app.start()
                await app.updater.start_polling(drop_pending_updates=True, allowed_updates=['message'],
                                                 error_callback=polling_error, bootstrap_retries=0)
                LOG.info('Telegram ready; idle until an authorized daily /arm.')
                if test_inventory:
                    receipt = await runtime.controller.test_inventory(runtime.controller.owner)
                    if not receipt.accepted:
                        LOG.warning('Explicit inventory test was not admitted; bot remains idle.')
                await stop.wait()
            finally:
                begin_shutdown = getattr(runtime.controller, 'begin_shutdown', None)
                if begin_shutdown is not None:
                    begin_shutdown()
                if app.updater.running:
                    await app.updater.stop()
                try:
                    await runtime.controller.close()
                finally:
                    # No queued pre-shutdown arm may start while draining PTB.
                    queue = getattr(app, 'update_queue', None)
                    if queue is not None:
                        while not queue.empty():
                            try:
                                queue.get_nowait()
                                queue.task_done()
                            except asyncio.QueueEmpty:
                                break
                    if app.running:
                        await app.stop()
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)
