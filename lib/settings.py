from json import load as json_load


PLACEHOLDER_SECRETS = {
    "",
    "change_me",
    "change-me",
    "change_me_password",
    "change-this-password",
    "change_me_token_32_chars",
    "change_me_16byte",
    "change_me_lora_key",
    "duckpass1234",
    "password",
    "admin",
}


def is_placeholder_secret(value):
    if value is None:
        return True
    normalized = str(value).strip()
    return not normalized or normalized.lower() in PLACEHOLDER_SECRETS


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
        self.data_source = bool(device.get("data_source", False))
        self.synthetic_telemetry = bool(
            device.get("synthetic_telemetry", True)
        )
        self.allow_hid_with_mesh = bool(
            device.get("allow_hid_with_mesh", False)
        )

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
            "password", settings_data.get("password", "")
        )
        self.api_token = management.get(
            "api_token", settings_data.get("api_token", "")
        )
        self.local_ui = bool(device.get("local_ui", self.management_enabled))
        network_policy = settings_data.get("network_policy", {})
        self.network_direct_sendmy = bool(network_policy.get("direct_sendmy", False))

        mesh = settings_data.get("mesh", {})
        self.mesh_enabled = bool(mesh.get(
            "enabled", self.role in ("node", "gateway")
        ))
        self.mesh_transport = mesh.get("transport", "espnow")
        self.mesh_network_id = mesh.get("network_id", "ducklogger-mesh")
        self.mesh_protocol_version = int(mesh.get("protocol_version", 4))
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

        delivery = settings_data.get("delivery", {})
        if not isinstance(delivery, dict):
            raise ValueError("delivery must be an object")
        self.delivery_mode = delivery.get("mode", "best")
        self.delivery_gateways = delivery.get(
            "gateways", [self.mesh_gateway_id] if self.mesh_gateway_id else []
        )
        if not isinstance(self.delivery_gateways, list):
            raise ValueError("delivery.gateways must be a list")

        uplink = settings_data.get("uplink", {})
        if not isinstance(uplink, dict):
            raise ValueError("uplink must be an object")
        self.uplink_mesh = bool(uplink.get("mesh", self.mesh_enabled))
        self.uplink_sendmy = bool(uplink.get("sendmy", False))

        sendmy = settings_data.get("sendmy", {})
        if not isinstance(sendmy, dict):
            raise ValueError("sendmy must be an object")
        self.sendmy_enabled = bool(sendmy.get("enabled", self.uplink_sendmy))
        self.sendmy_modem_id = str(sendmy.get("modem_id", ""))
        self.sendmy_uart_id = int(sendmy.get("uart_id", 1))
        self.sendmy_tx_pin = int(sendmy.get("tx_pin", 17))
        self.sendmy_rx_pin = int(sendmy.get("rx_pin", 18))
        self.sendmy_baudrate = int(sendmy.get("baudrate", 115200))
        self.sendmy_max_message_bytes = int(sendmy.get("max_message_bytes", 180))
        self.sendmy_max_pending = int(sendmy.get("max_pending", 64))
        self.sendmy_batch_interval_ms = int(
            sendmy.get("batch_interval_ms", 60000)
        )
        self.sendmy_batch_size = int(sendmy.get("batch_size", 32))
        self.sendmy_spool_path = sendmy.get("spool_path", "sendmy-outbox.json")

        egress = settings_data.get("egress", {})
        if not isinstance(egress, dict):
            raise ValueError("egress must be an object")
        gateway_default = self.role == "gateway"
        self.egress_enabled = bool(egress.get("enabled", gateway_default))
        self.egress_backend = egress.get(
            "backend", "log" if gateway_default else "none"
        )
        self.egress_backends = egress.get(
            "backends", [self.egress_backend] if self.egress_enabled else []
        )
        if isinstance(self.egress_backends, str):
            self.egress_backends = [self.egress_backends]
        self.egress_url = egress.get("url", "")
        self.egress_batch_size = int(egress.get("batch_size", 10))
        self.egress_interval_ms = int(egress.get("interval_ms", 5000))
        self.egress_max_pending = int(egress.get("max_pending", 512))
        self.egress_spool_path = egress.get("spool_path", "mesh-egress.json")
        self.egress_retry_base_ms = int(egress.get("retry_base_ms", 1000))
        self.egress_retry_max_ms = int(egress.get("retry_max_ms", 60000))
        self.egress_lora_uart = int(egress.get("uart_id", 2))
        self.egress_lora_tx = int(egress.get("tx_pin", 17))
        self.egress_lora_rx = int(egress.get("rx_pin", 18))
        self.egress_lora_baudrate = int(egress.get("baudrate", 9600))

        lora = settings_data.get("lora", {})
        if not isinstance(lora, dict):
            raise ValueError("lora must be an object")
        self.lora_frequency = int(lora.get("frequency", 868000000))
        self.lora_spreading_factor = int(lora.get("spreading_factor", 7))
        self.lora_bandwidth = int(lora.get("bandwidth", 125000))
        self.lora_coding_rate = int(lora.get("coding_rate", 5))
        self.lora_tx_power = int(lora.get("tx_power", 14))
        self.lora_spi_id = int(lora.get("spi_id", 1))
        # Seeed 113110064 uses the Wio-SX1262 B2B connector. These are
        # ESP32-S3 GPIO numbers, not the pin-header layout of other Wio boards.
        self.lora_sck_pin = int(lora.get("sck_pin", 7))
        self.lora_mosi_pin = int(lora.get("mosi_pin", 9))
        self.lora_miso_pin = int(lora.get("miso_pin", 8))
        self.lora_cs_pin = int(lora.get("cs_pin", 41))
        self.lora_reset_pin = int(lora.get("reset_pin", 42))
        self.lora_busy_pin = int(lora.get("busy_pin", 40))
        self.lora_dio1_pin = int(lora.get("dio1_pin", 39))
        self.lora_rf_switch_pin = int(lora.get("rf_switch_pin", 38))
        self.lora_key = str(lora.get("key", "")).encode("utf-8")
        self.lora_ack_timeout_ms = int(lora.get("ack_timeout_ms", 1500))
        self.lora_max_retries = int(lora.get("max_retries", 3))

        storage = settings_data.get("storage", {})
        self.storage_directory = storage.get("directory", "logs")
        self.storage_max_bytes = int(storage.get("max_bytes", 262144))
        self.storage_max_files = int(storage.get("max_files", 8))
        self.storage_ring_size = int(storage.get("ring_size", 256))

        self._validate(device, mesh, egress, lora)

    def _validate(self, device, mesh, egress, lora):
        if self.role not in ("node", "gateway", "standalone", "lora_sink"):
            raise ValueError("device.role must be node, gateway, lora_sink or standalone")

        if self.role == "lora_sink":
            if egress:
                raise ValueError("egress configuration belongs to the gateway role")
            if self.mesh_enabled:
                raise ValueError("lora_sink must set mesh.enabled=false")
            if not self.management_enabled:
                raise ValueError("lora_sink requires management.enabled=true")
            if len(self.lora_key) < 16 or is_placeholder_secret(lora.get("key", "")):
                raise ValueError("lora.key must be a non-placeholder value of at least 16 bytes")
            if self.storage_max_bytes < 4096 or self.storage_max_files < 1:
                raise ValueError("storage limits are too small")

        if self.egress_enabled and "lora" in self.egress_backends:
            if len(self.lora_key) < 16 or is_placeholder_secret(lora.get("key", "")):
                raise ValueError("lora.key must be a non-placeholder value of at least 16 bytes")

        if not 150000000 <= self.lora_frequency <= 960000000:
            raise ValueError("lora.frequency is outside SX1262 range")
        if self.lora_spreading_factor not in range(5, 13):
            raise ValueError("lora.spreading_factor must be between 5 and 12")
        if self.lora_bandwidth not in (125000, 250000, 500000):
            raise ValueError("lora.bandwidth must be 125000, 250000 or 500000")
        if self.lora_coding_rate not in (5, 6, 7, 8):
            raise ValueError("lora.coding_rate must be between 5 and 8")
        if self.lora_tx_power < -9 or self.lora_tx_power > 22:
            raise ValueError("lora.tx_power must be between -9 and 22")
        if self.lora_ack_timeout_ms < 250 or self.lora_max_retries not in range(0, 11):
            raise ValueError("invalid LoRa retry policy")

        if self.data_source:
            if not self.mesh_only:
                raise ValueError(
                    "device.data_source requires device.mesh_only=true"
                )
            if self.role != "node":
                raise ValueError(
                    "device.data_source is only supported on node role"
                )
            if not self.mesh_enabled:
                raise ValueError(
                    "device.data_source requires mesh.enabled=true"
                )

        if self.mesh_enabled and self.role in ("node", "gateway"):
            if self.mesh_protocol_version != 4:
                raise ValueError("mesh.protocol_version must be 4")
            if self.mesh_transport != "espnow":
                raise ValueError(
                    "mesh.transport must be espnow; LoRa mesh is not implemented"
                )
            if "mesh_only" not in device:
                raise ValueError(
                    "device.mesh_only must be set explicitly for node and "
                    "gateway roles"
                )
            if not self.mesh_only and not self.allow_hid_with_mesh:
                raise ValueError(
                    "device.mesh_only must be true for node and gateway roles; "
                    "set device.allow_hid_with_mesh=true only for an authorized "
                    "HID plus mesh build"
                )
            if is_placeholder_secret(mesh.get("peer_key", "")):
                raise ValueError(
                    "mesh.peer_key must be set to a non-placeholder value"
                )
            if not self.mesh_peer_macs:
                raise ValueError(
                    "mesh.peer_macs must contain at least one unicast MAC"
                )

        if self.mesh_only and not self.mesh_enabled:
            raise ValueError("device.mesh_only requires mesh.enabled=true")
        if self.mesh_only and self.role not in ("node", "gateway"):
            raise ValueError(
                "device.mesh_only is only supported on node or gateway role"
            )

        if self.role == "node":
            if not self.uplink_mesh and not self.uplink_sendmy:
                raise ValueError("node must enable uplink.mesh or uplink.sendmy")
            if self.delivery_mode not in ("best", "primary", "all"):
                raise ValueError("delivery.mode must be best, primary or all")
            if self.uplink_mesh and not self.delivery_gateways:
                raise ValueError("delivery.gateways must contain at least one gateway")
            unknown = [gateway for gateway in self.delivery_gateways
                       if gateway not in self.mesh_peer_macs]
            if self.uplink_mesh and unknown:
                raise ValueError("delivery.gateways references unknown mesh peers")

        if self.sendmy_enabled or self.uplink_sendmy or "sendmy" in self.egress_backends:
            if not self.sendmy_modem_id:
                raise ValueError("sendmy.modem_id is required")
            if not 32 <= self.sendmy_max_message_bytes <= 220:
                raise ValueError("sendmy.max_message_bytes must be between 32 and 220")
            if not 1 <= self.sendmy_max_pending <= 1024:
                raise ValueError("sendmy.max_pending must be between 1 and 1024")
            if not 1000 <= self.sendmy_batch_interval_ms <= 86400000:
                raise ValueError(
                    "sendmy.batch_interval_ms must be between 1000 and 86400000"
                )
            if not 1 <= self.sendmy_batch_size <= 256:
                raise ValueError("sendmy.batch_size must be between 1 and 256")
            if self.sendmy_baudrate < 1200:
                raise ValueError("sendmy.baudrate must be at least 1200")
        if (self.role == "gateway" and self.network_direct_sendmy
                and "sendmy" in self.egress_backends):
            raise ValueError("gateway sendmy conflicts with direct implant sendmy")

        if self.management_enabled:
            if is_placeholder_secret(self.password):
                raise ValueError(
                    "management.password must be set to a non-placeholder value"
                )
            if self.mode == "ap" and len(self.password) < 8:
                raise ValueError(
                    "management.password must be at least 8 characters in AP mode"
                )
            if is_placeholder_secret(self.api_token):
                raise ValueError(
                    "management.api_token must be set to a non-placeholder value"
                )
            if len(self.api_token) < 16:
                raise ValueError(
                    "management.api_token must be at least 16 characters"
                )

        if self.role != "gateway" and egress:
            raise ValueError("egress configuration belongs to the gateway role")

        if self.role == "gateway" and not self.egress_enabled:
            raise ValueError("gateway must keep egress enabled")

        if self.egress_enabled:
            if self.role != "gateway":
                raise ValueError("egress is only supported on gateway role")
            if self.egress_backend == "none" and self.egress_backends == ["none"]:
                raise ValueError(
                    "egress.backend must be log, wifi, lora or sendmy when enabled"
                )
            if (not self.egress_backends or any(
                    backend not in ("log", "wifi", "lora", "sendmy")
                    for backend in self.egress_backends)):
                raise ValueError(
                    "egress backends must be log, wifi, lora or sendmy"
                )
            if "wifi" in self.egress_backends:
                if not self.egress_url:
                    raise ValueError(
                        "egress.url is required for the wifi backend"
                    )
                if not self.management_enabled:
                    raise ValueError(
                        "egress wifi requires management.enabled=true"
                    )
            if "lora" in self.egress_backends and self.egress_lora_baudrate < 1200:
                raise ValueError(
                    "egress.baudrate must be at least 1200 for the lora backend"
                )
            if self.egress_max_pending < 1 or self.egress_max_pending > 4096:
                raise ValueError("egress.max_pending must be between 1 and 4096")
            if self.egress_retry_base_ms < 100:
                raise ValueError("egress.retry_base_ms must be at least 100")
            if self.egress_retry_max_ms < self.egress_retry_base_ms:
                raise ValueError(
                    "egress.retry_max_ms must be at least retry_base_ms"
                )
