"""One correlated RAM-only input; no transport objects or secret persistence."""
import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
import re
from uuid import uuid4

from config import DIGITS


def normalize_credential(kind: str, value: str) -> str:
    value = value.strip().translate(DIGITS)
    pattern = r'[0-9]{10}' if kind == 'national_id' else r'(?:[0-9]{4,8}|[A-Za-z0-9]{8})'
    if kind not in ('national_id', 'otp') or not re.fullmatch(pattern, value):
        raise ValueError('Invalid credential format.')
    return value


@dataclass(frozen=True)
class InputRequest:
    request_id: str
    kind: str
    run_id: str
    issued_at: datetime
    deadline: datetime
    prompt_id: int | None = None


class InputBroker:
    def __init__(self, now=None):
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.pending: InputRequest | None = None
        self._future: asyncio.Future | None = None

    def open(self, kind: str, run_id: str, deadline: datetime) -> InputRequest:
        if self.pending is not None or kind not in ('national_id', 'otp', 'manual'):
            raise RuntimeError('Input request already active or unsupported.')
        if deadline.tzinfo is None:
            raise ValueError('Input deadline must be timezone-aware.')
        self.pending = InputRequest(uuid4().hex, kind, run_id, self.now(), deadline)
        self._future = asyncio.get_running_loop().create_future()
        return self.pending

    def bind_prompt(self, request_id: str, message_id: int) -> None:
        if self.pending and self.pending.request_id == request_id:
            self.pending = replace(self.pending, prompt_id=message_id)

    def offer(self, value: str, *, reply_to: int | None, sent_at: datetime) -> bool:
        request, future = self.pending, self._future
        if (request is None or future is None or future.done() or request.kind == 'manual'
                or request.prompt_id is None or reply_to != request.prompt_id
                or sent_at.tzinfo is None or self.now() >= request.deadline
                or sent_at < request.issued_at.replace(microsecond=0)
                or sent_at > self.now().replace(microsecond=0) + timedelta(seconds=5)):
            return False
        try:
            normalized = normalize_credential(request.kind, value)
        except ValueError:
            return False
        future.set_result(normalized)
        return True

    def resume(self, request_id: str | None, reply_to: int | None = None) -> bool:
        request, future = self.pending, self._future
        if (request is None or request.kind != 'manual' or future is None or future.done()
                or self.now() >= request.deadline):
            return False
        if not ((request_id is not None and request_id == request.request_id)
                or (reply_to is not None and request.prompt_id is not None and reply_to == request.prompt_id)):
            return False
        future.set_result('')
        return True

    async def wait(self, request_id: str) -> str:
        request, future = self.pending, self._future
        if request is None or request.request_id != request_id or future is None:
            raise RuntimeError('Input request is no longer active.')
        try:
            return await asyncio.wait_for(future, max(0, (request.deadline-self.now()).total_seconds()))
        finally:
            if self.pending and self.pending.request_id == request_id:
                self.cancel()

    def cancel(self) -> None:
        future, self._future = self._future, None
        self.pending = None
        if future is not None and not future.done():
            future.cancel()
