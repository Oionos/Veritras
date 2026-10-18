"""A bounded, single-flight database health probe.

One daemon probe can be in flight per process. Slow/unreachable databases cannot
queue unbounded connection attempts, block HTTP responses or delay shutdown.
"""

from concurrent.futures import Future, TimeoutError
import threading


class DatabaseProbe:
    def __init__(self, check):
        self._check = check
        self._lock = threading.Lock()
        self._pending = None

    def _run(self, future):
        try:
            self._check()
        except Exception:
            future.set_result("disconnected")
        else:
            future.set_result("connected")

    def status(self, timeout):
        with self._lock:
            if self._pending is None or self._pending.done():
                self._pending = Future()
                threading.Thread(
                    target=self._run,
                    args=(self._pending,),
                    name="database-health",
                    daemon=True,
                ).start()
            pending = self._pending
        try:
            return pending.result(timeout=timeout)
        except TimeoutError:
            return "timed_out"
