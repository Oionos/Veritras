"""Bounded SSE subscriptions; indexer notifications cross the thread boundary."""

import asyncio
import json
import threading
from app.services.operations import operations


class EventBroadcaster:
    def __init__(self):
        self._queues = {}
        self._lock = threading.Lock()

    def subscribe(self):
        queue = asyncio.Queue(maxsize=64)
        with self._lock:
            self._queues[queue] = asyncio.get_running_loop()
        operations.stream("opened")
        return queue

    def unsubscribe(self, queue):
        with self._lock:
            removed = self._queues.pop(queue, None)
        if removed is not None:
            operations.stream("closed")

    @staticmethod
    def _put(queue, message):
        if queue.full():
            operations.stream("overflows")
            queue.get_nowait()
            message = "event: resync\ndata: {}\n\n"
            operations.stream("resyncs")
        queue.put_nowait(message)

    def publish_from_thread(self, event_type, data):
        message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            subscriptions = list(self._queues.items())
        for queue, loop in subscriptions:
            if not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(self._put, queue, message)
                except RuntimeError:
                    self.unsubscribe(queue)

    async def broadcast(self, event_type, data):
        self.publish_from_thread(event_type, data)


broadcaster = EventBroadcaster()


def chain_revision():
    """Database polling also observes commits from another API worker/process."""
    from app.core.database import SessionLocal
    from app.models.chain import IndexerCursor

    with SessionLocal() as db:
        return "|".join(
            f"{row.scope}:{row.updated_at.isoformat()}"
            for row in db.query(IndexerCursor).order_by(IndexerCursor.scope)
        )
