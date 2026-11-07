import json

import pytest

from sendmy import SendMyQueue


class Settings:
    sendmy_enabled = True
    sendmy_modem_id = "42424242"
    sendmy_max_message_bytes = 180
    sendmy_max_pending = 2
    sendmy_batch_interval_ms = 5000
    sendmy_batch_size = 32
    sendmy_spool_path = "unused.json"
    sendmy_uart_id = 1
    sendmy_baudrate = 115200
    sendmy_tx_pin = 17
    sendmy_rx_pin = 18


class UART:
    def __init__(self, result=True):
        self.lines = []
        self.result = result

    def write(self, line):
        self.lines.append(line)
        return len(line) if self.result else 0


def queue(tmp_path, uart=None):
    settings = Settings()
    settings.sendmy_spool_path = str(tmp_path / "sendmy.json")
    return SendMyQueue(settings, uart=uart)


def event(sequence=1, value="a", implant="implant-a", boot="boot"):
    return {"network_id": "lab", "implant_id": implant, "boot_id": boot,
            "sequence": sequence, "kind": "key_event", "value": value}


def test_sendmy_writes_versioned_ndjson_and_removes_on_success(tmp_path):
    uart = UART()
    sender = queue(tmp_path, uart)
    assert sender.enqueue(event()) is True
    assert sender.flush_one() is True
    payload = json.loads(uart.lines[0])
    assert payload["v"] == 1
    assert payload["i"] == "implant-a"
    assert sender.status()["pending"] == 0


def test_sendmy_queue_is_bounded_and_persisted(tmp_path):
    sender = queue(tmp_path, UART())
    sender.enqueue(event(1)); sender.enqueue(event(2)); sender.enqueue(event(3))
    assert [item["sequence"] for item in sender.queue] == [2, 3]
    assert sender.dropped == 1
    reloaded = queue(tmp_path, UART())
    assert [item["sequence"] for item in reloaded.queue] == [2, 3]


def test_sendmy_retains_event_when_uart_fails(tmp_path):
    sender = queue(tmp_path, UART(False))
    sender.enqueue(event())
    assert sender.flush_one() is False
    assert len(sender.queue) == 1
    assert sender.errors == 1


def test_sendmy_rejects_oversized_event(tmp_path):
    sender = queue(tmp_path, UART())
    with pytest.raises(ValueError, match="byte limit"):
        sender.enqueue(event(value="x" * 300))


def test_sendmy_waits_for_configured_interval(tmp_path):
    uart = UART()
    sender = queue(tmp_path, uart)
    sender.enqueue(event(1), now_ms=1000)
    assert sender.flush_due(now_ms=5999) is False
    assert sender.queue[0]["sequence"] == 1
    assert sender.flush_due(now_ms=6000) is True
    assert len(uart.lines) == 1
    assert sender.status()["pending"] == 0


def test_sendmy_batches_multiple_events_in_one_message(tmp_path):
    uart = UART()
    sender = queue(tmp_path, uart)
    sender.batch_interval_ms = 0
    sender.enqueue(event(1, "a"), now_ms=1000)
    sender.enqueue(event(2, "b"), now_ms=1000)
    assert sender.flush_due(now_ms=1000) is True
    assert len(uart.lines) == 1
    payload = json.loads(uart.lines[0])
    assert payload["v"] == 2
    assert payload["k"] == "batch"
    assert [item[4] for item in payload["e"]] == ["a", "b"]
    assert sender.status()["events_sent"] == 2
    assert sender.status()["sent"] == 1


def test_sendmy_batch_honors_size_limits(tmp_path):
    uart = UART()
    sender = queue(tmp_path, uart)
    sender.batch_interval_ms = 0
    sender.max_pending = 8
    sender.batch_size = 2
    for sequence in range(1, 4):
        sender.enqueue(event(sequence, str(sequence)), now_ms=0)
    assert sender.flush_due(now_ms=0) is True
    payload = json.loads(uart.lines[0])
    assert len(payload["e"]) == 2
    assert sender.status()["pending"] == 1
    assert sender.flush_due(now_ms=1) is True
    single = json.loads(uart.lines[1])
    assert single["v"] == 1
    assert single["q"] == 3


def test_sendmy_batch_preserves_gateway_sources(tmp_path):
    uart = UART()
    sender = queue(tmp_path, uart)
    sender.batch_interval_ms = 0
    sender.max_pending = 8
    sender.enqueue({
        "network_id": "lab", "source": "node-1", "boot_id": "boot-1",
        "sequence": 1, "kind": "key_event", "value": "a",
    }, now_ms=0)
    sender.enqueue({
        "network_id": "lab", "source": "node-2", "boot_id": "boot-2",
        "sequence": 1, "kind": "key_event", "value": "b",
    }, now_ms=0)
    assert sender.flush_due(now_ms=0) is True
    payload = json.loads(uart.lines[0])
    assert [item[0] for item in payload["e"]] == ["node-1", "node-2"]
    assert [item[1] for item in payload["e"]] == ["boot-1", "boot-2"]


def test_sendmy_does_not_send_empty_batches(tmp_path):
    uart = UART()
    sender = queue(tmp_path, uart)
    sender.batch_interval_ms = 0
    assert sender.flush_due(now_ms=0) is False
    assert uart.lines == []


def test_sendmy_shrinks_batch_to_fit_byte_limit(tmp_path):
    uart = UART()
    sender = queue(tmp_path, uart)
    sender.batch_interval_ms = 0
    sender.max_pending = 8
    sender.max_message_bytes = 110
    sender.enqueue(event(1, "a"), now_ms=0)
    sender.enqueue(event(2, "b"), now_ms=0)
    assert sender.flush_due(now_ms=0) is True
    assert len(uart.lines[0]) <= 111
    assert sender.status()["pending"] == 1
