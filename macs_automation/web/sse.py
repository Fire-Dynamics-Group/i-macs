"""SSE (Server-Sent Events) broadcaster for real-time updates.

Bridges sync batch runner callbacks to async SSE streams served by FastAPI.
"""

import asyncio
import json
from typing import Optional


class SSEBroadcaster:
    """Manages SSE subscriptions and broadcasts events to all connected clients.

    Thread-safe: use broadcast_threadsafe() from sync code (e.g., batch runner
    running in a background thread) to push events into the async event loop.
    """

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        """Create and return a new subscription queue."""
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        """Remove a subscription queue."""
        async with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    async def broadcast(self, event_type: str, data: dict):
        """Broadcast an event to all subscribers (call from async context)."""
        message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        async with self._lock:
            dead = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    dead.append(queue)
            for q in dead:
                self._subscribers.remove(q)

    def broadcast_threadsafe(self, event_type: str, data: dict,
                             loop: Optional[asyncio.AbstractEventLoop] = None):
        """Broadcast from a sync context (e.g., background thread).

        Uses loop.call_soon_threadsafe() to schedule the broadcast in the
        async event loop.
        """
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self.broadcast(event_type, data), loop
        )


# Module-level singleton
broadcaster = SSEBroadcaster()
