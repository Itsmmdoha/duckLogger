"""Compact, radio-agnostic protocol helpers for DuckLogger MeshOps.

Packets are intentionally small because ESP-NOW payloads are limited to 250
bytes.  The module has no hardware dependencies, so it can also be exercised
with CPython tests.
"""

try:
    import ujson as json
except ImportError:  # CPython
    import json


PROTOCOL_VERSION = 4
TYPE_ROUTE = "r"
TYPE_DATA = "d"
TYPE_ACK = "a"
MAX_PACKET_BYTES = 240
MAX_KEY_EVENT_CHARS = 120
EVENT_KINDS = ("heartbeat", "synthetic_counter", "link_test", "key_event")


class ProtocolError(ValueError):
    pass


def route_packet(network_id, gateway_id, sender_id, hop_count, sequence,
                 parent_id="", epoch=0, load=0):
    return {
        "v": PROTOCOL_VERSION,
        "n": network_id,
        "t": TYPE_ROUTE,
        "g": gateway_id,
        "s": sender_id,
        "h": int(hop_count),
        "q": int(sequence),
        "p": parent_id or "",
        "e": int(epoch),
        "o": int(load),
    }


def data_packet(network_id, source_id, sequence, ttl, event_kind,
                event_value=0, boot_id="", target_gateway="", session_id=""):
    if event_kind not in EVENT_KINDS:
        raise ProtocolError("unsupported telemetry event kind")
    if event_kind == "key_event":
        if (not isinstance(event_value, str) or not event_value
                or len(event_value) > MAX_KEY_EVENT_CHARS):
            raise ProtocolError("invalid key event value")
        if any(ord(char) < 0x20 for char in event_value):
            raise ProtocolError("key event contains control characters")
    elif not isinstance(event_value, int):
        raise ProtocolError("telemetry value must be an integer")
    packet = {
        "v": PROTOCOL_VERSION,
        "n": network_id,
        "t": TYPE_DATA,
        "s": source_id,
        "q": int(sequence),
        "l": int(ttl),
        "k": event_kind,
        "x": event_value,
        "h": 1,
        "b": boot_id or "legacy",
    }
    if target_gateway:
        packet["g"] = target_gateway
    if session_id:
        packet["j"] = session_id
    return packet


def ack_packet(network_id, source_id, sequence, ttl, boot_id="legacy",
               gateway_id=""):
    """A hop-by-hop-routed acknowledgement for one telemetry sequence."""
    packet = {
        "v": PROTOCOL_VERSION,
        "n": network_id,
        "t": TYPE_ACK,
        "s": source_id,
        "q": int(sequence),
        "l": int(ttl),
        "b": boot_id or "legacy",
    }
    if gateway_id:
        packet["g"] = gateway_id
    return packet


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
        required = ("s", "b", "q", "l", "k", "x")
    elif packet_type == TYPE_ACK:
        required = ("s", "b", "q", "l")
    else:
        raise ProtocolError("unknown packet type")

    if any(key not in packet for key in required):
        raise ProtocolError("packet is missing required fields")
    if packet_type == TYPE_DATA:
        if packet.get("k") not in EVENT_KINDS:
            raise ProtocolError("unsupported telemetry event kind")
        if packet.get("k") == "key_event":
            value = packet.get("x")
            if (not isinstance(value, str) or not value
                    or len(value) > MAX_KEY_EVENT_CHARS):
                raise ProtocolError("invalid key event value")
            if any(ord(char) < 0x20 for char in value):
                raise ProtocolError("key event contains control characters")
        elif not isinstance(packet.get("x"), int):
            raise ProtocolError("telemetry value must be an integer")
        if not isinstance(packet.get("s"), str) or not packet["s"]:
            raise ProtocolError("invalid source identity")
        if not isinstance(packet.get("b"), str) or not packet["b"]:
            raise ProtocolError("invalid boot identity")
        if "g" in packet and (not isinstance(packet["g"], str) or not packet["g"]):
            raise ProtocolError("invalid target gateway")
        for key in ("q", "l"):
            if not isinstance(packet.get(key), int) or packet[key] < 0:
                raise ProtocolError("invalid data metric")
        if "h" in packet and (not isinstance(packet["h"], int) or packet["h"] < 0):
            raise ProtocolError("invalid hop metric")
    elif packet_type == TYPE_ACK:
        if not isinstance(packet.get("s"), str) or not packet["s"]:
            raise ProtocolError("invalid acknowledgement source")
        if not isinstance(packet.get("b"), str) or not packet["b"]:
            raise ProtocolError("invalid acknowledgement boot identity")
        for key in ("q", "l"):
            if not isinstance(packet.get(key), int) or packet[key] < 0:
                raise ProtocolError("invalid acknowledgement metric")
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

    def seen(self, source_id, sequence, boot_id="legacy", gateway_id=""):
        key = "%s:%s:%s:%s" % (source_id, boot_id, sequence, gateway_id)
        if key in self._items:
            return True
        self._items.append(key)
        if len(self._items) > self.capacity:
            self._items.pop(0)
        return False


class RouteState:
    """Select a fresh parent toward one gateway, with failure-aware failover."""

    def __init__(self, configured_gateway="", max_hops=8,
                 failover_failures=3, failover_cooldown_ms=8000,
                 delivery_mode="best"):
        if isinstance(configured_gateway, (list, tuple)):
            self.configured_gateways = list(configured_gateway)
        else:
            self.configured_gateways = [configured_gateway] if configured_gateway else []
        self.configured_gateway = self.configured_gateways[0] if self.configured_gateways else ""
        self.delivery_mode = delivery_mode
        self.max_hops = max_hops
        self.failover_failures = max(1, int(failover_failures))
        self.failover_cooldown_ms = max(1, int(failover_cooldown_ms))
        self.gateway_id = ""
        self.parent_id = ""
        self.parent_mac = None
        self.hop_count = None
        self.last_seen_ms = 0
        self.candidates = {}

    @property
    def available(self):
        return self.parent_mac is not None and self.hop_count is not None

    def clear(self):
        self.gateway_id = ""
        self.parent_id = ""
        self.parent_mac = None
        self.hop_count = None
        self.last_seen_ms = 0
        self.candidates = {}

    def _select(self, now_ms=None):
        eligible = []
        for mac, candidate in self.candidates.items():
            cooling_down = (
                now_ms is not None and candidate["blocked_until"] is not None
                and time_diff(candidate["blocked_until"], now_ms) > 0
            )
            if (not cooling_down and now_ms is not None
                    and candidate["blocked_until"] is not None):
                candidate["failures"] = 0
                candidate["blocked_until"] = None
            if candidate["failures"] < self.failover_failures and not cooling_down:
                age = (time_diff(now_ms, candidate["last_seen"])
                       if now_ms is not None else 0)
                if self.delivery_mode == "primary" and self.configured_gateways:
                    gateway_rank = self.configured_gateways.index(candidate["gateway"])
                else:
                    gateway_rank = 0
                eligible.append((gateway_rank, candidate["hops"],
                                  candidate.get("load", 0), candidate["failures"],
                                  age, mac, candidate))
        if not eligible:
            self.gateway_id = ""
            self.parent_id = ""
            self.parent_mac = None
            self.hop_count = None
            self.last_seen_ms = 0
            return
        eligible.sort()
        _, _, _, _, _, mac, candidate = eligible[0]
        self.gateway_id = candidate["gateway"]
        self.parent_id = candidate["parent"]
        self.parent_mac = mac
        self.hop_count = candidate["hops"]
        self.last_seen_ms = candidate["last_seen"]

    def record_send(self, mac, success, now_ms=None):
        """Update a candidate's consecutive delivery failures; return on switch."""
        candidate = self.candidates.get(mac)
        if candidate is None:
            return False
        previous = self.parent_mac
        if success:
            candidate["failures"] = 0
            candidate["blocked_until"] = None
        else:
            candidate["failures"] += 1
            if candidate["failures"] >= self.failover_failures:
                if now_ms is None:
                    now_ms = candidate["last_seen"]
                try:
                    import time
                    candidate["blocked_until"] = time.ticks_add(
                        now_ms, self.failover_cooldown_ms
                    )
                except AttributeError:
                    candidate["blocked_until"] = now_ms + self.failover_cooldown_ms
        self._select(now_ms)
        return previous is not None and self.parent_mac != previous

    def expire(self, now_ms, timeout_ms):
        stale = []
        for mac, candidate in self.candidates.items():
            if time_diff(now_ms, candidate["last_seen"]) > timeout_ms:
                stale.append(mac)
        for mac in stale:
            del self.candidates[mac]
        self._select(now_ms)

    def consider(self, own_id, sender_mac, packet, now_ms):
        """Select a better parent or refresh the currently selected parent."""
        gateway_id = packet.get("g", "")
        sender_id = packet.get("s", "")
        if not gateway_id or not sender_id or sender_id == own_id:
            return False
        if packet.get("p") == own_id:  # split horizon: do not select a child
            return False
        if self.configured_gateways and gateway_id not in self.configured_gateways:
            return False

        candidate_hops = int(packet.get("h", self.max_hops)) + 1
        if candidate_hops > self.max_hops:
            return False

        candidate = self.candidates.get(sender_mac)
        self.candidates[sender_mac] = {
            "gateway": gateway_id,
            "parent": sender_id,
            "hops": candidate_hops,
            "last_seen": now_ms,
            # Route advertisements refresh reachability, not delivery quality.
            "failures": candidate["failures"] if candidate else 0,
            "blocked_until": candidate["blocked_until"] if candidate else None,
            "load": int(packet.get("o", 0)),
        }
        previous = (self.parent_mac, self.hop_count)
        self._select(now_ms)
        return previous != (self.parent_mac, self.hop_count)

    def route_for_gateway(self, gateway_id, now_ms=None):
        matches = []
        for mac, candidate in self.candidates.items():
            if candidate["gateway"] != gateway_id:
                continue
            if (candidate["failures"] >= self.failover_failures or
                    (now_ms is not None and candidate["blocked_until"] is not None
                     and time_diff(candidate["blocked_until"], now_ms) > 0)):
                continue
            matches.append((candidate["hops"], candidate.get("load", 0), mac, candidate))
        if not matches:
            return None
        matches.sort()
        return matches[0][2], matches[0][3]


def time_diff(now, then):
    """ticks_diff-compatible subtraction for the small positive timeout window."""
    try:
        import time
        return time.ticks_diff(now, then)
    except AttributeError:  # CPython protocol simulations
        return now - then
