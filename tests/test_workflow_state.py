import unittest
from kavirtire.orchestration.models import WorkflowState as S, validate_transition


class StateTests(unittest.TestCase):
    def test_cannot_skip_admission_or_replay_checkout(self):
        for current, following in [(S.IDLE, S.CHECKOUT), (S.MONITORING, S.CHECKOUT),
                (S.WAITING_FOR_OTP, S.CHECKOUT), (S.CANCELLED, S.MONITORING),
                (S.COMPLETED, S.CHECKOUT), (S.PAYMENT_READY, S.CHECKOUT),
                (S.CANCELLING, S.MONITORING)]:
            with self.subTest(current=current, following=following), self.assertRaises(RuntimeError):
                validate_transition(current, following)

    def test_cancel_is_available_during_every_active_phase(self):
        for state in (S.WAITING_FOR_NATIONAL_ID, S.CHECKING_SESSION, S.LOGIN_IN_PROGRESS,
                      S.WAITING_FOR_OTP, S.READY_FOR_SALE, S.MONITORING, S.PRODUCT_FOUND,
                      S.CHECKOUT, S.WAITING_FOR_MANUAL_ACTION, S.PAYMENT_READY):
            validate_transition(state, S.CANCELLING)
        validate_transition(S.CANCELLING, S.CANCELLED)
