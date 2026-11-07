"""Gateway egress for MeshOps records.

Records are queued by MeshStore and flushed in batches to a configured
backend: a local log, an HTTP collector over Wi-Fi, or a serial LoRa bridge.
"""

import asyncio
import os
import time

try:
    import ujson as json
except ImportError:
    import json


class Egress:
    def __init__(self, settings, lora_link=None):
        self.settings = settings
        self.enabled = settings.egress_enabled
        self.backend = settings.egress_backend
        self.url = settings.egress_url
        self.batch_size = max(1, settings.egress_batch_size)
        self.interval_ms = max(500, settings.egress_interval_ms)
        self.max_pending = max(1, settings.egress_max_pending)
        self.spool_path = getattr(settings, "egress_spool_path", "mesh-egress.json")
        self.retry_base_ms = getattr(settings, "egress_retry_base_ms", 1000)
        self.retry_max_ms = getattr(settings, "egress_retry_max_ms", 60000)
        self.queue = []
        self.sent = 0
        self.failed = 0
        self.dropped = 0
        self._uart = None
        self.lora_link = lora_link
        self._lora_inflight = 0
        self.retry_count = 0
        self.next_retry_ms = 0
        self._load_spool()

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

    def _load_spool(self):
        if not self.enabled:
            return
        try:
            with open(self.spool_path, "r") as spool:
                records = json.load(spool)
            if isinstance(records, list):
                self.queue = records[-self.max_pending:]
        except (OSError, ValueError):
            self.queue = []

    def _save_spool(self):
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
        except OSError as exc:
            print("Egress spool persistence failed: %s" % exc)

    def enqueue(self, record):
        if not self.enabled or record is None:
            return
        if len(self.queue) >= self.max_pending:
            self.queue.pop(0)
            self.dropped += 1
        self.queue.append(record)
        self._save_spool()

    async def run(self):
        while True:
            if self.lora_link is not None:
                self.lora_link.poll()
            self.flush()
            await asyncio.sleep_ms(20 if self.backend == "lora" else self.interval_ms)

    def flush(self, now_ms=None):
        if not self.enabled or not self.queue:
            return
        if now_ms is None:
            now_ms = self._now_ms()
        if self.next_retry_ms and self._diff_ms(now_ms, self.next_retry_ms) < 0:
            return
        batch = self.queue[:self.batch_size]
        if self.backend == "lora":
            try:
                if self.lora_link is None:
                    from sx1262 import from_settings
                    from lora_link import LoRaLink
                    self.lora_link = LoRaLink(from_settings(self.settings), self.settings.lora_key,
                                              ack_timeout_ms=self.settings.lora_ack_timeout_ms,
                                              max_retries=self.settings.lora_max_retries)
                if self._lora_inflight:
                    result = self.lora_link.next_send_result()
                    if result is None:
                        return
                    if result[1]:
                        del self.queue[:self._lora_inflight]
                        self.sent += self._lora_inflight
                        self.retry_count = 0; self.next_retry_ms = 0
                    else:
                        self.failed += self._lora_inflight
                        self.retry_count += 1
                        delay = self.retry_base_ms * (2 ** min(self.retry_count - 1, 10))
                        self.next_retry_ms = now_ms + min(delay, self.retry_max_ms)
                    self._lora_inflight = 0; self._save_spool()
                    return
                self.lora_link.send_records(batch, self.settings.node_id)
                self._lora_inflight = len(batch)
            except Exception as exc:
                self.failed += len(batch); self.retry_count += 1
                self.next_retry_ms = now_ms + min(self.retry_base_ms, self.retry_max_ms)
                print("Egress failed: %s" % exc)
            return
        try:
            self._send(batch)
        except Exception as exc:
            self.failed += len(batch)
            self.retry_count += 1
            delay = self.retry_base_ms * (2 ** min(self.retry_count - 1, 10))
            self.next_retry_ms = now_ms + min(delay, self.retry_max_ms)
            print("Egress failed: %s" % exc)
            return
        del self.queue[:len(batch)]
        self.sent += len(batch)
        self.retry_count = 0
        self.next_retry_ms = 0
        self._save_spool()

    def _send(self, batch):
        if self.backend == "none":
            return
        if self.backend == "log":
            for record in batch:
                print("EGRESS %s" % json.dumps(record))
            return
        if self.backend == "wifi":
            import urequests
            response = urequests.post(
                self.url,
                data=json.dumps(batch),
                headers={"Content-Type": "application/json"},
            )
            try:
                status = response.status_code
            finally:
                response.close()
            if status < 200 or status >= 300:
                raise OSError("collector returned HTTP %s" % status)
            return
        if self.backend == "lora":
            raise RuntimeError("LoRa delivery is handled asynchronously")
        raise ValueError("unknown egress backend")

    def status(self):
        result = {
            "enabled": self.enabled,
            "backend": self.backend,
            "pending": len(self.queue),
            "sent": self.sent,
            "failed": self.failed,
            "dropped": self.dropped,
            "retry_count": self.retry_count,
            "next_retry_ms": self.next_retry_ms,
            "spool_path": self.spool_path,
        }
        if self.lora_link is not None:
            result["link"] = self.lora_link.status()
        return result


class _BackendSettings:
    def __init__(self, settings, backend):
        self._settings = settings
        self.egress_backend = backend
        self.egress_enabled = True
        self.egress_spool_path = "%s.%s" % (settings.egress_spool_path, backend)
        self.sendmy_enabled = backend == "sendmy"

    def __getattr__(self, name):
        return getattr(self._settings, name)


class GatewayEgress:
    """Execute a gateway's configured outbound delivery functions.

    The gateway owns this component. Receivers such as ``lora_sink`` are
    destinations of a backend and never instantiate gateway egress.
    """

    def __init__(self, settings, lora_link=None, sendmy_uart=None):
        self.enabled = settings.egress_enabled
        self.backends = {}
        configured = getattr(settings, "egress_backends", [settings.egress_backend])
        for backend in configured:
            backend_settings = _BackendSettings(settings, backend)
            if backend == "sendmy":
                from sendmy import SendMyQueue
                self.backends[backend] = SendMyQueue(backend_settings, uart=sendmy_uart)
            else:
                self.backends[backend] = Egress(
                    backend_settings,
                    lora_link=lora_link if backend == "lora" else None,
                )

    def enqueue(self, record):
        for backend in self.backends.values():
            backend.enqueue(record)

    def flush(self, now_ms=None):
        for name, backend in self.backends.items():
            if name == "sendmy":
                backend.flush_due(now_ms)
            else:
                backend.flush()

    async def run(self):
        while True:
            self.flush()
            await asyncio.sleep_ms(20)

    def status(self):
        return {
            "enabled": self.enabled,
            "backends": {name: backend.status()
                         for name, backend in self.backends.items()},
        }


# Compatibility for integrations written before gateway ownership was made
# explicit in the class name.
EgressManager = GatewayEgress
