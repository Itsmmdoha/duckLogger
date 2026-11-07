import json

import pytest

from sendmy import SendMyQueue


class Settings:
    sendmy_enabled = True
    sendmy_modem_id = "42424242"
    sendmy_max_message_bytes = 180
    sendmy_max_pending = 2
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


def event(sequence=1, value="a"):
    return {"network_id": "lab", "implant_id": "implant-a", "boot_id": "boot",
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
