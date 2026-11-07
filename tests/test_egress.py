from egress import Egress, GatewayEgress
import json


class Settings:
    egress_enabled = True
    egress_backend = "log"
    egress_url = ""
    egress_batch_size = 2
    egress_interval_ms = 500
    egress_max_pending = 2
    egress_lora_uart = 2
    egress_lora_tx = 17
    egress_lora_rx = 18
    egress_lora_baudrate = 9600
    egress_spool_path = "mesh-egress.json"
    egress_retry_base_ms = 100
    egress_retry_max_ms = 800
    egress_backends = ["log"]
    sendmy_enabled = False
    sendmy_batch_interval_ms = 0
    sendmy_batch_size = 32


def test_disabled_egress_drops_nothing_into_queue():
    settings = Settings()
    settings.egress_enabled = False
    egress = Egress(settings)
    egress.enqueue({"value": "a"})
    assert egress.queue == []


def test_egress_batches_and_counts_sent(tmp_path):
    settings = Settings()
    settings.egress_spool_path = str(tmp_path / "spool.json")
    egress = Egress(settings)
    egress.enqueue({"value": "a"})
    egress.enqueue({"value": "b"})
    egress.enqueue({"value": "c"})
    assert egress.dropped == 1
    assert len(egress.queue) == 2
    egress.flush()
    assert egress.sent == 2
    assert egress.queue == []
    assert json.loads((tmp_path / "spool.json").read_text()) == []


def test_failed_batch_is_persisted_and_backed_off(tmp_path):
    settings = Settings()
    settings.egress_spool_path = str(tmp_path / "spool.json")
    egress = Egress(settings)
    egress.enqueue({"value": "a"})

    def fail(_batch):
        raise OSError("offline")

    egress._send = fail
    egress.flush(now_ms=1000)
    assert egress.queue == [{"value": "a"}]
    assert egress.retry_count == 1
    assert egress.next_retry_ms == 1100
    egress.flush(now_ms=1050)
    assert egress.failed == 1
    assert json.loads((tmp_path / "spool.json").read_text()) == egress.queue

    restored = Egress(settings)
    assert restored.queue == [{"value": "a"}]


def test_corrupt_spool_does_not_prevent_startup(tmp_path):
    spool = tmp_path / "spool.json"
    spool.write_text("not-json")
    settings = Settings()
    settings.egress_spool_path = str(spool)
    assert Egress(settings).queue == []


def test_lora_queue_is_removed_only_after_radio_ack(tmp_path):
    class Link:
        def __init__(self): self.results, self.sent = [], []
        def send_records(self, batch, gateway): self.sent.append((batch, gateway))
        def next_send_result(self): return self.results.pop(0) if self.results else None
        def status(self): return {}
        def poll(self): pass

    settings = Settings(); settings.egress_backend = "lora"
    settings.egress_spool_path = str(tmp_path / "spool.json")
    settings.node_id = "gateway-01"
    link = Link(); egress = Egress(settings, lora_link=link)
    egress.enqueue({"value": "a"}); egress.flush(now_ms=1000)
    assert len(egress.queue) == 1
    egress.flush(now_ms=1001)
    assert len(egress.queue) == 1
    link.results.append((1, True)); egress.flush(now_ms=1002)
    assert egress.queue == []
    assert egress.sent == 1


def test_manager_fans_out_to_independent_backends(tmp_path):
    settings = Settings()
    settings.egress_backends = ["log", "sendmy"]
    settings.egress_spool_path = str(tmp_path / "egress.json")
    settings.sendmy_modem_id = "42424242"
    settings.sendmy_max_message_bytes = 180
    settings.sendmy_max_pending = 8
    settings.sendmy_spool_path = str(tmp_path / "sendmy.json")
    settings.sendmy_uart_id = 1
    settings.sendmy_baudrate = 115200
    settings.sendmy_tx_pin = 17
    settings.sendmy_rx_pin = 18

    class UART:
        def write(self, line): return len(line)

    manager = GatewayEgress(settings, sendmy_uart=UART())
    manager.enqueue({"network_id": "lab", "implant_id": "node-1",
                     "boot_id": "boot", "sequence": 1,
                     "kind": "key_event", "value": "a"})
    assert all(len(backend.queue) == 1 for backend in manager.backends.values())
    manager.flush()
    assert all(len(backend.queue) == 0 for backend in manager.backends.values())


def test_manager_sendmy_waits_for_interval(tmp_path):
    settings = Settings()
    settings.egress_backends = ["sendmy"]
    settings.egress_spool_path = str(tmp_path / "egress.json")
    settings.sendmy_modem_id = "42424242"
    settings.sendmy_max_message_bytes = 180
    settings.sendmy_max_pending = 8
    settings.sendmy_batch_interval_ms = 60000
    settings.sendmy_spool_path = str(tmp_path / "sendmy.json")
    settings.sendmy_uart_id = 1
    settings.sendmy_baudrate = 115200
    settings.sendmy_tx_pin = 17
    settings.sendmy_rx_pin = 18

    class UART:
        def __init__(self): self.lines = []
        def write(self, line):
            self.lines.append(line)
            return len(line)

    uart = UART()
    manager = GatewayEgress(settings, sendmy_uart=uart)
    manager.enqueue({"network_id": "lab", "source": "node-1",
                     "boot_id": "boot", "sequence": 1,
                     "kind": "key_event", "value": "a"})
    backend = manager.backends["sendmy"]
    backend._last_flush_ms = 1000
    manager.flush(now_ms=2000)
    assert len(backend.queue) == 1
    assert uart.lines == []
    manager.flush(now_ms=61000)
    assert backend.queue == []
    assert len(uart.lines) == 1
