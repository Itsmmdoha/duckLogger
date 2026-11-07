import pytest

from lora_frame import decode_frame, fragment_message
from lora_link import LoRaLink

KEY = b"unit-test-lora-auth-key-value-01"


class Radio:
    def __init__(self): self.tx, self.rx = [], []
    def send(self, value): self.tx.append(value)
    def recv(self): return self.rx.pop(0) if self.rx else None
    def status(self): return {"rssi": -80, "snr": 7}


def test_fragment_round_trip_and_authentication():
    payload = b"x" * 600
    frames = fragment_message(payload, KEY, 12, 4)
    decoded = [decode_frame(frame, KEY) for frame in frames]
    assert b"".join(item["payload"] for item in decoded) == payload
    damaged = bytearray(frames[0]); damaged[-1] ^= 1
    with pytest.raises(ValueError, match="authentication"):
        decode_frame(bytes(damaged), KEY)


def test_links_reassemble_and_ack_a_batch():
    sender_radio, receiver_radio = Radio(), Radio()
    sender = LoRaLink(sender_radio, KEY, session=123)
    receiver = LoRaLink(receiver_radio, KEY, session=456)
    sender.send_records([{"source": "node-1", "sequence": 1, "kind": "heartbeat", "value": 1}])
    receiver_radio.rx.extend(sender_radio.tx); sender_radio.tx.clear()
    receiver.poll(now_ms=100)
    message = receiver.receive()
    assert message[0:2] == (123, 1)
    assert message[2]["records"][0]["kind"] == "heartbeat"
    sender_radio.rx.extend(receiver_radio.tx)
    sender.poll(now_ms=200)
    assert sender.pending == {}


def test_multifragment_link_waits_for_each_ack():
    sender_radio, receiver_radio = Radio(), Radio()
    sender = LoRaLink(sender_radio, KEY, session=123)
    receiver = LoRaLink(receiver_radio, KEY, session=456)
    sender.send_records([{"source": "node-1", "sequence": 1,
                          "kind": "key_event", "value": "x" * 600}])
    assert len(sender_radio.tx) == 1

    cycles = 0
    while sender.pending and cycles < 10:
        receiver_radio.rx.extend(sender_radio.tx)
        sender_radio.tx.clear()
        receiver.poll(now_ms=100 + cycles)
        sender_radio.rx.extend(receiver_radio.tx)
        receiver_radio.tx.clear()
        sender.poll(now_ms=200 + cycles)
        assert len(sender_radio.tx) <= 1
        cycles += 1

    assert sender.pending == {}
    assert receiver.receive()[2]["records"][0]["value"] == "x" * 600


def test_wrong_key_is_counted_not_delivered():
    radio = Radio(); link = LoRaLink(radio, b"different-unit-test-lora-key-02")
    radio.rx.extend(fragment_message(b"{}", KEY, 1, 1))
    link.poll(now_ms=0)
    assert link.auth_errors == 1
    assert link.receive() is None
