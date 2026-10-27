"""Expected workflow exits (never include personal values in messages)."""


class BotError(RuntimeError):
    pass


class AmbiguousElement(BotError):
    pass


class SessionExpired(BotError):
    pass


class SafetyError(BotError):
    pass


class QuantityLimit(SafetyError):
    pass
