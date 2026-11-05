"""ESP-NOW collection-tree transport for DuckLogger MeshOps."""

import asyncio
import time

import espnow
import network

from mesh_protocol import (
    DuplicateCache,
    ProtocolError,
    RouteState,
    TYPE_DATA,
    TYPE_ROUTE,
    data_packet,
    decode_packet,
    encode_packet,
    route_packet,
)


BROADCAST = b"\xff\xff\xff\xff\xff\xff"


class MeshNetwork:
    """A single-root collection tree.

    Nodes generate data and relay packets received from descendants. The
    gateway is the root and never needs a route back to every node.
    """

    def __init__(self, settings, on_data=None):
        self.settings = settings
        self.role = settings.role
        self.network_id = settings.mesh_network_id
        self.node_id = settings.node_id
        self.gateway_id = settings.mesh_gateway_id
        self.channel = settings.mesh_channel
        self.max_hops = settings.mesh_max_hops
        self.route_interval_ms = settings.mesh_route_interval_ms
        self.route_timeout_ms = settings.mesh_route_timeout_ms
        self.max_pending = settings.mesh_max_pending
        self.peer_key = settings.mesh_peer_key
        self.on_data = on_data

        self.sta = None
        self.radio = None
        self.route = RouteState(self.gateway_id, self.max_hops)
        self.duplicates = DuplicateCache(settings.mesh_duplicate_cache)
        self.pending = []
        self.peers = []
        self.sequence = 0
        self.route_sequence = 0
        self.last_route_ms = 0
        self.running = False
        self.stats = {
            "received": 0,
            "forwarded": 0,
            "delivered": 0,
            "sent": 0,
            "dropped": 0,
            "decode_errors": 0,
        }

    def start(self):
        self.sta = network.WLAN(network.STA_IF)
        self.sta.active(True)
        if self.sta.isconnected():
            self.sta.disconnect()
        try:
            self.sta.config(channel=self.channel)
        except OSError:
            pass

        if not self.node_id:
            mac = self.sta.config("mac")
            self.node_id = "node-" + "".join("%02x" % byte for byte in mac[-3:])

        if self.role == "gateway":
            self.gateway_id = self.node_id

        self.radio = espnow.ESPNow()
        self.radio.active(True)
        if self.peer_key:
            self.radio.set_pmk(self.peer_key)
        self._add_peer(BROADCAST, encrypt=False)
        self.running = True
        print("MeshOps %s '%s' on channel %s" % (
            self.role, self.node_id, self.channel
        ))

    def stop(self):
        self.running = False
        if self.radio is not None:
            self.radio.active(False)

    def _add_peer(self, mac, encrypt=True):
        if mac in self.peers:
            return
        try:
            if encrypt and len(self.peer_key) == 16:
                self.radio.add_peer(mac, lmk=self.peer_key, channel=0,
                                    ifidx=network.STA_IF, encrypt=True)
            else:
                self.radio.add_peer(mac)
            self.peers.append(mac)
        except OSError:
            # ESP-NOW reports an error when a peer already exists. Treat it as
            # usable and avoid retrying it on every packet.
            self.peers.append(mac)

    def publish_telemetry(self, event_kind, event_value=0):
        """Queue one allow-listed synthetic/operational telemetry event."""
        if self.role != "node":
            return False
        try:
            packet = data_packet(
                self.network_id,
                self.node_id,
                (self.sequence + 1) & 0x7fffffff,
                self.max_hops,
                event_kind,
                event_value,
            )
        except ProtocolError:
            return False
        if len(self.pending) >= self.max_pending:
            self.pending.pop(0)
            self.stats["dropped"] += 1
        self.sequence = packet["q"]
        self.pending.append(packet)
        return True

    def _send_packet(self, mac, packet):
        try:
            self._add_peer(mac, encrypt=(mac != BROADCAST))
            self.radio.send(mac, encode_packet(packet), False)
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
        changed = self.route.consider(self.node_id, mac, packet, now_ms)
        if changed:
            self._add_peer(self.route.parent_mac)
            print("MeshOps parent=%s hops=%s gateway=%s" % (
                self.route.parent_id,
                self.route.hop_count,
                self.route.gateway_id,
            ))

    def _handle_data(self, mac, packet):
        source_id = packet.get("s")
        sequence = packet.get("q")
        if self.duplicates.seen(source_id, sequence):
            return

        self.stats["received"] += 1
        if self.role == "gateway":
            self.stats["delivered"] += 1
            if self.on_data is not None:
                self.on_data(packet, mac)
            return

        ttl = int(packet.get("l", 0))
        if ttl <= 1 or not self.route.available:
            self.stats["dropped"] += 1
            return

        forwarded = dict(packet)
        forwarded["l"] = ttl - 1
        if self._send_packet(self.route.parent_mac, forwarded):
            self.stats["forwarded"] += 1

    def _receive_available(self, now_ms):
        for _ in range(8):
            try:
                mac, raw = self.radio.irecv(0)
            except OSError:
                return
            if mac is None or raw is None:
                return
            try:
                packet = decode_packet(raw, self.network_id)
            except ProtocolError:
                self.stats["decode_errors"] += 1
                continue

            if packet.get("t") == TYPE_ROUTE:
                self._handle_route(mac, packet, now_ms)
            elif packet.get("t") == TYPE_DATA:
                self._handle_data(mac, packet)

    def _expire_route(self, now_ms):
        if self.role != "node" or not self.route.available:
            return
        if time.ticks_diff(now_ms, self.route.last_seen_ms) > self.route_timeout_ms:
            print("MeshOps route expired")
            self.route.clear()

    def _send_pending(self):
        if self.role != "node" or not self.pending or not self.route.available:
            return
        packet = self.pending[0]
        if self._send_packet(self.route.parent_mac, packet):
            self.duplicates.seen(packet["s"], packet["q"])
            self.pending.pop(0)

    def status(self):
        return {
            "role": self.role,
            "node_id": self.node_id,
            "network_id": self.network_id,
            "gateway_id": self.gateway_id or self.route.gateway_id,
            "parent_id": self.route.parent_id,
            "hop_count": self.route.hop_count,
            "route_available": self.role == "gateway" or self.route.available,
            "pending": len(self.pending),
            "stats": self.stats,
        }

    async def run(self):
        if not self.running:
            self.start()
        while self.running:
            now_ms = time.ticks_ms()
            self._receive_available(now_ms)
            self._expire_route(now_ms)
            if time.ticks_diff(now_ms, self.last_route_ms) >= self.route_interval_ms:
                self._advertise_route(now_ms)
            self._send_pending()
            await asyncio.sleep_ms(20)

    async def run_synthetic_telemetry(self):
        """Emit a fixed heartbeat/counter for bench and lab validation."""
        if not self.running:
            self.start()
        interval = self.settings.mesh_telemetry_interval_ms
        next_emit = time.ticks_ms()
        counter = 0
        while self.running:
            now_ms = time.ticks_ms()
            if self.role == "node" and time.ticks_diff(now_ms, next_emit) >= 0:
                counter += 1
                self.publish_telemetry("synthetic_counter", counter)
                next_emit = time.ticks_add(now_ms, interval)
            await asyncio.sleep_ms(100)
