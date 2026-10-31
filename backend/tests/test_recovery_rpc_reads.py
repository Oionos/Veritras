from types import SimpleNamespace
import json

import pytest

import replay_private_restore as replay


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(now=0.0, pauses=[])

    def sleep(delay):
        clock.pauses.append(delay)
        clock.now += delay

    monkeypatch.setattr(replay, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    return clock


def http_failure(status):
    error = RuntimeError("https://provider.example/private-key")
    error.response = SimpleNamespace(status_code=status)
    return error


@pytest.mark.parametrize("stage", ["worker_connection", "chain_head", "target_header",
                                  "fixed_target_header", "canonical_history_recheck"])
def test_required_rpc_reads_retry_transient_throttling_and_keep_their_result(clock, stage):
    calls = []

    def read():
        calls.append(True)
        if len(calls) < 3:
            raise http_failure(429)
        return "verified-result"

    assert replay.read_rpc(read, 20, stage=stage) == "verified-result"
    assert len(calls) == 3 and clock.pauses == [1, 2]


def test_persistent_header_throttling_fails_after_five_attempts_with_safe_diagnostics(clock):
    calls = []

    def header(number):
        calls.append(number)
        raise http_failure(429)

    with pytest.raises(replay.ReplayBlocked) as failure:
        replay.reconciliation_header(SimpleNamespace(_header=header), 123, 30)
    assert str(failure.value) == "reconciliation_rpc_failed"
    assert failure.value.diagnostics == {
        "rpc_stage": "reconciliation_header", "rpc_failure_kind": "http_error",
        "rpc_http_status": 429, "from_block": 123, "to_block": 123, "attempts": 5,
    }
    assert calls == [123] * 5 and clock.pauses == [1, 2, 4, 8]
    assert "private-key" not in json.dumps(failure.value.diagnostics)


@pytest.mark.parametrize("error", [http_failure(401), http_failure(403),
                                   ValueError({"code": -32000, "message": "historical state pruned private-key"})])
def test_permanent_rpc_access_and_history_failures_are_not_retried(clock, error):
    calls = []

    def read():
        calls.append(True)
        raise error

    with pytest.raises(replay.ReplayBlocked) as failure:
        replay.read_rpc(read, 20, stage="chain_head")
    assert len(calls) == 1 and not clock.pauses
    assert failure.value.diagnostics["attempts"] == 1
    assert "private-key" not in json.dumps(failure.value.diagnostics)


def test_rpc_retries_cannot_extend_the_recovery_deadline(clock):
    calls = []

    def read():
        calls.append(True)
        raise http_failure(429)

    with pytest.raises(replay.ReplayBlocked, match="private_rpc_timeout") as failure:
        replay.read_rpc(read, 1.5, stage="chain_head")
    assert len(calls) == 2 and clock.pauses == [1] and clock.now == 1
    assert failure.value.diagnostics["rpc_http_status"] == 429


def test_rpc_result_arriving_after_deadline_is_not_accepted(clock):
    def read():
        clock.now = 2
        return "valid-but-late"

    with pytest.raises(replay.ReplayBlocked, match="private_rpc_timeout"):
        replay.read_rpc(read, 1, stage="chain_head")
    assert not clock.pauses


@pytest.mark.parametrize("wrong_header", [False, True])
def test_event_inclusion_headers_remain_mandatory_after_throttling(monkeypatch, clock, wrong_header):
    from app.core.config import settings
    monkeypatch.setattr(settings, "indexer_start_block", 0)
    canonical = "0x" + "11" * 32
    fetches, headers, progress = [], [], []
    event = {"blockNumber": 3, "blockHash": bytes.fromhex("11" * 32)}
    worker = SimpleNamespace(_batch_size=8)

    def header(number):
        headers.append(number)
        if number == 3 and headers.count(3) == 1:
            raise http_failure(429)
        return "0x" + "22" * 32 if number == 3 and wrong_header else canonical

    def fetch(start, end):
        fetches.append((start, end))
        return [event]

    worker._header, worker._fetch_events = header, fetch
    if wrong_header:
        with pytest.raises(replay.ReplayBlocked, match="canonical_target_mismatch"):
            replay.confirmed_events(worker, 8, canonical, 30, progress=progress.append)
        assert not any(item["scan_state"] == "complete" for item in progress)
    else:
        assert replay.confirmed_events(worker, 8, canonical, 30, progress=progress.append) == [event]
        assert progress[-1]["scan_state"] == "complete" and progress[-1]["rpc_retries"] == 1
    assert fetches == [(1, 8)] and headers.count(3) == 2
    assert worker._batch_size == 8 and clock.pauses == [1]
