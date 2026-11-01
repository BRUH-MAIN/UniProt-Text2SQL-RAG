from agent.ratelimit import RateLimiter


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_per_client_limit_and_window_expiry():
    c = Clock()
    rl = RateLimiter(per_client=2, global_limit=100, window_s=60, clock=c)
    assert rl.allow("a")[0] and rl.allow("a")[0]
    ok, msg = rl.allow("a")
    assert not ok and "per hour" in msg
    assert rl.allow("b")[0]  # other clients unaffected
    c.t = 61
    assert rl.allow("a")[0]  # window slid


def test_global_limit():
    rl = RateLimiter(per_client=10, global_limit=2, window_s=60, clock=Clock())
    assert rl.allow("a")[0] and rl.allow("b")[0]
    ok, msg = rl.allow("c")
    assert not ok and "capacity" in msg
