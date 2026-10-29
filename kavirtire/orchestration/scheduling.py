"""Civil time is Tehran-aware; durations belong to the event loop clock."""
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo('Asia/Tehran')


def in_tehran(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('An aware datetime is required.')
    return now.astimezone(TEHRAN)


@dataclass(frozen=True)
class Decision:
    phase: str
    interval: int | None
    boundary: datetime
    window: int = 0


@dataclass(frozen=True)
class Schedule:
    start: time = time(8)
    ends: tuple[time, ...] = (time(8, 5), time(8, 10), time(8, 15))
    intervals: tuple[int, ...] = (5, 15, 30)
    reminder: time = time(7, 55)

    def __post_init__(self):
        if (len(self.ends) != 3 or len(self.intervals) != 3
                or not self.reminder < self.start < self.ends[0] < self.ends[1] < self.ends[2]
                or any(i <= 0 for i in self.intervals)
                or any(t.tzinfo is not None for t in (self.reminder, self.start, *self.ends))):
            raise ValueError('Invalid sale schedule.')

    def at(self, day: date, when: time) -> datetime:
        return datetime.combine(day, when, TEHRAN)

    def cutoff(self, day: date) -> datetime:
        return self.at(day, self.ends[-1])

    def decide(self, now: datetime, sale_date: date) -> Decision:
        now = in_tehran(now)
        cutoff = self.cutoff(sale_date)
        if now.date() != sale_date or now >= cutoff:
            return Decision('closed', None, cutoff)
        if now < self.at(sale_date, self.start):
            return Decision('before_start', None, self.at(sale_date, self.start))
        for window, (end, interval) in enumerate(zip(self.ends, self.intervals), 1):
            if now < self.at(sale_date, end):
                return Decision('open', interval, self.at(sale_date, end), window)
        return Decision('closed', None, cutoff)


def get_poll_interval(now_tehran: datetime) -> int | None:
    now = in_tehran(now_tehran)
    return Schedule().decide(now, now.date()).interval


class TehranClock:
    def now(self) -> datetime:
        return datetime.now(TEHRAN)

    def monotonic(self) -> float:
        import asyncio
        return asyncio.get_running_loop().time()

    async def sleep(self, seconds: float) -> None:
        import asyncio
        await asyncio.sleep(seconds)
