import asyncio
import threading
from app.services.events import EventBroadcaster


def test_slow_sse_subscriber_is_bounded_and_gets_resync():
    async def run():
        broadcaster = EventBroadcaster()
        queue = broadcaster.subscribe()
        for i in range(100):
            await broadcaster.broadcast("chain_updated", {"block": i})
        await asyncio.sleep(0)
        assert queue.qsize() == 64
        messages = [queue.get_nowait() for _ in range(64)]
        assert any("event: resync" in message for message in messages)
        broadcaster.unsubscribe(queue)
        broadcaster.unsubscribe(queue)

    asyncio.run(run())


def test_indexer_thread_notification_reaches_event_loop():
    async def run():
        broadcaster = EventBroadcaster()
        queue = broadcaster.subscribe()
        thread = threading.Thread(
            target=broadcaster.publish_from_thread,
            args=("chain_updated", {"indexed_block": 7}),
        )
        thread.start()
        thread.join()
        message = await asyncio.wait_for(queue.get(), timeout=1)
        assert "chain_updated" in message and "7" in message
        broadcaster.unsubscribe(queue)

    asyncio.run(run())
