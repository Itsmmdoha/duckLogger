"""Reliable message layer over an SX1262 packet radio."""

import time
try:
    import ujson as json
except ImportError:
    import json

from lora_frame import (TYPE_ACK, TYPE_DATA, decode_ack, decode_frame,
                        encode_ack, fragment_message)


def _now_ms():
    try: return time.ticks_ms()
    except AttributeError: return int(time.time() * 1000)


class LoRaLink:
    def __init__(self, radio, key, session=None, ack_timeout_ms=1500,
                 max_retries=3, reassembly_timeout_ms=15000):
        self.radio, self.key = radio, key
        self.session = session if session is not None else (_now_ms() & 0xffffffff)
        self.ack_timeout_ms, self.max_retries = ack_timeout_ms, max_retries
        self.reassembly_timeout_ms = reassembly_timeout_ms
        self.sequence = 0
        self.pending, self.incoming, self.completed = {}, {}, []
        self.send_results = []
        self.auth_errors = self.dropped = self.retries = self.duplicates = 0

    def send_records(self, records, gateway_id="gateway-01", topology=None):
        self.sequence = (self.sequence + 1) & 0xffff
        document = {"schema": 1, "gateway_id": gateway_id, "records": records}
        if topology is not None: document["topology"] = topology
        payload = json.dumps(document).encode("utf-8")
        frames = fragment_message(payload, self.key, self.session, self.sequence)
        state = {"frames": frames, "received": set(), "attempts": 0,
                 "last_send_ms": 0}
        self.pending[(self.session, self.sequence)] = state
        self._send_missing(state)
        return self.sequence

    def _send_missing(self, state):
        for index, frame in enumerate(state["frames"]):
            if index not in state["received"]:
                # SX1262 is half-duplex. Send one fragment and leave the radio
                # in RX for its bitmap ACK before advancing to the next one.
                self.radio.send(frame)
                break
        state["attempts"] += 1; state["last_send_ms"] = _now_ms()

    def poll(self, now_ms=None):
        now_ms = _now_ms() if now_ms is None else now_ms
        raw = self.radio.recv()
        while raw is not None:
            try: frame = decode_frame(raw, self.key)
            except ValueError: self.auth_errors += 1; frame = None
            if frame is not None:
                if frame["type"] == TYPE_ACK: self._handle_ack(frame)
                elif frame["type"] == TYPE_DATA: self._handle_data(frame, now_ms)
            raw = self.radio.recv()
        for key, state in list(self.pending.items()):
            if len(state["received"]) == len(state["frames"]):
                del self.pending[key]; self.send_results.append((key[1], True)); continue
            if now_ms - state["last_send_ms"] >= self.ack_timeout_ms:
                if state["attempts"] > self.max_retries:
                    self.dropped += 1; del self.pending[key]; self.send_results.append((key[1], False))
                else: self.retries += 1; self._send_missing(state)
        for key, state in list(self.incoming.items()):
            if now_ms - state["updated_ms"] > self.reassembly_timeout_ms:
                self.dropped += 1; del self.incoming[key]

    def _handle_ack(self, frame):
        state = self.pending.get((frame["session"], frame["message_seq"]))
        if state is not None:
            previous = len(state["received"])
            state["received"].update(decode_ack(frame, len(state["frames"])))
            if (len(state["received"]) > previous and
                    len(state["received"]) < len(state["frames"])):
                state["attempts"] = 0
                self._send_missing(state)

    def _handle_data(self, frame, now_ms):
        key = (frame["session"], frame["message_seq"])
        state = self.incoming.get(key)
        if state is None:
            state = {"total": frame["total"], "parts": {}, "updated_ms": now_ms}
            self.incoming[key] = state
        if state["total"] != frame["total"]: self.dropped += 1; return
        if frame["fragment"] in state["parts"]: self.duplicates += 1
        state["parts"][frame["fragment"]] = frame["payload"]; state["updated_ms"] = now_ms
        self.radio.send(encode_ack(self.key, frame["session"], frame["message_seq"],
                                   state["total"], state["parts"].keys()))
        if len(state["parts"]) == state["total"]:
            payload = b"".join(state["parts"][index] for index in range(state["total"]))
            try: document = json.loads(payload.decode("utf-8"))
            except (ValueError, UnicodeError): self.dropped += 1
            else: self.completed.append((frame["session"], frame["message_seq"], document))
            del self.incoming[key]

    def receive(self):
        return self.completed.pop(0) if self.completed else None

    def next_send_result(self):
        return self.send_results.pop(0) if self.send_results else None

    def status(self):
        state = self.radio.status()
        state.update({"session": self.session, "pending": len(self.pending),
                      "reassembling": len(self.incoming), "auth_errors": self.auth_errors,
                      "dropped": self.dropped, "retries": self.retries,
                      "duplicates": self.duplicates})
        return state
