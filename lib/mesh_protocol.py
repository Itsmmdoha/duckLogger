"""Compact, radio-agnostic protocol helpers for DuckLogger MeshOps.

Packets are intentionally small because ESP-NOW payloads are limited to 250
bytes.  The module has no hardware dependencies, so it can also be exercised
with CPython tests.
"""

try:
    import ujson as json
except ImportError:  # CPython
    import json


PROTOCOL_VERSION = 1
TYPE_ROUTE = "r"
TYPE_DATA = "d"
MAX_PACKET_BYTES = 240
EVENT_KINDS = ("heartbeat", "synthetic_counter", "link_test")


class ProtocolError(ValueError):
    pass


def route_packet(network_id, gateway_id, sender_id, hop_count, sequence,
                 parent_id=""):
    return {
        "v": PROTOCOL_VERSION,
        "n": network_id,
        "t": TYPE_ROUTE,
        "g": gateway_id,
        "s": sender_id,
        "h": int(hop_count),
        "q": int(sequence),
        "p": parent_id or "",
    }


def data_packet(network_id, source_id, sequence, ttl, event_kind,
                event_value=0):
    if event_kind not in EVENT_KINDS:
        raise ProtocolError("unsupported telemetry event kind")
    if not isinstance(event_value, int):
        raise ProtocolError("telemetry value must be an integer")
    return {
        "v": PROTOCOL_VERSION,
        "n": network_id,
        "t": TYPE_DATA,
        "s": source_id,
        "q": int(sequence),
        "l": int(ttl),
        "k": event_kind,
        "x": event_value,
    }


def encode_packet(packet):
    try:
        encoded = json.dumps(packet, separators=(",", ":")).encode("utf-8")
    except TypeError:  # MicroPython ujson has no separators argument
        encoded = json.dumps(packet).encode("utf-8")

    if len(encoded) > MAX_PACKET_BYTES:
        raise ProtocolError("packet exceeds ESP-NOW safe payload size")
    return encoded


def decode_packet(raw, expected_network=None):
    if not raw:
        raise ProtocolError("empty packet")
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        packet = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ProtocolError("invalid packet encoding") from exc

    if not isinstance(packet, dict):
        raise ProtocolError("packet must be an object")
    if packet.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    if expected_network is not None and packet.get("n") != expected_network:
        raise ProtocolError("packet belongs to another mesh")

    packet_type = packet.get("t")
    if packet_type == TYPE_ROUTE:
        required = ("g", "s", "h", "q")
    elif packet_type == TYPE_DATA:
        required = ("s", "q", "l", "k", "x")
    else:
        raise ProtocolError("unknown packet type")

    if any(key not in packet for key in required):
        raise ProtocolError("packet is missing required fields")
    if packet_type == TYPE_DATA:
        if packet.get("k") not in EVENT_KINDS:
            raise ProtocolError("unsupported telemetry event kind")
        if not isinstance(packet.get("x"), int):
            raise ProtocolError("telemetry value must be an integer")
        if not isinstance(packet.get("s"), str) or not packet["s"]:
            raise ProtocolError("invalid source identity")
        for key in ("q", "l"):
            if not isinstance(packet.get(key), int) or packet[key] < 0:
                raise ProtocolError("invalid data metric")
    else:
        for key in ("h", "q"):
            if not isinstance(packet.get(key), int) or packet[key] < 0:
                raise ProtocolError("invalid route metric")
        for key in ("g", "s"):
            if not isinstance(packet.get(key), str) or not packet[key]:
                raise ProtocolError("invalid route identity")
    return packet


class DuplicateCache:
    """Small FIFO cache used to suppress repeated multi-hop data packets."""

    def __init__(self, capacity=128):
        self.capacity = capacity
        self._items = []

    def seen(self, source_id, sequence):
        key = "%s:%s" % (source_id, sequence)
        if key in self._items:
            return True
        self._items.append(key)
        if len(self._items) > self.capacity:
            self._items.pop(0)
        return False


class RouteState:
    """Selected next hop towards a single gateway/root."""

    def __init__(self, configured_gateway="", max_hops=8):
        self.configured_gateway = configured_gateway
        self.max_hops = max_hops
        self.gateway_id = ""
        self.parent_id = ""
        self.parent_mac = None
        self.hop_count = None
        self.last_seen_ms = 0

    @property
    def available(self):
        return self.parent_mac is not None and self.hop_count is not None

    def clear(self):
        self.gateway_id = ""
        self.parent_id = ""
        self.parent_mac = None
        self.hop_count = None
        self.last_seen_ms = 0

    def consider(self, own_id, sender_mac, packet, now_ms):
        """Select a better parent or refresh the currently selected parent."""
        gateway_id = packet.get("g", "")
        sender_id = packet.get("s", "")
        if not gateway_id or not sender_id or sender_id == own_id:
            return False
        if packet.get("p") == own_id:  # split horizon: do not select a child
            return False
        if self.configured_gateway and gateway_id != self.configured_gateway:
            return False

        candidate_hops = int(packet.get("h", self.max_hops)) + 1
        if candidate_hops > self.max_hops:
            return False

        same_parent = self.parent_mac == sender_mac
        better = self.hop_count is None or candidate_hops < self.hop_count
        if not (same_parent or better):
            return False

        changed = not same_parent or self.hop_count != candidate_hops
        self.gateway_id = gateway_id
        self.parent_id = sender_id
        self.parent_mac = sender_mac
        self.hop_count = candidate_hops
        self.last_seen_ms = now_ms
        return changed
