import time

from src.dispatcher.scheduler import PollScheduler


def test_scheduler_fires_at_interval():
    """A job runs at its configured interval."""
    counter = {"n": 0}

    def tick() -> None:
        counter["n"] += 1

    scheduler = PollScheduler()
    scheduler.add_job(tick, interval_seconds=0.1, job_id="tick")
    scheduler.start()
    try:
        time.sleep(0.45)  # expect ~4 fires
    finally:
        scheduler.stop()

    assert counter["n"] >= 3, f"expected >=3 fires, got {counter['n']}"


def test_scheduler_runs_multiple_jobs():
    """Two jobs at different intervals both run."""
    a = {"n": 0}
    b = {"n": 0}

    scheduler = PollScheduler()
    scheduler.add_job(lambda: a.__setitem__("n", a["n"] + 1), interval_seconds=0.1, job_id="a")
    scheduler.add_job(lambda: b.__setitem__("n", b["n"] + 1), interval_seconds=0.2, job_id="b")
    scheduler.start()
    try:
        time.sleep(0.5)
    finally:
        scheduler.stop()

    assert a["n"] >= 3, f"job 'a' fired {a['n']} times"
    assert b["n"] >= 1, f"job 'b' fired {b['n']} times"
    assert a["n"] > b["n"], "job 'a' should fire more often than 'b'"


def test_scheduler_stop_halts_jobs():
    """After stop(), no more callbacks fire."""
    counter = {"n": 0}
    scheduler = PollScheduler()
    scheduler.add_job(lambda: counter.__setitem__("n", counter["n"] + 1), interval_seconds=0.05, job_id="t")
    scheduler.start()
    time.sleep(0.2)
    scheduler.stop()
    snapshot = counter["n"]
    time.sleep(0.3)
    assert counter["n"] == snapshot, f"jobs kept firing after stop: {snapshot}->{counter['n']}"


def test_scheduler_callback_exception_does_not_kill_scheduler():
    """A failing callback doesn't stop subsequent invocations."""
    state = {"good": 0, "bad": 0}

    def bad() -> None:
        state["bad"] += 1
        raise RuntimeError("boom")

    def good() -> None:
        state["good"] += 1

    scheduler = PollScheduler()
    scheduler.add_job(bad, interval_seconds=0.1, job_id="bad")
    scheduler.add_job(good, interval_seconds=0.1, job_id="good")
    scheduler.start()
    try:
        time.sleep(0.45)
    finally:
        scheduler.stop()

    assert state["bad"] >= 2, "failing job should still be retried"
    assert state["good"] >= 2, "good job should not be affected by bad's failures"
