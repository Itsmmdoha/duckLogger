import pytest

from mesh_protocol import (
    DuplicateCache,
    ProtocolError,
    RouteState,
    data_packet,
    decode_packet,
    encode_packet,
)


def test_data_packet_roundtrip():
    packet = data_packet("lab", "node-1", 7, 4, "heartbeat", 3)
    assert decode_packet(encode_packet(packet), "lab") == packet


def test_rejects_unknown_event_kind():
    with pytest.raises(ProtocolError):
        data_packet("lab", "node-1", 1, 4, "free_text", 0)


def test_rejects_non_integer_value():
    with pytest.raises(ProtocolError):
        data_packet("lab", "node-1", 1, 4, "heartbeat", "3")


def test_rejects_wrong_version():
    packet = data_packet("lab", "node-1", 1, 4, "heartbeat", 0)
    packet["v"] = 1
    with pytest.raises(ProtocolError, match="version"):
        decode_packet(encode_packet(packet))


def test_rejects_wrong_network():
    packet = data_packet("lab", "node-1", 1, 4, "heartbeat", 0)
    with pytest.raises(ProtocolError, match="another mesh"):
        decode_packet(encode_packet(packet), "other")


def test_rejects_oversized_packet():
    packet = data_packet("x" * 300, "node-1", 1, 4, "heartbeat", 0)
    with pytest.raises(ProtocolError, match="payload"):
        encode_packet(packet)


def test_duplicate_cache_evicts_old_entries():
    cache = DuplicateCache(2)
    assert cache.seen("a", 1) is False
    assert cache.seen("a", 1) is True
    assert cache.seen("a", 2) is False
    assert cache.seen("a", 3) is False
    assert cache.seen("a", 1) is False


def test_route_state_selects_shortest_parent():
    state = RouteState("gateway-01", max_hops=4, failover_failures=2)
    near = b"\x01\x02\x03\x04\x05\x06"
    far = b"\x0a\x0b\x0c\x0d\x0e\x0f"
    state.consider(
        "node-01", far,
        {"g": "gateway-01", "s": "node-far", "h": 2, "q": 1},
        1000,
    )
    state.consider(
        "node-01", near,
        {"g": "gateway-01", "s": "gateway-01", "h": 0, "q": 2},
        1001,
    )
    assert state.parent_mac == near
    assert state.hop_count == 1


def test_route_state_blocks_failing_parent():
    state = RouteState("gateway-01", max_hops=4, failover_failures=2)
    parent = b"\x01\x02\x03\x04\x05\x06"
    state.consider(
        "node-01", parent,
        {"g": "gateway-01", "s": "gateway-01", "h": 0, "q": 1},
        1000,
    )
    state.record_send(parent, False, 1000)
    assert state.available is True
    state.record_send(parent, False, 1001)
    assert state.available is False


def test_primary_mode_prefers_gateway_order_over_shorter_route():
    state = RouteState(["gateway-a", "gateway-b"], max_hops=4,
                       failover_failures=2, delivery_mode="primary")
    a = bytes.fromhex("020000000001")
    b = bytes.fromhex("020000000002")
    state.consider("node", b, {"g": "gateway-b", "s": "relay-b", "h": 0,
                               "q": 1, "o": 0}, 1000)
    state.consider("node", a, {"g": "gateway-a", "s": "relay-a", "h": 2,
                               "q": 1, "o": 0}, 1001)
    assert state.gateway_id == "gateway-a"


def test_best_mode_uses_load_as_tiebreaker():
    state = RouteState(["gateway-a", "gateway-b"], max_hops=4,
                       delivery_mode="best")
    busy = bytes.fromhex("020000000001")
    quiet = bytes.fromhex("020000000002")
    state.consider("node", busy, {"g": "gateway-a", "s": "a", "h": 0,
                                  "q": 1, "o": 9}, 1000)
    state.consider("node", quiet, {"g": "gateway-b", "s": "b", "h": 0,
                                   "q": 1, "o": 1}, 1001)
    assert state.gateway_id == "gateway-b"


def test_key_event_roundtrip():
    packet = data_packet("lab", "node-1", 9, 4, "key_event", "[CTRL+C]")
    assert decode_packet(encode_packet(packet), "lab") == packet


def test_v4_event_identity_and_target_roundtrip():
    packet = data_packet("lab", "node-1", 9, 4, "key_event", "a",
                         boot_id="boot-1", target_gateway="gateway-b")
    decoded = decode_packet(encode_packet(packet), "lab")
    assert decoded["b"] == "boot-1"
    assert decoded["g"] == "gateway-b"


def test_key_event_rejects_empty_value():
    with pytest.raises(ProtocolError, match="key event"):
        data_packet("lab", "node-1", 1, 4, "key_event", "")


def test_key_event_rejects_control_characters():
    with pytest.raises(ProtocolError, match="control"):
        data_packet("lab", "node-1", 1, 4, "key_event", "a\nb")


def test_key_event_rejects_oversized_value():
    with pytest.raises(ProtocolError, match="key event"):
        data_packet("lab", "node-1", 1, 4, "key_event", "a" * 121)
