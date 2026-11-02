"""Explicit state transitions and nonsecret public snapshots."""
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum, auto


class WorkflowState(Enum):
    IDLE = auto()
    WAITING_FOR_NATIONAL_ID = auto()
    CHECKING_SESSION = auto()
    LOGIN_IN_PROGRESS = auto()
    WAITING_FOR_OTP = auto()
    READY_FOR_SALE = auto()
    MONITORING = auto()
    PRODUCT_FOUND = auto()
    CHECKOUT = auto()
    WAITING_FOR_MANUAL_ACTION = auto()
    PAYMENT_READY = auto()
    CANCELLING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


S = WorkflowState
TERMINAL = {S.IDLE, S.COMPLETED, S.CANCELLED, S.FAILED}
TRANSITIONS = {
    S.IDLE: {S.WAITING_FOR_NATIONAL_ID},
    S.WAITING_FOR_NATIONAL_ID: {S.CHECKING_SESSION},
    S.CHECKING_SESSION: {S.WAITING_FOR_NATIONAL_ID, S.LOGIN_IN_PROGRESS, S.WAITING_FOR_OTP, S.READY_FOR_SALE},
    S.LOGIN_IN_PROGRESS: {S.WAITING_FOR_NATIONAL_ID, S.WAITING_FOR_OTP, S.READY_FOR_SALE},
    S.WAITING_FOR_OTP: {S.LOGIN_IN_PROGRESS},
    S.READY_FOR_SALE: {S.MONITORING},
    S.MONITORING: {S.WAITING_FOR_NATIONAL_ID, S.PRODUCT_FOUND},
    S.PRODUCT_FOUND: {S.CHECKOUT},
    S.CHECKOUT: {S.PAYMENT_READY},
    S.PAYMENT_READY: set(),
    S.WAITING_FOR_MANUAL_ACTION: {S.CHECKING_SESSION, S.LOGIN_IN_PROGRESS, S.READY_FOR_SALE,
                                  S.MONITORING, S.CHECKOUT, S.PAYMENT_READY},
    S.CANCELLING: {S.CANCELLED},
    S.COMPLETED: {S.WAITING_FOR_NATIONAL_ID, S.CANCELLING},
    S.CANCELLED: {S.WAITING_FOR_NATIONAL_ID, S.CANCELLING},
    S.FAILED: {S.WAITING_FOR_NATIONAL_ID, S.CANCELLING},
}
for _state in set(S) - TERMINAL - {S.CANCELLING}:
    TRANSITIONS[_state] |= {S.CANCELLING, S.COMPLETED, S.FAILED}
    if _state != S.WAITING_FOR_NATIONAL_ID:
        TRANSITIONS[_state].add(S.WAITING_FOR_MANUAL_ACTION)


def validate_transition(current: WorkflowState, following: WorkflowState) -> None:
    if following != current and following not in TRANSITIONS[current]:
        raise RuntimeError('Invalid workflow transition.')


@dataclass(frozen=True)
class AuthorizedOwner:
    user_id: int
    chat_id: int


@dataclass(frozen=True)
class Receipt:
    accepted: bool
    reason: str
    run_id: str | None = None


@dataclass(frozen=True)
class PaymentResult:
    url: str = field(repr=False)


@dataclass(frozen=True)
class StatusSnapshot:
    state: WorkflowState
    now: datetime
    run_id: str | None
    sale_date: date | None
    dry_run: bool
    product: str
    size: str
    quantity: int
    interval: int | None
    checkpoint_id: str | None
    outcome: str | None
    last_stock: str | None
    last_check: datetime | None
    next_action: datetime | None = None
    inventory_test: bool = False
