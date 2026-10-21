"""Injectable clock so time-driven simulations can be tested without sleeping."""

import time


class SystemClock:
    """Real wall-clock time; used by the running server."""

    def now(self) -> float:
        return time.time()


class ManualClock:
    """Test clock that moves only when a test advances it."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


_clock: SystemClock | ManualClock = SystemClock()


def get_clock() -> SystemClock | ManualClock:
    return _clock


def set_clock(clock: SystemClock | ManualClock) -> None:
    global _clock
    _clock = clock
