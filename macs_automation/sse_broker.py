"""In-memory pub/sub broker for sweep events.

Bridges the synchronous sweep worker thread (publisher) and async HTTP request
handlers (subscribers, served via Server-Sent Events). Each subscriber gets its
own bounded asyncio.Queue. publish() is thread-safe and never blocks the
worker — if a subscriber's queue is full, the oldest queued event is dropped
to make room for the new one.

Public interface:
    Broker.publish(event)               — sync, callable from any thread
    Broker.subscribe()                  — async iterator over events
    Broker.shutdown()                   — close all subscribers cleanly
    Broker.subscriber_count             — number of active subscriptions

Used by app.py: a single module-level Broker instance is shared between the
worker thread (publishes run_completed and batch_done) and the SSE endpoint
(opens one subscription per HTTP connection).
"""

from __future__ import annotations

import asyncio
import threading
from typing import AsyncIterator, Optional


class Broker:
    DEFAULT_QUEUE_MAXSIZE = 256

    def __init__(self, queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE):
        self._queue_maxsize = queue_maxsize
        self._subscribers: list[asyncio.Queue] = []
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: dict) -> None:
        """Publish an event to every active subscriber. Thread-safe.

        For each subscriber's queue: schedule put_nowait via the loop. If the
        queue is full, drop the oldest queued event and retry — the publisher
        never blocks on a slow consumer.
        """
        with self._lock:
            subs = list(self._subscribers)
            loop = self._loop
        if not subs:
            return
        for q in subs:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(self._safe_put, q, event)
            else:
                self._safe_put(q, event)

    @staticmethod
    def _safe_put(queue: asyncio.Queue, event: object) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> AsyncIterator[dict]:
        """Yield events as they arrive on this subscription. Iteration ends
        when shutdown() is called (None sentinel) or the consumer breaks."""
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._loop = loop
            self._subscribers.append(q)
        try:
            while True:
                event = await q.get()
                if event is None:
                    return
                yield event
        finally:
            with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)

    def shutdown(self) -> None:
        """Send the close sentinel to every subscriber, ending their streams."""
        with self._lock:
            subs = list(self._subscribers)
            loop = self._loop
        for q in subs:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(self._safe_put, q, None)
            else:
                self._safe_put(q, None)
