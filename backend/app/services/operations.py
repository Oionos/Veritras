"""Bounded process-local operational counters. No identities, payloads or tokens."""

from collections import Counter, deque
import threading
import time


class Operations:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.lock = threading.Lock()
        self.requests = deque(maxlen=15)
        self.browser = Counter()
        self.streams = Counter(
            active=0, opened=0, closed=0, failures=0, resyncs=0, overflows=0
        )

    def request(self, *, status, duration_ms, business=True):
        with self.lock:
            minute = int(self.clock() // 60)
            if not self.requests or self.requests[-1][0] != minute:
                self.requests.append((minute, Counter()))
            counts = self.requests[-1][1]
            counts["requests"] += 1
            counts["duration_ms"] += max(0, duration_ms)
            if business:
                counts["api_requests"] += 1
                counts["api_5xx"] += int(status >= 500)
            for limit in (100, 500, 2000):
                counts[f"le_{limit}_ms"] += int(duration_ms <= limit)

    def stream(self, event):
        assert event in {"opened", "closed", "failures", "resyncs", "overflows"}
        with self.lock:
            self.streams[event] += 1
            if event == "opened":
                self.streams["active"] += 1
            if event == "closed":
                self.streams["active"] = max(0, self.streams["active"] - 1)

    def browser_metric(self, metric, route, value):
        # Both metric/route come from bounded enums validated by the API schema.
        with self.lock:
            key = (metric, route)
            self.browser[key] += 1
            self.browser[(metric, route, "sum")] += value

    def snapshot(self):
        with self.lock:
            minimum = int(self.clock() // 60) - 14
            counts = Counter()
            for minute, values in self.requests:
                if minute >= minimum:
                    counts.update(values)
            browser = [
                dict(
                    metric=key[0],
                    route=key[1],
                    count=value,
                    mean=round(self.browser[(*key, "sum")] / value, 2),
                )
                for key, value in self.browser.items()
                if len(key) == 2 and value
            ]
            return dict(
                window_seconds=900,
                uptime_seconds=int(self.clock() - self.started),
                requests=int(counts["requests"]),
                api_requests=int(counts["api_requests"]),
                api_5xx=int(counts["api_5xx"]),
                mean_duration_ms=(
                    round(counts["duration_ms"] / counts["requests"], 2)
                    if counts["requests"]
                    else None
                ),
                duration_buckets={
                    f"le_{limit}_ms": int(counts[f"le_{limit}_ms"])
                    for limit in (100, 500, 2000)
                },
                streams=dict(self.streams),
                browser_metrics=browser,
                storage="process_memory",
                reset_on_restart=True,
            )


operations = Operations()
