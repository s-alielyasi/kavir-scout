"""One browser owner; short commands never await the purchase workflow."""
import asyncio
from datetime import timedelta
from uuid import uuid4

from config import BotSettings
from kavirtire.errors import SessionExpired
from kavirtire.orchestration.input_broker import InputBroker
from kavirtire.orchestration.models import (
    AuthorizedOwner, Receipt, StatusSnapshot, WorkflowState as S, validate_transition)
from kavirtire.orchestration.order_attempts import OrderAttemptStore
from kavirtire.orchestration.scheduling import TehranClock, in_tehran


class WindowClosed(Exception):
    pass


class ClockInconsistent(Exception):
    pass


class RunInteractions:
    def __init__(self, controller, transport):
        self.controller, self.transport = controller, transport

    async def request_national_id(self):
        self.controller.ensure_open()
        self.controller.transition(S.WAITING_FOR_NATIONAL_ID)
        value = await self.transport.request_national_id()
        self.controller.ensure_open()
        self.controller.transition(S.CHECKING_SESSION)
        return value

    async def request_otp(self):
        self.controller.ensure_open()
        self.controller.transition(S.WAITING_FOR_OTP)
        value = await self.transport.request_otp()
        self.controller.ensure_open()
        self.controller.transition(S.LOGIN_IN_PROGRESS)
        return value

    async def request_manual_action(self, reason):
        previous = self.controller.state
        if previous != S.PAYMENT_READY:
            self.controller.transition(S.WAITING_FOR_MANUAL_ACTION)
        try:
            await self.transport.request_manual_action(reason)
        finally:
            if self.controller.state == S.WAITING_FOR_MANUAL_ACTION:
                self.controller.transition(previous)


class PurchaseOrchestrator:
    def __init__(self, settings: BotSettings, interactions_factory, notifications,
                 service_factory, *, clock=None, attempts=None):
        self.settings = settings
        self.clock = clock or TehranClock()
        self.owner = AuthorizedOwner(settings.allowed_user_id, settings.allowed_chat_id)
        self.broker = InputBroker(self.clock.now)
        self.attempts = attempts or OrderAttemptStore(settings.retailer.root / 'data/order_attempt.json')
        self.interactions_factory = interactions_factory
        self.notifications, self.service_factory = notifications, service_factory
        self.state = S.IDLE
        self.run_id = None
        self.sale_date = None
        self.outcome = None
        self.last_stock = None
        self.last_check = None
        self._task = None
        self._lock = asyncio.Lock()
        self._cancel = asyncio.Event()
        self._started = False
        self._admitted = False
        self._authenticated = False
        self._deadline_expired = False
        self._clock_failed = False
        self._last_now = None
        self._last_cycle_start = None
        self._closing = False

    @property
    def active(self):
        return self._task is not None and not self._task.done()

    def transition(self, following):
        if self._cancel.is_set() and following not in (S.CANCELLING, S.CANCELLED):
            raise asyncio.CancelledError
        validate_transition(self.state, following)
        self.state = following

    def status(self):
        now = in_tehran(self.clock.now())
        decision = self.settings.schedule.decide(now, self.sale_date) if self.sale_date else None
        pending = self.broker.pending
        next_action = None
        if self.active and decision:
            next_action = pending.deadline if pending else decision.boundary
            if self.state == S.MONITORING and decision.interval and self._last_cycle_start is not None:
                seconds = max(0, self._last_cycle_start + decision.interval - self.clock.monotonic())
                next_action = min(now + timedelta(seconds=seconds), decision.boundary)
        return StatusSnapshot(self.state, now, self.run_id, self.sale_date, self.settings.dry_run,
            self.settings.retailer.target_product, self.settings.retailer.target_size,
            self.settings.retailer.target_quantity, decision.interval if decision else None,
            pending.request_id if pending and pending.kind == 'manual' else None,
            self.outcome, self.last_stock, self.last_check, next_action)

    async def arm(self, owner):
        if owner != self.owner:
            return Receipt(False, 'unauthorized')
        async with self._lock:
            if self._closing:
                return Receipt(False, 'shutting_down')
            if self.active:
                return Receipt(False, 'already_active', self.run_id)
            now = in_tehran(self.clock.now())
            if self.settings.schedule.decide(now, now.date()).phase == 'closed':
                return Receipt(False, 'sale_window_ended')
            if self.attempts.blocked():
                return Receipt(False, 'unresolved_order_attempt')
            self.run_id, self.sale_date = uuid4().hex, now.date()
            self.outcome = self.last_stock = self.last_check = None
            self._cancel = asyncio.Event()
            self._started = self._admitted = self._authenticated = False
            self._deadline_expired = self._clock_failed = False
            self._last_now = now
            self._last_cycle_start = None
            self.transition(S.WAITING_FOR_NATIONAL_ID)
            self._task = asyncio.create_task(self._worker(), name='kavir-workflow')
            self._task.add_done_callback(self._settled)
            return Receipt(True, 'armed', self.run_id)

    def _settled(self, task):
        if self._task is not task:
            return
        if self.state == S.CANCELLING:
            self.state = S.CANCELLED
        if not task.cancelled() and task.exception() is not None:
            self.state = S.FAILED
            self.outcome = 'cleanup_failed'

    async def cancel(self, owner):
        if owner != self.owner:
            return Receipt(False, 'unauthorized')
        async with self._lock:
            if not self.active:
                return Receipt(True, 'idle', self.run_id)
            self._request_cancel()
            return Receipt(True, 'cancellation_requested', self.run_id)

    def _request_cancel(self):
        if self.active and not self._cancel.is_set():
            self.transition(S.CANCELLING)
            self._cancel.set()
            self.broker.cancel()
            if self._started:
                self._task.cancel()

    def begin_shutdown(self):
        self._closing = True
        self._request_cancel()

    async def resume(self, owner, checkpoint_id=None, reply_to=None):
        if owner != self.owner:
            return Receipt(False, 'unauthorized')
        if self.state not in (S.WAITING_FOR_MANUAL_ACTION, S.PAYMENT_READY):
            return Receipt(False, 'no_manual_checkpoint', self.run_id)
        accepted = self.broker.resume(checkpoint_id, reply_to)
        return Receipt(accepted, 'resume_requested' if accepted else 'reply_to_current_checkpoint', self.run_id)

    def ensure_open(self):
        if self._cancel.is_set():
            raise asyncio.CancelledError
        now = in_tehran(self.clock.now())
        if self._last_now is not None and now < self._last_now:
            raise ClockInconsistent
        self._last_now = now
        if self.settings.schedule.decide(now, self.sale_date).phase == 'closed':
            raise WindowClosed
        return now

    def input_deadline(self):
        deadline = self.clock.now() + timedelta(seconds=self.settings.otp_timeout)
        if not self._admitted:
            deadline = min(deadline, self.settings.schedule.cutoff(self.sale_date))
        return deadline

    async def _notify(self, event):
        try:
            await asyncio.wait_for(self.notifications.publish(event), timeout=10)
        except Exception:
            pass  # no raw transport exception or parameters enter logs

    async def _watch_deadline(self):
        while not self._admitted:
            await asyncio.sleep(0.25)
            try:
                self.ensure_open()
            except WindowClosed:
                self._deadline_expired = True
                self.broker.cancel()
                self._task.cancel()
                return
            except ClockInconsistent:
                self._clock_failed = True
                self.broker.cancel()
                self._task.cancel()
                return

    async def _remind(self):
        reminder = self.settings.schedule.at(self.sale_date, self.settings.schedule.reminder)
        while not self._authenticated:
            if self.clock.now() >= reminder:
                await self._notify('login_reminder')
                return
            await asyncio.sleep(min(1, (reminder-self.clock.now()).total_seconds()))

    async def _wait_cycle(self, last_start):
        while True:
            now = self.ensure_open()
            decision = self.settings.schedule.decide(now, self.sale_date)
            if decision.phase == 'before_start':
                await self.clock.sleep(min(1, (decision.boundary-now).total_seconds()))
                continue
            # Recompute cadence at every boundary; skipped ticks are never replayed.
            remaining = 0 if last_start is None else last_start + decision.interval - self.clock.monotonic()
            if remaining <= 0:
                return
            await self.clock.sleep(min(1, remaining, (decision.boundary-now).total_seconds()))

    async def _deliver(self, result, interactions):
        deadline = self.clock.monotonic() + self.settings.handoff_ttl
        failures = 0
        while self.clock.monotonic() < deadline:
            remaining = deadline-self.clock.monotonic()
            try:
                await asyncio.wait_for(self.notifications.payment(result.url), min(10, remaining))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failures += 1
                delay = getattr(error, 'retry_after', min(2 ** failures, 30))
                if hasattr(delay, 'total_seconds'):
                    delay = delay.total_seconds()
                delay = max(1, float(delay))
                await self.clock.sleep(min(delay, max(0, deadline-self.clock.monotonic())))
                if failures >= 3 and self.clock.monotonic() < deadline:
                    async with asyncio.timeout(max(0, deadline-self.clock.monotonic())):
                        await interactions.request_manual_action('payment_delivery_retry')
                    failures = 0
                continue
            self.attempts.handed_off(self.run_id)
            self.outcome = 'payment_handoff_sent'
            self.transition(S.COMPLETED)
            # Retention failure must not restart notification or checkout.
            await self.clock.sleep(max(0, deadline-self.clock.monotonic()))
            return
        raise TimeoutError('Payment delivery deadline expired.')

    async def _worker(self):
        self._started = True
        watchdog = asyncio.create_task(self._watch_deadline())
        reminder = asyncio.create_task(self._remind())
        identity = ''
        try:
            if self._cancel.is_set():
                raise asyncio.CancelledError
            interactions = RunInteractions(self, self.interactions_factory(self))
            identity = await interactions.request_national_id()
            async with self.service_factory(self.settings.retailer, interactions) as service:
                try:
                    authentication = service.authenticate(identity)
                    identity = ''
                    await authentication
                    authentication = None
                finally:
                    identity = ''
                self.ensure_open()
                self._authenticated = True
                if getattr(service, 'policy_disallowed', False) is True:
                    await self._notify('requested_quantity_disallowed')
                self.transition(S.READY_FOR_SALE)
                last_start = None
                refresh = False
                while True:
                    await self._wait_cycle(last_start)
                    self.transition(S.MONITORING)
                    last_start = self.clock.monotonic()
                    self._last_cycle_start = last_start
                    try:
                        stock = await service.observe(refresh=refresh)
                    except SessionExpired:
                        self._authenticated = False
                        identity = await interactions.request_national_id()
                        try:
                            authentication = service.authenticate(identity)
                            identity = ''
                            await authentication
                            authentication = None
                        finally:
                            identity = ''
                        self._authenticated = True
                        self.transition(S.READY_FOR_SALE)
                        refresh = False
                        last_start = None
                        continue
                    self.ensure_open()  # discard a late response, even if in stock
                    if stock not in ('available', 'out_of_stock', 'target_absent'):
                        raise RuntimeError('Unknown stock outcome.')
                    self.last_stock, self.last_check = stock, self.clock.now()
                    refresh = True
                    if stock != 'available':
                        continue
                    self.transition(S.PRODUCT_FOUND)
                    if self.settings.dry_run:
                        self.outcome = 'dry_run_target_found'
                        self.transition(S.COMPLETED)
                        return
                    if not self.settings.live_checkout_approved:
                        raise RuntimeError('Live checkout release gates incomplete.')
                    await service.preflight_live()
                    self.ensure_open()
                    self.attempts.begin(self.run_id, self.sale_date)
                    self._admitted = True
                    self.transition(S.CHECKOUT)
                    async with asyncio.timeout(self.settings.checkout_timeout):
                        result = await service.checkout(before_selection=self.ensure_open)
                    self.transition(S.PAYMENT_READY)
                    await self._deliver(result, interactions)
                    result = None
                    return
        except WindowClosed:
            self.outcome = 'sale_window_ended'
            self.transition(S.COMPLETED)
        except ClockInconsistent:
            self.outcome = 'clock_inconsistent'
            self.transition(S.FAILED)
        except asyncio.CancelledError:
            if self._deadline_expired or self._clock_failed:
                self.outcome = 'clock_inconsistent' if self._clock_failed else 'sale_window_ended'
                self.state = S.FAILED if self._clock_failed else S.COMPLETED
            else:
                self.outcome = 'cancelled_order_may_exist' if self._admitted else 'cancelled'
                self.state = S.CANCELLED
        except Exception:
            self.outcome = 'order_requires_reconciliation' if self._admitted else 'workflow_failed'
            if self.state != S.COMPLETED:
                self.transition(S.FAILED)
        finally:
            identity = ''
            self.broker.cancel()
            for task in (watchdog, reminder):
                task.cancel()
            await asyncio.gather(watchdog, reminder, return_exceptions=True)
            try:
                await self._notify(self.outcome or 'workflow_finished')
            finally:
                if self._cancel.is_set():
                    self.state = S.CANCELLED

    async def close(self):
        self.begin_shutdown()
        if self.active:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 20)
            except TimeoutError:
                self._task.cancel()
                done, _ = await asyncio.wait([self._task], timeout=5)
                if not done:
                    self.outcome = 'cleanup_timed_out'
                    raise RuntimeError('Cleanup timed out; reconcile any order before restarting.') from None
