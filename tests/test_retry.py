import pytest

from shopnotify.retry import RateLimitError, TransientError, retry_call


class Recorder:
    """Fake sleep that records delays instead of waiting."""

    def __init__(self):
        self.delays: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)


def no_jitter(a: float, b: float) -> float:
    return 0.0


def test_succeeds_after_transient_failures():
    rec = Recorder()
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TransientError("502 bad gateway")
        return "ok"

    result = retry_call(flaky, base_delay=0.5, sleep=rec.sleep,
                        jitter=no_jitter)
    assert result == "ok"
    assert rec.delays == [0.5, 1.0]  # exponential backoff


def test_retry_after_overrides_backoff():
    rec = Recorder()
    attempts = {"n": 0}

    def limited():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RateLimitError("slow down", retry_after=7.0)
        return "ok"

    assert retry_call(limited, base_delay=0.5, sleep=rec.sleep,
                      jitter=no_jitter) == "ok"
    assert rec.delays == [7.0]  # server instruction wins


def test_gives_up_after_max_attempts():
    rec = Recorder()

    def always_down():
        raise ConnectionError("unreachable")

    with pytest.raises(ConnectionError):
        retry_call(always_down, max_attempts=3, base_delay=0.5,
                   sleep=rec.sleep, jitter=no_jitter)
    assert len(rec.delays) == 2  # no sleep after the final attempt


def test_fatal_errors_are_not_retried():
    rec = Recorder()
    attempts = {"n": 0}

    def bad_request():
        attempts["n"] += 1
        raise ValueError("bad payload")

    with pytest.raises(ValueError):
        retry_call(bad_request, sleep=rec.sleep, jitter=no_jitter)
    assert attempts["n"] == 1
    assert rec.delays == []
