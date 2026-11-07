import json

import pytest

from settings import Settings


TEST_KEY = "test-key-1234567"
TEST_TOKEN = "unit-test-api-token-value"
TEST_PASSWORD = "unit-test-password"


def sample_mac(last="01", first="02"):
    return ":".join((first, "00", "00", "00", "00", last))


def write_config(tmp_path, data):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def node_config():
    return {
        "device": {
            "role": "node",
            "id": "node-01",
            "mesh_only": True,
            "local_ui": False,
        },
        "management": {"enabled": False},
        "mesh": {
            "enabled": True,
            "network_id": "lab-mesh",
            "gateway_id": "gateway-01",
            "channel": 6,
            "peer_key": TEST_KEY,
            "peer_macs": {"gateway-01": sample_mac()},
        },
    }


def gateway_config():
    return {
        "device": {
            "role": "gateway",
            "id": "gateway-01",
            "mesh_only": True,
            "local_ui": True,
        },
        "management": {
            "enabled": True,
            "mode": "ap",
            "ssid": "meshops-gateway",
            "password": TEST_PASSWORD,
            "api_token": TEST_TOKEN,
        },
        "mesh": {
            "enabled": True,
            "network_id": "lab-mesh",
            "gateway_id": "gateway-01",
            "channel": 6,
            "peer_key": TEST_KEY,
            "peer_macs": {"node-01": sample_mac("02")},
        },
    }


def receiver_config():
    return {
        "device": {"role": "lora_sink", "id": "sink-01", "mesh_only": False},
        "management": {"enabled": True, "mode": "ap", "ssid": "sink",
                       "password": TEST_PASSWORD, "api_token": TEST_TOKEN},
        "mesh": {"enabled": False},
        "lora": {"key": "test-lora-key-01", "frequency": 868000000},
        "storage": {"max_bytes": 4096, "max_files": 2},
    }


def test_valid_lora_sink_config(tmp_path):
    settings = Settings(write_config(tmp_path, receiver_config()))
    assert settings.role == "lora_sink"
    assert settings.lora_frequency == 868000000
    assert settings.storage_max_files == 2
    assert (settings.lora_sck_pin, settings.lora_miso_pin,
            settings.lora_mosi_pin) == (7, 8, 9)
    assert (settings.lora_cs_pin, settings.lora_reset_pin,
            settings.lora_busy_pin, settings.lora_dio1_pin,
            settings.lora_rf_switch_pin) == (41, 42, 40, 39, 38)


def test_lora_sink_requires_key_and_management(tmp_path):
    config = receiver_config(); config["lora"]["key"] = "short"
    with pytest.raises(ValueError, match="lora.key"):
        Settings(write_config(tmp_path, config))
    config = receiver_config(); config["management"]["enabled"] = False
    with pytest.raises(ValueError, match="management"):
        Settings(write_config(tmp_path, config))


def test_valid_node_config(tmp_path):
    settings = Settings(write_config(tmp_path, node_config()))
    assert settings.role == "node"
    assert settings.mesh_only is True
    assert settings.mesh_peer_key == TEST_KEY.encode()
    assert settings.management_enabled is False
    assert settings.mesh_transport == "espnow"


def test_unsupported_mesh_transport_rejected(tmp_path):
    config = node_config()
    config["mesh"]["transport"] = "lora"
    with pytest.raises(ValueError, match="mesh.transport"):
        Settings(write_config(tmp_path, config))


def test_valid_gateway_config(tmp_path):
    settings = Settings(write_config(tmp_path, gateway_config()))
    assert settings.role == "gateway"
    assert settings.mesh_only is True
    assert settings.management_enabled is True
    assert settings.api_token == TEST_TOKEN


def test_mesh_role_requires_explicit_mesh_only(tmp_path):
    config = node_config()
    del config["device"]["mesh_only"]
    with pytest.raises(ValueError, match="mesh_only"):
        Settings(write_config(tmp_path, config))


def test_mesh_role_rejects_hid_without_override(tmp_path):
    config = node_config()
    config["device"]["mesh_only"] = False
    with pytest.raises(ValueError, match="mesh_only"):
        Settings(write_config(tmp_path, config))


def test_mesh_role_allows_explicit_hid_override(tmp_path):
    config = node_config()
    config["device"]["mesh_only"] = False
    config["device"]["allow_hid_with_mesh"] = True
    settings = Settings(write_config(tmp_path, config))
    assert settings.mesh_only is False
    assert settings.allow_hid_with_mesh is True


def test_placeholder_password_rejected(tmp_path):
    config = gateway_config()
    config["management"]["password"] = "CHANGE_ME_PASSWORD"
    with pytest.raises(ValueError, match="password"):
        Settings(write_config(tmp_path, config))


def test_short_password_rejected(tmp_path):
    config = gateway_config()
    config["management"]["password"] = "short"
    with pytest.raises(ValueError, match="at least 8"):
        Settings(write_config(tmp_path, config))


def test_placeholder_api_token_rejected(tmp_path):
    config = gateway_config()
    config["management"]["api_token"] = "CHANGE_ME_TOKEN_32_CHARS"
    with pytest.raises(ValueError, match="api_token"):
        Settings(write_config(tmp_path, config))


def test_short_api_token_rejected(tmp_path):
    config = gateway_config()
    config["management"]["api_token"] = "short"
    with pytest.raises(ValueError, match="at least 16"):
        Settings(write_config(tmp_path, config))


def test_empty_peer_key_rejected(tmp_path):
    config = node_config()
    config["mesh"]["peer_key"] = ""
    with pytest.raises(ValueError, match="peer_key"):
        Settings(write_config(tmp_path, config))


def test_wrong_peer_key_length_rejected(tmp_path):
    config = node_config()
    config["mesh"]["peer_key"] = "short"
    with pytest.raises(ValueError, match="16 UTF-8 bytes"):
        Settings(write_config(tmp_path, config))


def test_placeholder_peer_key_rejected(tmp_path):
    config = node_config()
    config["mesh"]["peer_key"] = "CHANGE_ME_16BYTE"
    with pytest.raises(ValueError, match="peer_key"):
        Settings(write_config(tmp_path, config))


def test_peer_mac_allowlist(tmp_path):
    config = node_config()
    config["mesh"]["peer_macs"] = {"gateway-01": sample_mac("90", "0a")}
    settings = Settings(write_config(tmp_path, config))
    assert settings.mesh_peer_macs["gateway-01"] == bytes.fromhex("0a0000000090")


def test_invalid_peer_mac_rejected(tmp_path):
    config = node_config()
    config["mesh"]["peer_macs"] = {"gateway-01": ":".join(("7c", "e8", "b1", "e5", "49"))}
    with pytest.raises(ValueError, match="invalid MAC"):
        Settings(write_config(tmp_path, config))


def test_multicast_peer_mac_rejected(tmp_path):
    config = node_config()
    config["mesh"]["peer_macs"] = {"gateway-01": ":".join(("01", "e8", "b1", "e5", "49", "90"))}
    with pytest.raises(ValueError, match="unicast"):
        Settings(write_config(tmp_path, config))


def test_empty_peer_mac_allowlist_rejected(tmp_path):
    config = node_config()
    config["mesh"]["peer_macs"] = {}
    with pytest.raises(ValueError, match="at least one unicast MAC"):
        Settings(write_config(tmp_path, config))


def test_all_zero_peer_mac_is_not_an_allowlist(tmp_path):
    config = node_config()
    config["mesh"]["peer_macs"] = {"gateway-01": ":".join(("00",) * 6)}
    with pytest.raises(ValueError, match="at least one unicast MAC"):
        Settings(write_config(tmp_path, config))


def test_data_source_requires_mesh_only(tmp_path):
    config = node_config()
    config["device"]["mesh_only"] = False
    config["device"]["allow_hid_with_mesh"] = True
    config["device"]["data_source"] = True
    with pytest.raises(ValueError, match="data_source"):
        Settings(write_config(tmp_path, config))


def test_data_source_requires_node_role(tmp_path):
    config = gateway_config()
    config["device"]["data_source"] = True
    with pytest.raises(ValueError, match="node role"):
        Settings(write_config(tmp_path, config))


def test_wifi_egress_requires_url(tmp_path):
    config = gateway_config()
    config["egress"] = {"enabled": True, "backend": "wifi"}
    with pytest.raises(ValueError, match="egress.url"):
        Settings(write_config(tmp_path, config))


def test_valid_wifi_egress(tmp_path):
    config = gateway_config()
    config["egress"] = {
        "enabled": True,
        "backend": "wifi",
        "url": "https://collector.example.test/mesh",
    }
    settings = Settings(write_config(tmp_path, config))
    assert settings.egress_enabled is True
    assert settings.egress_backend == "wifi"


def test_egress_retry_window_is_validated(tmp_path):
    config = gateway_config()
    config["egress"] = {
        "enabled": True,
        "backend": "log",
        "retry_base_ms": 1000,
        "retry_max_ms": 500,
    }
    with pytest.raises(ValueError, match="retry_max_ms"):
        Settings(write_config(tmp_path, config))


def test_egress_requires_gateway_role(tmp_path):
    config = node_config()
    config["egress"] = {"enabled": True, "backend": "log"}
    with pytest.raises(ValueError, match="gateway role"):
        Settings(write_config(tmp_path, config))


def test_enabled_egress_needs_real_backend(tmp_path):
    config = gateway_config()
    config["egress"] = {"enabled": True, "backend": "none"}
    with pytest.raises(ValueError, match="when enabled"):
        Settings(write_config(tmp_path, config))


def test_mesh_only_requires_mesh_enabled(tmp_path):
    config = node_config()
    config["mesh"]["enabled"] = False
    with pytest.raises(ValueError, match="mesh.enabled"):
        Settings(write_config(tmp_path, config))


def test_synthetic_telemetry_defaults_true(tmp_path):
    settings = Settings(write_config(tmp_path, node_config()))
    assert settings.synthetic_telemetry is True


def test_synthetic_telemetry_can_be_disabled(tmp_path):
    config = node_config()
    config["device"]["synthetic_telemetry"] = False
    settings = Settings(write_config(tmp_path, config))
    assert settings.synthetic_telemetry is False


def test_delivery_mode_and_gateways_are_loaded(tmp_path):
    config = node_config()
    config["delivery"] = {"mode": "all", "gateways": ["gateway-01"]}
    settings = Settings(write_config(tmp_path, config))
    assert settings.delivery_mode == "all"
    assert settings.delivery_gateways == ["gateway-01"]


def test_delivery_rejects_unknown_gateway(tmp_path):
    config = node_config()
    config["delivery"] = {"mode": "best", "gateways": ["missing"]}
    with pytest.raises(ValueError, match="unknown"):
        Settings(write_config(tmp_path, config))


def test_sendmy_uplink_requires_modem_id(tmp_path):
    config = node_config()
    config["uplink"] = {"mesh": True, "sendmy": True}
    config["sendmy"] = {"enabled": True}
    with pytest.raises(ValueError, match="modem_id"):
        Settings(write_config(tmp_path, config))


def test_valid_sendmy_uplink(tmp_path):
    config = node_config()
    config["uplink"] = {"mesh": True, "sendmy": True}
    config["sendmy"] = {"enabled": True, "modem_id": "42424242"}
    settings = Settings(write_config(tmp_path, config))
    assert settings.uplink_mesh is True
    assert settings.uplink_sendmy is True
    assert settings.sendmy_max_message_bytes == 180


def test_gateway_runtime_rejects_direct_and_gateway_sendmy_conflict(tmp_path):
    config = gateway_config()
    config["network_policy"] = {"direct_sendmy": True}
    config["egress"] = {"enabled": True, "backend": "sendmy",
                        "backends": ["sendmy"]}
    config["sendmy"] = {"enabled": True, "modem_id": "42424242"}
    with pytest.raises(ValueError, match="conflicts"):
        Settings(write_config(tmp_path, config))
