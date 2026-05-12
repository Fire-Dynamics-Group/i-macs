"""Tests for sse_broker — pub/sub for sweep events.

The broker is the deep-module bridge between the synchronous sweep worker
thread (which produces events) and async HTTP request handlers (which stream
them as SSE). Tests cover externally-observable behaviour: subscribers receive
what is published, slow subscribers drop instead of backpressuring publishers,
and shutdown closes streams cleanly.
"""

import asyncio
import threading

import pytest

from macs_automation.sse_broker import Broker


@pytest.mark.asyncio
async def test_single_subscriber_receives_published_event():
    broker = Broker()
    received = []

    async def collect():
        async for event in broker.subscribe():
            received.append(event)
            if event.get("type") == "stop":
                return

    task = asyncio.create_task(collect())
    # Yield once so subscribe() registers before we publish.
    await asyncio.sleep(0)

    broker.publish({"type": "run_completed", "id": 1, "uf_max": 0.7})
    broker.publish({"type": "stop"})

    await asyncio.wait_for(task, timeout=1.0)
    assert received == [
        {"type": "run_completed", "id": 1, "uf_max": 0.7},
        {"type": "stop"},
    ]


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive_event():
    broker = Broker()
    a_events: list[dict] = []
    b_events: list[dict] = []

    async def collect(into):
        async for event in broker.subscribe():
            into.append(event)
            if event.get("type") == "stop":
                return

    task_a = asyncio.create_task(collect(a_events))
    task_b = asyncio.create_task(collect(b_events))
    await asyncio.sleep(0)

    broker.publish({"type": "run_completed", "id": 7})
    broker.publish({"type": "stop"})

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)
    assert a_events == [{"type": "run_completed", "id": 7}, {"type": "stop"}]
    assert b_events == [{"type": "run_completed", "id": 7}, {"type": "stop"}]


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_is_noop():
    """Publishing before anyone subscribes must not raise."""
    broker = Broker()
    broker.publish({"type": "run_completed", "id": 1})  # should not error


@pytest.mark.asyncio
async def test_subscriber_removed_after_iteration_finishes():
    broker = Broker()
    received: list[dict] = []

    async def collect_one():
        async for event in broker.subscribe():
            received.append(event)
            return  # exit after first

    task = asyncio.create_task(collect_one())
    await asyncio.sleep(0)
    broker.publish({"type": "run_completed", "id": 1})
    await asyncio.wait_for(task, timeout=1.0)

    assert broker.subscriber_count == 0


def test_safe_put_drops_oldest_when_queue_full():
    """Drop policy: when the queue is full, _safe_put removes the oldest event
    and inserts the new one. After many puts the queue holds the most recent
    items, never raises QueueFull, and never blocks. This is the property that
    keeps the publisher from being backpressured by a slow subscriber."""
    q: asyncio.Queue = asyncio.Queue(maxsize=2)
    for i in range(5):
        Broker._safe_put(q, i)
    assert q.qsize() == 2
    assert q.get_nowait() == 3
    assert q.get_nowait() == 4


@pytest.mark.asyncio
async def test_publish_from_worker_thread():
    """publish() is called from sweep worker threads in production. Subscribers
    on the asyncio loop must still receive events."""
    broker = Broker()
    received: list[dict] = []

    async def collect():
        async for event in broker.subscribe():
            received.append(event)
            if event.get("type") == "stop":
                return

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)

    def worker():
        broker.publish({"type": "run_completed", "id": 99})
        broker.publish({"type": "stop"})

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    await asyncio.wait_for(task, timeout=1.0)
    t.join(timeout=1.0)

    assert received == [
        {"type": "run_completed", "id": 99},
        {"type": "stop"},
    ]


@pytest.mark.asyncio
async def test_shutdown_closes_all_subscribers():
    broker = Broker()
    a_done = asyncio.Event()
    b_done = asyncio.Event()

    async def consumer(done):
        async for _event in broker.subscribe():
            pass  # broker.shutdown() will end the iteration
        done.set()

    task_a = asyncio.create_task(consumer(a_done))
    task_b = asyncio.create_task(consumer(b_done))
    await asyncio.sleep(0)

    broker.shutdown()

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)
    assert a_done.is_set() and b_done.is_set()
    assert broker.subscriber_count == 0
