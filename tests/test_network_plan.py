import pytest

from network_plan import PlanError, render_settings, validate_plan, write_rendered


TEST_KEY = "test-key-1234567"


def sample_mac(last):
    return ":".join(("02", "00", "00", "00", "00", last))


def plan():
    lora = {"frequency": 868000000, "spreading_factor": 7,
            "bandwidth": 125000, "coding_rate": 5,
            "key": "test-lora-key-01"}
    return {
        "network": {"id": "lab", "channel": 6,
                    "peer_key": TEST_KEY, "protocol_version": 4},
        "gateways": [{"id": "gateway-01", "mac": sample_mac("01"),
                      "egress": ["lora"], "lora": dict(lora)}],
        "implants": [{"id": "implant-a", "mac": sample_mac("11"),
                      "uplink": {"mesh": True, "sendmy": False}, "relay": True}],
        "lora_sink": {"id": "sink-01", "mac": sample_mac("21"),
                      "lora": dict(lora),
                      "management": {"enabled": True, "mode": "ap",
                                     "ssid": "sink",
                                     "password": "unit-test-password",
                                     "api_token": "unit-test-api-token-value"}},
    }


def test_plan_renders_all_devices_and_delivery_defaults():
    rendered = render_settings(plan())
    assert set(rendered) == {"gateway-01", "implant-a", "sink-01"}
    assert rendered["implant-a"]["delivery"] == {
        "mode": "best", "gateways": ["gateway-01"]}
    assert rendered["gateway-01"]["egress"]["backends"] == ["lora"]
    assert rendered["sink-01"]["mesh"]["enabled"] is False
    assert "egress" not in rendered["sink-01"]


def test_plan_rejects_duplicate_ids_and_macs():
    value = plan()
    value["implants"][0]["id"] = "gateway-01"
    with pytest.raises(PlanError, match="IDs"):
        validate_plan(value)
    value = plan()
    value["implants"][0]["mac"] = value["gateways"][0]["mac"]
    with pytest.raises(PlanError, match="MACs"):
        validate_plan(value)


def test_plan_requires_one_implant_uplink():
    value = plan()
    value["implants"][0]["uplink"] = {"mesh": False, "sendmy": False}
    with pytest.raises(PlanError, match="mesh or sendmy"):
        validate_plan(value)


def test_direct_sendmy_conflicts_with_gateway_sendmy():
    value = plan()
    value["implants"][0]["uplink"]["sendmy"] = True
    value["gateways"][0]["egress"] = ["sendmy"]
    with pytest.raises(PlanError, match="conflicts"):
        validate_plan(value)


def test_direct_sendmy_requires_modem_id():
    value = plan()
    value["implants"][0]["uplink"]["sendmy"] = True
    with pytest.raises(PlanError, match="modem_id"):
        validate_plan(value)


def test_wifi_gateway_requires_collector_url():
    value = plan()
    value["gateways"][0]["egress"] = ["wifi"]
    value.pop("lora_sink")
    with pytest.raises(PlanError, match="URL"):
        validate_plan(value)


def test_delivery_rejects_unknown_gateway():
    value = plan()
    value["implants"][0]["delivery"] = {
        "mode": "primary", "gateways": ["missing"]}
    with pytest.raises(PlanError, match="unknown gateway"):
        validate_plan(value)


def test_lora_settings_must_match_sink():
    value = plan()
    value["lora_sink"]["lora"]["frequency"] = 915000000
    with pytest.raises(PlanError, match="must match"):
        validate_plan(value)


def test_write_rendered_creates_settings_summary_and_manifest(tmp_path):
    import json
    from settings import Settings
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan()), encoding="utf-8")
    output = tmp_path / "rendered"
    write_rendered(str(plan_path), str(output))
    assert (output / "implant-a.json").is_file()
    assert (output / "network-plan.rendered.json").is_file()
    for device_id in ("gateway-01", "implant-a", "sink-01"):
        Settings(str(output / (device_id + ".json")))
    manifest = (output / "device-manifest.tsv").read_text(encoding="utf-8")
    assert "implant-a\t%s\tnode" % sample_mac("11") in manifest


def test_direct_sendmy_rejects_invalid_batch_interval():
    value = plan()
    value["implants"][0]["uplink"]["sendmy"] = True
    value["sendmy"] = {"modem_id": "42424242", "batch_interval_ms": 500}
    with pytest.raises(PlanError, match="batch_interval_ms"):
        validate_plan(value)


def test_direct_sendmy_rejects_invalid_batch_size():
    value = plan()
    value["implants"][0]["uplink"]["sendmy"] = True
    value["sendmy"] = {"modem_id": "42424242", "batch_size": 0}
    with pytest.raises(PlanError, match="batch_size"):
        validate_plan(value)


def test_rendered_sendmy_keeps_batch_settings():
    value = plan()
    value["implants"][0]["uplink"]["sendmy"] = True
    value["sendmy"] = {"modem_id": "42424242", "batch_interval_ms": 30000,
                       "batch_size": 16}
    rendered = render_settings(value)
    assert rendered["implant-a"]["sendmy"]["enabled"] is True
    assert rendered["implant-a"]["sendmy"]["batch_interval_ms"] == 30000
    assert rendered["implant-a"]["sendmy"]["batch_size"] == 16
