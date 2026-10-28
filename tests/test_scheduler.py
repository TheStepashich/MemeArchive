import asyncio

from app import scheduler
from app.config import settings


def test_next_scan_delay_doubles_up_to_cap(monkeypatch):
    monkeypatch.setattr(settings, "scan_interval", 10)
    monkeypatch.setattr(settings, "scan_backoff_max", 60)

    assert scheduler.next_scan_delay(10.0, False) == 10.0
    assert scheduler.next_scan_delay(10.0, True) == 20.0
    assert scheduler.next_scan_delay(20.0, True) == 40.0
    assert scheduler.next_scan_delay(40.0, True) == 60.0
    assert scheduler.next_scan_delay(60.0, True) == 60.0
    assert scheduler.next_scan_delay(60.0, False) == 10.0


def test_periodic_ingest_resets_delay_after_clean_pass(monkeypatch):
    from collections import Counter

    monkeypatch.setattr(settings, "scan_interval", 10)
    monkeypatch.setattr(settings, "scan_backoff_max", 120)

    stats_seq = iter([Counter(aborted=1), Counter(aborted=1), Counter()])
    timeouts: list[float] = []
    stop = asyncio.Event()

    def fake_add_dir():
        if len(timeouts) >= 2:
            stop.set()
        return next(stats_seq, Counter())

    async def fake_wait_for(coro, timeout=None):
        coro.close()
        timeouts.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(scheduler, "add_dir", fake_add_dir)
    monkeypatch.setattr(scheduler.asyncio, "wait_for", fake_wait_for)

    asyncio.run(scheduler.periodic_ingest(stop))

    assert timeouts == [20.0, 40.0, 10.0]
