"""Bounded UART companion transport for positive-security/send-my.

The modem protocol uses one versioned NDJSON line per batch.  A single event is
encoded as a v1 record; two or more events are encoded as a compact v2 batch.
The channel has no acknowledgement, confidentiality, or authentication; callers
must treat delivery as advisory and payloads as public.
"""

import os
import time

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
        self.batch_interval_ms = max(
            0, int(getattr(settings, "sendmy_batch_interval_ms", 60000))
        )
        self.batch_size = max(1, int(getattr(settings, "sendmy_batch_size", 32)))
        self._uart = uart
        self.queue = []
        self.sent = 0
        self.events_sent = 0
        self.dropped = 0
        self.errors = 0
        self._settings = settings
        self._last_flush_ms = None
        self._load()

    def _now_ms(self):
        try:
            return time.ticks_ms()
        except AttributeError:
            return int(time.time() * 1000)

    def _diff_ms(self, left, right):
        try:
            return time.ticks_diff(left, right)
        except AttributeError:
            return left - right

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

    def _identity(self, record):
        return (
            record.get("network_id", record.get("n", "")),
            record.get("implant_id", record.get(
                "source_id", record.get("s", record.get("source", ""))
            )),
            record.get("boot_id", record.get("b", "legacy")),
            int(record.get("sequence", record.get("q", 0))),
            record.get("kind", record.get("k", "")),
            record.get("value", record.get("x", "")),
        )

    def _single(self, record):
        network, source, boot, sequence, kind, value = self._identity(record)
        return {
            "v": 1,
            "m": self.modem_id,
            "n": network,
            "i": source,
            "b": boot,
            "q": sequence,
            "k": kind,
            "x": value,
        }

    def _batch(self, records):
        entries = []
        network = ""
        for record in records:
            record_network, source, boot, sequence, kind, value = (
                self._identity(record)
            )
            if not network:
                network = record_network
            entries.append([source, boot, sequence, kind, value])
        return {
            "v": 2,
            "m": self.modem_id,
            "n": network,
            "k": "batch",
            "e": entries,
        }

    def _encode(self, records):
        if not records:
            raise ValueError("Send My batch is empty")
        if len(records) == 1:
            event = self._single(records[0])
        else:
            event = self._batch(records)
        try:
            encoded = json.dumps(event, separators=(",", ":")).encode("utf-8")
        except TypeError:
            encoded = json.dumps(event).encode("utf-8")
        if len(encoded) > self.max_message_bytes:
            raise ValueError("Send My message exceeds configured byte limit")
        return encoded + b"\n"

    def _select_batch(self):
        limit = min(len(self.queue), self.batch_size)
        while limit > 0:
            records = self.queue[:limit]
            try:
                return records, self._encode(records)
            except ValueError:
                limit -= 1
        return None, None

    def enqueue(self, record, now_ms=None):
        if not self.enabled or record is None:
            return False
        # Validate the single-record form before mutating the persistent queue.
        self._encode([record])
        if self._last_flush_ms is None:
            self._last_flush_ms = (
                self._now_ms() if now_ms is None else now_ms
            )
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

    def _write(self, records, line, now_ms=None):
        try:
            written = self._get_uart().write(line)
            if not written:
                raise OSError("Send My modem UART accepted no bytes")
        except (OSError, ValueError):
            self.errors += 1
            return False
        del self.queue[:len(records)]
        self.sent += 1
        self.events_sent += len(records)
        self._last_flush_ms = (
            self._now_ms() if now_ms is None else now_ms
        )
        self._save()
        return True

    def flush_one(self, now_ms=None):
        if not self.enabled or not self.queue:
            return False
        records = self.queue[:1]
        try:
            line = self._encode(records)
        except ValueError:
            self.errors += 1
            return False
        return self._write(records, line, now_ms)

    def _flush_batch(self, now_ms=None):
        records, line = self._select_batch()
        if records is None:
            self.errors += 1
            return False
        return self._write(records, line, now_ms)

    def flush_due(self, now_ms=None):
        """Send one timed batch when the configured interval has elapsed."""
        if not self.enabled or not self.queue:
            return False
        if now_ms is None:
            now_ms = self._now_ms()
        if self._last_flush_ms is None:
            self._last_flush_ms = now_ms
            return False
        if self._diff_ms(now_ms, self._last_flush_ms) < self.batch_interval_ms:
            return False
        result = self._flush_batch(now_ms)
        self._last_flush_ms = now_ms
        return result

    def status(self):
        return {
            "enabled": self.enabled,
            "modem_id": self.modem_id,
            "pending": len(self.queue),
            "sent": self.sent,
            "events_sent": self.events_sent,
            "dropped": self.dropped,
            "errors": self.errors,
            "batch_interval_ms": self.batch_interval_ms,
            "batch_size": self.batch_size,
        }
