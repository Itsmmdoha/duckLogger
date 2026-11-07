"""Bounded UART companion transport for positive-security/send-my.

The modem protocol is deliberately one versioned NDJSON line per event.  The
channel has no acknowledgement, confidentiality, or authentication; callers
must treat delivery as advisory and payloads as public.
"""

import os

try:
    import ujson as json
except ImportError:
    import json


class SendMyQueue:
    def __init__(self, settings, uart=None):
        self.enabled = settings.sendmy_enabled
        self.modem_id = settings.sendmy_modem_id
        self.max_message_bytes = settings.sendmy_max_message_bytes
        self.max_pending = settings.sendmy_max_pending
        self.spool_path = settings.sendmy_spool_path
        self._uart = uart
        self.queue = []
        self.sent = 0
        self.dropped = 0
        self.errors = 0
        self._settings = settings
        self._load()

    def _load(self):
        if not self.enabled:
            return
        try:
            with open(self.spool_path, "r") as spool:
                saved = json.load(spool)
            if isinstance(saved, list):
                self.queue = saved[-self.max_pending:]
        except (OSError, ValueError):
            self.queue = []

    def _save(self):
        if not self.enabled:
            return
        temporary = self.spool_path + ".tmp"
        try:
            with open(temporary, "w") as spool:
                spool.write(json.dumps(self.queue))
            try:
                os.remove(self.spool_path)
            except OSError:
                pass
            os.rename(temporary, self.spool_path)
        except OSError:
            self.errors += 1

    def _line(self, record):
        event = {
            "v": 1,
            "m": self.modem_id,
            "n": record.get("network_id", record.get("n", "")),
            "i": record.get("implant_id", record.get("source_id", record.get("s", ""))),
            "b": record.get("boot_id", record.get("b", "")),
            "q": record.get("sequence", record.get("q", 0)),
            "k": record.get("kind", record.get("k", "")),
            "x": record.get("value", record.get("x", "")),
        }
        try:
            encoded = json.dumps(event, separators=(",", ":")).encode("utf-8")
        except TypeError:
            encoded = json.dumps(event).encode("utf-8")
        if len(encoded) > self.max_message_bytes:
            raise ValueError("Send My message exceeds configured byte limit")
        return encoded + b"\n"

    def enqueue(self, record):
        if not self.enabled or record is None:
            return False
        # Validate before mutating the persistent queue.
        self._line(record)
        if len(self.queue) >= self.max_pending:
            self.queue.pop(0)
            self.dropped += 1
        self.queue.append(record)
        self._save()
        return True

    def _get_uart(self):
        if self._uart is None:
            from machine import UART, Pin
            self._uart = UART(
                self._settings.sendmy_uart_id,
                baudrate=self._settings.sendmy_baudrate,
                tx=Pin(self._settings.sendmy_tx_pin),
                rx=Pin(self._settings.sendmy_rx_pin),
            )
        return self._uart

    def flush_one(self):
        if not self.enabled or not self.queue:
            return False
        try:
            written = self._get_uart().write(self._line(self.queue[0]))
            if not written:
                raise OSError("Send My modem UART accepted no bytes")
        except (OSError, ValueError):
            self.errors += 1
            return False
        self.queue.pop(0)
        self.sent += 1
        self._save()
        return True

    def status(self):
        return {
            "enabled": self.enabled,
            "modem_id": self.modem_id,
            "pending": len(self.queue),
            "sent": self.sent,
            "dropped": self.dropped,
            "errors": self.errors,
        }
