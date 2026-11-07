from mesh_network import MeshNetwork
from mesh_protocol import data_packet


class Settings:
    role = "node"
    mesh_network_id = "lab"
    node_id = "node-01"
    mesh_gateway_id = "gateway-01"
    mesh_channel = 6
    mesh_max_hops = 6
    mesh_route_interval_ms = 2000
    mesh_route_timeout_ms = 8000
    mesh_route_failover_failures = 3
    mesh_ack_timeout_ms = 800
    mesh_max_retries = 3
    mesh_queue_persist = False
    mesh_queue_path = "mesh-outbox.json"
    mesh_max_pending = 8
    mesh_duplicate_cache = 8
    mesh_telemetry_interval_ms = 1000
    mesh_telemetry_batch = 1
    mesh_log_path = "mesh-log.jsonl"
    mesh_peer_key = b"test-key-1234567"
    mesh_peer_macs = {}


class Transport:
    def __init__(self):
        self.sent = []
        self.received = []
        self.started = False

    def start(self):
        self.started = True
        return bytes.fromhex("020000000001")

    def stop(self):
        self.started = False

    def send(self, mac, data):
        self.sent.append((mac, data))
        return True

    def recv(self):
        if self.received:
            return self.received.pop(0)
        return None, None

    def status(self):
        return {"type": "fake", "mac": "test-mac"}


def make_network():
    network = MeshNetwork(Settings(), transport=Transport())
    return network


def test_transport_lifecycle_and_status():
    mesh = make_network()
    mesh.start()
    assert mesh.transport.started is True
    assert mesh.status()["transport"]["type"] == "fake"
    assert mesh.status()["mac"] == "test-mac"
    mesh.stop()
    assert mesh.transport.started is False


def test_send_packet_rejects_unknown_destination():
    mesh = make_network()
    allowed = bytes.fromhex("010203040506")
    unknown = bytes.fromhex("0a0b0c0d0e0f")
    mesh.peer_macs = {"gateway-01": allowed}
    packet = data_packet("lab", "node-01", 1, 4, "key_event", "a")
    assert mesh._send_packet(allowed, packet) is True
    assert mesh._send_packet(unknown, packet) is False
    assert mesh.stats["allowlist_dropped"] == 1


def test_publish_key_event_queues_key_event():
    mesh = make_network()
    assert mesh.publish_key_event("[CTRL+C]") is True
    assert mesh.pending[0]["packet"]["k"] == "key_event"
    assert mesh.pending[0]["packet"]["x"] == "[CTRL+C]"


def test_gateway_does_not_publish_key_events():
    mesh = make_network()
    mesh.role = "gateway"
    assert mesh.publish_key_event("a") is False
    assert mesh.pending == []


def test_all_mode_queues_one_targeted_copy_per_gateway():
    settings = Settings()
    settings.delivery_mode = "all"
    settings.delivery_gateways = ["gateway-a", "gateway-b"]
    mesh = MeshNetwork(settings, transport=Transport())
    assert mesh.publish_key_event("a") is True
    assert len(mesh.pending) == 2
    assert {entry["packet"]["g"] for entry in mesh.pending} == {
        "gateway-a", "gateway-b"}
    assert len({entry["packet"]["q"] for entry in mesh.pending}) == 1
    assert all(entry["packet"]["b"] == mesh.boot_id for entry in mesh.pending)
