import pytest

from odoo_agent_gateway.ratelimit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_refuses():
    limiter = RateLimiter(per_minute=3, clock=FakeClock())

    assert [limiter.allow("ana") for _ in range(4)] == [True, True, True, False]


def test_each_login_has_its_own_budget():
    limiter = RateLimiter(per_minute=1, clock=FakeClock())

    assert limiter.allow("ana") is True
    assert limiter.allow("ana") is False
    assert limiter.allow("luis") is True


def test_the_window_slides():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=2, clock=clock)
    limiter.allow("ana")
    clock.now += 30
    limiter.allow("ana")

    assert limiter.allow("ana") is False
    clock.now += 31  # the first call is now more than a minute old
    assert limiter.allow("ana") is True


def test_logins_are_compared_without_case_or_spaces():
    limiter = RateLimiter(per_minute=1, clock=FakeClock())

    assert limiter.allow("Ana") is True
    assert limiter.allow("  ana ") is False


@pytest.mark.parametrize("login", [None, "", "   "])
def test_calls_without_a_login_share_one_bucket(login):
    limiter = RateLimiter(per_minute=1, clock=FakeClock())

    assert limiter.allow(login) is True
    assert limiter.allow(None) is False


def test_refused_calls_do_not_extend_the_block():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=1, clock=clock)
    limiter.allow("ana")
    for _ in range(100):
        limiter.allow("ana")  # hammering while blocked

    clock.now += 61
    assert limiter.allow("ana") is True


@pytest.mark.parametrize("per_minute", [0, -1])
def test_the_limit_must_be_positive(per_minute):
    with pytest.raises(ValueError):
        RateLimiter(per_minute=per_minute)
