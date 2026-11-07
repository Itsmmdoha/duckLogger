"""Collection-tree routing core for DuckLogger MeshOps."""

import asyncio
import time
import os

try:
    import ujson as json
except ImportError:
    import json

from mesh_protocol import (
    DuplicateCache,
    ProtocolError,
    PROTOCOL_VERSION,
    RouteState,
    TYPE_DATA,
    TYPE_ACK,
    TYPE_ROUTE,
    ack_packet,
    data_packet,
    decode_packet,
    encode_packet,
    route_packet,
)
from mesh_transport import BROADCAST


def _ticks_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def _ticks_diff(now, then):
    try:
        return time.ticks_diff(now, then)
    except AttributeError:
        return now - then


def _ticks_add(now, delta):
    try:
        return time.ticks_add(now, delta)
    except AttributeError:
        return now + delta


class MeshNetwork:
    """A single-root collection tree.

    Nodes generate data and relay packets received from descendants. The
    gateway is the root and never needs a route back to every node.
    """

    def __init__(self, settings, on_data=None, transport=None):
        self.settings = settings
        self.role = settings.role
        self.network_id = settings.mesh_network_id
        self.node_id = settings.node_id
        self.gateway_id = settings.mesh_gateway_id
        self.delivery_mode = getattr(settings, "delivery_mode", "best")
        self.delivery_gateways = getattr(
            settings, "delivery_gateways", [self.gateway_id]
        )
        self.channel = settings.mesh_channel
        self.max_hops = settings.mesh_max_hops
        self.route_interval_ms = settings.mesh_route_interval_ms
        self.route_timeout_ms = settings.mesh_route_timeout_ms
        self.route_failover_failures = settings.mesh_route_failover_failures
        self.ack_timeout_ms = settings.mesh_ack_timeout_ms
        self.max_retries = settings.mesh_max_retries
        self.queue_persist = settings.mesh_queue_persist
        self.queue_path = settings.mesh_queue_path
        self.max_pending = settings.mesh_max_pending
        self.peer_key = settings.mesh_peer_key
        self.peer_macs = settings.mesh_peer_macs
        self.on_data = on_data
        if transport is None:
            from espnow_transport import EspNowTransport
            transport = EspNowTransport(
                self.channel, self.peer_key, self.peer_macs.values()
            )
        self.transport = transport
        self.route = RouteState(
            self.delivery_gateways, self.max_hops, self.route_failover_failures,
            self.route_timeout_ms, self.delivery_mode,
        )
        self.duplicates = DuplicateCache(settings.mesh_duplicate_cache)
        self.pending = []
        self.reverse_paths = {}
        self.reverse_order = []
        self.sequence = 0
        try:
            self.boot_id = os.urandom(4).hex()
        except AttributeError:
            self.boot_id = "boot-%08x" % (_ticks_ms() & 0xffffffff)
        self.route_sequence = 0
        self.last_route_ms = 0
        self.running = False
        self.stats = {
            "received": 0,
            "forwarded": 0,
            "delivered": 0,
            "sent": 0,
            "dropped": 0,
            "allowlist_dropped": 0,
            "decode_errors": 0,
            "acknowledged": 0,
            "retry_exhausted": 0,
            "retries": 0,
            "delivery_ack_total_ms": 0,
            "delivery_ack_samples": 0,
            "route_failovers": 0,
        }
        self._load_pending()

    def _load_pending(self):
        if not self.queue_persist:
            return
        try:
            with open(self.queue_path, "r") as queue_file:
                saved = json.load(queue_file)
            if isinstance(saved, dict):
                self.sequence = int(saved.get("sequence", 0))
                packets = saved.get("packets", [])
            else:  # Read the first experimental outbox format.
                packets = saved
            if not isinstance(packets, list):
                return
            for packet in packets[-self.max_pending:]:
                if isinstance(packet, dict) and packet.get("t") == TYPE_DATA:
                    packet["v"] = PROTOCOL_VERSION
                    packet.setdefault("b", self.boot_id)
                    self.sequence = max(self.sequence, int(packet.get("q", 0)))
                    self.pending.append({
                        "packet": packet,
                        "attempts": 0,
                        "last_sent_ms": None,
                        "created_ms": _ticks_ms(),
                    })
        except (OSError, ValueError):
            # A damaged outbox must not prevent the node from booting.
            self.pending = []

    def _persist_pending(self):
        if not self.queue_persist:
            return
        temporary = self.queue_path + ".tmp"
        try:
            packets = [entry["packet"] for entry in self.pending]
            with open(temporary, "w") as queue_file:
                queue_file.write(json.dumps({
                    "sequence": self.sequence,
                    "packets": packets,
                }))
            try:
                os.remove(self.queue_path)
            except OSError:
                pass
            os.rename(temporary, self.queue_path)
        except OSError as exc:
            print("MeshOps outbox persistence failed: %s" % exc)

    def _event_key(self, source_id, boot_id, sequence, gateway_id=""):
        return "%s:%s:%s:%s" % (source_id, boot_id, sequence, gateway_id)

    def _remember_reverse_path(self, source_id, boot_id, sequence, gateway_id, mac):
        key = self._event_key(source_id, boot_id, sequence, gateway_id)
        if key not in self.reverse_paths:
            self.reverse_order.append(key)
        self.reverse_paths[key] = mac
        limit = max(16, self.max_pending * 2)
        while len(self.reverse_order) > limit:
            expired = self.reverse_order.pop(0)
            self.reverse_paths.pop(expired, None)

    def start(self):
        mac = self.transport.start()
        if not self.node_id:
            self.node_id = "node-" + "".join("%02x" % byte for byte in mac[-3:])

        if self.role == "gateway":
            self.gateway_id = self.node_id

        self.running = True
        print("MeshOps %s '%s' mac=%s channel=%s" % (
            self.role, self.node_id,
            ":".join("%02x" % byte for byte in mac), self.channel
        ))

    def stop(self):
        self.running = False
        self.transport.stop()

    def _enqueue_packet(self, packet):
        if len(self.pending) >= self.max_pending:
            self.pending.pop(0)
            self.stats["dropped"] += 1
        self.sequence = packet["q"]
        self.pending.append({
            "packet": packet,
            "attempts": 0,
            "last_sent_ms": None,
            "created_ms": _ticks_ms(),
        })
        self._persist_pending()
        return True

    def publish_telemetry(self, event_kind, event_value=0):
        """Queue one allow-listed synthetic/operational telemetry event."""
        if self.role != "node":
            return False
        try:
            sequence = (self.sequence + 1) & 0x7fffffff
            targets = self.delivery_gateways if self.delivery_mode == "all" else [""]
            packets = [data_packet(
                self.network_id, self.node_id, sequence, self.max_hops,
                event_kind, event_value, self.boot_id, target,
            ) for target in targets]
        except ProtocolError:
            return False
        for packet in packets:
            self._enqueue_packet(packet)
        return True

    def publish_key_event(self, press):
        """Queue one decoded DuckLogger key event for the gateway."""
        if self.role != "node":
            return False
        try:
            sequence = (self.sequence + 1) & 0x7fffffff
            targets = self.delivery_gateways if self.delivery_mode == "all" else [""]
            packets = [data_packet(
                self.network_id, self.node_id, sequence, self.max_hops,
                "key_event", press, self.boot_id, target,
            ) for target in targets]
        except ProtocolError:
            return False
        for packet in packets:
            self._enqueue_packet(packet)
        return True

    def _send_packet(self, mac, packet):
        if mac != BROADCAST and mac not in self.peer_macs.values():
            self.stats["allowlist_dropped"] += 1
            self.stats["dropped"] += 1
            return False
        try:
            self.transport.send(mac, encode_packet(packet))
            self.stats["sent"] += 1
            return True
        except (OSError, ProtocolError):
            self.stats["dropped"] += 1
            return False

    def _advertise_route(self, now_ms):
        if self.role == "gateway":
            gateway_id = self.node_id
            hop_count = 0
            parent_id = ""
        elif self.route.available:
            gateway_id = self.route.gateway_id
            hop_count = self.route.hop_count
            parent_id = self.route.parent_id
        else:
            return

        self.route_sequence = (self.route_sequence + 1) & 0x7fffffff
        packet = route_packet(
            self.network_id,
            gateway_id,
            self.node_id,
            hop_count,
            self.route_sequence,
            parent_id,
        )
        self._send_packet(BROADCAST, packet)
        self.last_route_ms = now_ms

    def _handle_route(self, mac, packet, now_ms):
        if self.role != "node":
            return
        expected_mac = self.peer_macs.get(packet.get("s"))
        if self.peer_macs and expected_mac != mac:
            return
        changed = self.route.consider(self.node_id, mac, packet, now_ms)
        if changed:
            print("MeshOps parent=%s hops=%s gateway=%s" % (
                self.route.parent_id,
                self.route.hop_count,
                self.route.gateway_id,
            ))

    def _handle_data(self, mac, packet):
        if self.peer_macs and mac not in self.peer_macs.values():
            self.stats["dropped"] += 1
            return
        source_id = packet.get("s")
        boot_id = packet.get("b", "legacy")
        sequence = packet.get("q")
        target_gateway = packet.get("g", "")
        duplicate = self.duplicates.seen(source_id, sequence, boot_id, target_gateway)
        self._remember_reverse_path(source_id, boot_id, sequence, target_gateway, mac)
        if not duplicate:
            self.stats["received"] += 1
        if self.role == "gateway":
            if target_gateway and target_gateway != self.node_id:
                self.stats["dropped"] += 1
                return
            if not duplicate:
                self.stats["delivered"] += 1
                if self.on_data is not None:
                    self.on_data(packet, mac)
            self._send_ack(mac, source_id, boot_id, sequence)
            return

        ttl = int(packet.get("l", 0))
        selected_route = None
        if target_gateway:
            selected_route = self.route.route_for_gateway(target_gateway, _ticks_ms())
        elif self.route.available:
            selected_route = (self.route.parent_mac, None)
        if ttl <= 1 or selected_route is None:
            self.stats["dropped"] += 1
            return

        forwarded = dict(packet)
        forwarded["l"] = ttl - 1
        forwarded["h"] = int(forwarded.get("h", 0)) + 1
        parent_mac = selected_route[0]
        if self._send_packet(parent_mac, forwarded):
            self.stats["forwarded"] += 1
        else:
            self._record_route_failure(parent_mac)

    def _send_ack(self, mac, source_id, boot_id, sequence, ttl=None):
        packet = ack_packet(
            self.network_id, source_id, sequence,
            self.max_hops if ttl is None else ttl, boot_id, self.node_id,
        )
        return self._send_packet(mac, packet)

    def _handle_ack(self, mac, packet):
        if self.peer_macs and mac not in self.peer_macs.values():
            self.stats["dropped"] += 1
            return
        source_id = packet.get("s")
        boot_id = packet.get("b", "legacy")
        sequence = packet.get("q")
        gateway_id = packet.get("g", "")
        if mac in self.route.candidates:
            self.route.record_send(mac, True, _ticks_ms())

        if self.role == "node" and source_id == self.node_id:
            for index, entry in enumerate(self.pending):
                data = entry["packet"]
                if (data.get("s") == source_id and data.get("b", "legacy") == boot_id
                        and data.get("q") == sequence
                        and (not data.get("g") or data.get("g") == gateway_id)):
                    elapsed = _ticks_diff(
                        _ticks_ms(), entry["created_ms"]
                    )
                    self.stats["acknowledged"] += 1
                    self.stats["delivery_ack_total_ms"] += max(0, elapsed)
                    self.stats["delivery_ack_samples"] += 1
                    del self.pending[index]
                    self._persist_pending()
                    return
            return

        if int(packet.get("l", 0)) <= 1:
            return
        previous_hop = self.reverse_paths.get(
            self._event_key(source_id, boot_id, sequence, gateway_id)
        )
        if previous_hop is None:
            previous_hop = self.reverse_paths.get(
                self._event_key(source_id, boot_id, sequence, "")
            )
        if previous_hop is None:
            return
        forwarded = dict(packet)
        forwarded["l"] = int(packet["l"]) - 1
        self._send_packet(previous_hop, forwarded)

    def _record_route_failure(self, mac):
        if self.route.record_send(mac, False, _ticks_ms()):
            self.stats["route_failovers"] += 1
            print("MeshOps route failover parent=%s hops=%s" % (
                self.route.parent_id, self.route.hop_count
            ))

    def _receive_available(self, now_ms):
        for _ in range(8):
            try:
                mac, raw = self.transport.recv()
            except OSError:
                return
            if mac is None or raw is None:
                return
            if mac not in self.peer_macs.values():
                self.stats["allowlist_dropped"] += 1
                self.stats["dropped"] += 1
                continue
            try:
                packet = decode_packet(raw, self.network_id)
            except ProtocolError:
                self.stats["decode_errors"] += 1
                continue

            if packet.get("t") == TYPE_ROUTE:
                self._handle_route(mac, packet, now_ms)
            elif packet.get("t") == TYPE_DATA:
                self._handle_data(mac, packet)
            elif packet.get("t") == TYPE_ACK:
                self._handle_ack(mac, packet)

    def _expire_route(self, now_ms):
        if self.role != "node" or not self.route.available:
            return
        previous = self.route.parent_mac
        self.route.expire(now_ms, self.route_timeout_ms)
        if previous is not None and self.route.parent_mac != previous:
            self.stats["route_failovers"] += 1
            print("MeshOps route changed after expiry parent=%s" % self.route.parent_id)

    def _send_pending(self, now_ms):
        if self.role != "node" or not self.pending:
            return
        entry = self.pending[0]
        target_gateway = entry["packet"].get("g", "")
        selected_route = (self.route.route_for_gateway(target_gateway, now_ms)
                          if target_gateway else
                          ((self.route.parent_mac, None) if self.route.available else None))
        if selected_route is None:
            return
        last_sent = entry["last_sent_ms"]
        if last_sent is not None:
            if _ticks_diff(now_ms, last_sent) < self.ack_timeout_ms:
                return
            if entry["attempts"]:
                failed_parent = self.route.parent_mac
                self._record_route_failure(failed_parent)
                if entry["attempts"] >= self.max_retries + 1:
                    self.pending.pop(0)
                    self.stats["retry_exhausted"] += 1
                    self.stats["dropped"] += 1
                    self._persist_pending()
                    return
                self.stats["retries"] += 1

        packet = entry["packet"]
        parent_mac = selected_route[0]
        if self._send_packet(parent_mac, packet):
            entry["attempts"] += 1
            entry["last_sent_ms"] = now_ms
        else:
            entry["last_sent_ms"] = now_ms
            self._record_route_failure(parent_mac)

    def status(self):
        transport_status = self.transport.status()
        return {
            "role": self.role,
            "node_id": self.node_id,
            "mac": transport_status.get("mac", ""),
            "transport": transport_status,
            "network_id": self.network_id,
            "gateway_id": self.gateway_id or self.route.gateway_id,
            "parent_id": self.route.parent_id,
            "hop_count": self.route.hop_count,
            "route_available": self.role == "gateway" or self.route.available,
            "pending": len(self.pending),
            "route_candidates": len(self.route.candidates),
            "delivery_mode": self.delivery_mode,
            "delivery_gateways": list(self.delivery_gateways),
            "boot_id": self.boot_id,
            "allowlist_peers": len(self.peer_macs),
            "route_metrics": {
                "hop_count": self.route.hop_count,
                "parent_failures": self.route.candidates.get(
                    self.route.parent_mac, {}
                ).get("failures", 0) if self.route.parent_mac is not None else 0,
            },
            "stats": dict(self.stats),
            "average_delivery_ack_ms": (
                self.stats["delivery_ack_total_ms"] //
                self.stats["delivery_ack_samples"]
                if self.stats["delivery_ack_samples"] else None
            ),
        }

    async def run(self):
        if not self.running:
            self.start()
        while self.running:
            now_ms = _ticks_ms()
            self._receive_available(now_ms)
            self._expire_route(now_ms)
            if _ticks_diff(now_ms, self.last_route_ms) >= self.route_interval_ms:
                self._advertise_route(now_ms)
            self._send_pending(now_ms)
            await asyncio.sleep_ms(20)

    async def run_synthetic_telemetry(self):
        """Emit a fixed heartbeat/counter for bench and lab validation."""
        if not self.running:
            self.start()
        interval = self.settings.mesh_telemetry_interval_ms
        batch = self.settings.mesh_telemetry_batch
        next_emit = _ticks_ms()
        counter = 0
        while self.running:
            now_ms = _ticks_ms()
            if self.role == "node" and _ticks_diff(now_ms, next_emit) >= 0:
                for _ in range(batch):
                    counter += 1
                    self.publish_telemetry("synthetic_counter", counter)
                next_emit = _ticks_add(now_ms, interval)
            await asyncio.sleep_ms(100)
