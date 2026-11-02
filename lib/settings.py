from json import load as json_load

class Settings:
    def __init__(self, path="settings.json") -> None:
        self.load_from_file(path=path)

    def load_from_file(self, path):
        with open(path, "r") as f:
            settings_data = json_load(f)

        device = settings_data.get("device", {})
        self.role = device.get("role", "standalone")
        self.node_id = device.get("id", "")
        self.mesh_only = bool(device.get("mesh_only", False))

        # Wi-Fi is a management interface, not the mesh transport. Preserve
        # the original flat settings for standalone installations while
        # allowing MeshOps devices to configure management Wi-Fi explicitly.
        management = settings_data.get("management", {})
        self.management_enabled = bool(management.get(
            "enabled", device.get("local_ui", self.role == "standalone")
        ))
        self.mode = management.get(
            "mode", settings_data.get("mode", "ap")
        )
        self.ssid = management.get(
            "ssid", settings_data.get("ssid", "duckLogger")
        )
        self.password = management.get(
            "password", settings_data.get("password", "duckPass1234")
        )
        self.local_ui = bool(device.get("local_ui", self.management_enabled))

        mesh = settings_data.get("mesh", {})
        self.mesh_enabled = bool(mesh.get(
            "enabled", self.role in ("node", "gateway")
        ))
        self.mesh_network_id = mesh.get("network_id", "ducklogger-mesh")
        self.mesh_gateway_id = mesh.get("gateway_id", "gateway-01")
        self.mesh_channel = int(mesh.get("channel", 6))
        self.mesh_max_hops = int(mesh.get("max_hops", 6))
        self.mesh_route_interval_ms = int(mesh.get("route_interval_ms", 2000))
        self.mesh_route_timeout_ms = int(mesh.get("route_timeout_ms", 8000))
        self.mesh_route_failover_failures = int(
            mesh.get("route_failover_failures", 3)
        )
        self.mesh_ack_timeout_ms = int(mesh.get("ack_timeout_ms", 800))
        self.mesh_max_retries = int(mesh.get("max_retries", 3))
        self.mesh_queue_persist = bool(mesh.get("queue_persist", False))
        self.mesh_queue_path = mesh.get("queue_path", "mesh-outbox.json")
        self.mesh_duplicate_cache = int(mesh.get("duplicate_cache", 128))
        self.mesh_max_pending = int(mesh.get("max_pending", 128))
        self.mesh_telemetry_batch = int(mesh.get("telemetry_batch", 1))
        self.mesh_telemetry_interval_ms = int(
            mesh.get("telemetry_interval_ms", 10000)
        )
        if self.mesh_route_failover_failures < 1:
            raise ValueError("mesh.route_failover_failures must be positive")
        if self.mesh_ack_timeout_ms < 100:
            raise ValueError("mesh.ack_timeout_ms must be at least 100")
        if self.mesh_max_retries < 0 or self.mesh_max_retries > 10:
            raise ValueError("mesh.max_retries must be between 0 and 10")
        if self.mesh_telemetry_batch < 1 or self.mesh_telemetry_batch > 64:
            raise ValueError("mesh.telemetry_batch must be between 1 and 64")
        self.mesh_log_path = mesh.get("log_path", "mesh-log.jsonl")

        peer_key = mesh.get("peer_key", "")
        self.mesh_peer_key = peer_key.encode("utf-8")
        if self.mesh_peer_key and len(self.mesh_peer_key) != 16:
            raise ValueError("mesh.peer_key must contain exactly 16 UTF-8 bytes")

        peer_macs = mesh.get("peer_macs", {})
        if not isinstance(peer_macs, dict):
            raise ValueError("mesh.peer_macs must map device IDs to MAC addresses")
        self.mesh_peer_macs = {}
        for peer_id, address in peer_macs.items():
            try:
                octets = address.replace("-", ":").split(":")
                if len(octets) != 6 or any(len(part) != 2 for part in octets):
                    raise ValueError
                mac_buffer = bytearray(6)
                for index in range(6):
                    mac_buffer[index] = int(octets[index], 16)
                mac = bytes(mac_buffer)
            except (AttributeError, ValueError):
                raise ValueError("invalid MAC address for mesh peer %s" % peer_id)
            if not any(mac):
                # All-zero addresses are local discovery placeholders. Once
                # filled, a non-empty map enforces the configured allowlist.
                continue
            if mac[0] & 1:
                raise ValueError("mesh peer %s needs a unicast MAC address" % peer_id)
            self.mesh_peer_macs[peer_id] = mac
