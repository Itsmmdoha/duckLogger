import json
import types

from api import DuckLoggerAPI


TOKEN = "unit-test-api-token-value"
TEST_KEY = "test-key-1234567"
TEST_MAC = ":".join(("0a", "00", "00", "00", "00", "90"))


def request(headers=None, args=None):
    return types.SimpleNamespace(headers=headers or {}, args=args or {})


def test_authorization_header():
    api = DuckLoggerAPI(api_token=TOKEN)
    assert api._authorized(
        request({"Authorization": "Bearer " + TOKEN})
    )


def test_query_token():
    api = DuckLoggerAPI(api_token=TOKEN)
    assert api._authorized(request(args={"token": TOKEN}))


def test_x_api_key_header():
    api = DuckLoggerAPI(api_token=TOKEN)
    assert api._authorized(request({"X-API-Key": TOKEN}))


def test_rejects_missing_or_wrong_token():
    api = DuckLoggerAPI(api_token=TOKEN)
    assert not api._authorized(request())
    assert not api._authorized(
        request({"Authorization": "Bearer wrong"})
    )


def test_require_auth_returns_401():
    api = DuckLoggerAPI(api_token=TOKEN)
    response = api._require_auth(request())
    assert response is not None
    assert response.status_code == 401


def test_public_settings_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps({
            "mode": "ap",
            "ssid": "duckLogger",
            "password": "unit-test-password",
            "api_token": TOKEN,
            "management": {
                "enabled": True,
                "password": "unit-test-password",
                "api_token": TOKEN,
            },
            "mesh": {
                "peer_key": TEST_KEY,
                "peer_macs": {"gateway-01": TEST_MAC},
            },
        }),
        encoding="utf-8",
    )
    api = DuckLoggerAPI(api_token=TOKEN)
    data = api._public_settings()
    assert "password" not in data
    assert "api_token" not in data
    assert "password" not in data["management"]
    assert "api_token" not in data["management"]
    assert "peer_key" not in data["mesh"]
    assert "peer_macs" not in data["mesh"]


def test_mesh_status_includes_egress_state():
    mesh = types.SimpleNamespace(status=lambda: {"role": "gateway"})
    egress = types.SimpleNamespace(status=lambda: {
        "enabled": True, "backend": "wifi", "pending": 3,
        "retry_count": 1,
    })
    api = DuckLoggerAPI(mesh=mesh, egress=egress, api_token=TOKEN)
    status = api._mesh_status()
    assert status["role"] == "gateway"
    assert status["egress"]["pending"] == 3
    assert status["egress"]["retry_count"] == 1


def test_gateway_config_update_is_validated_and_redacted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = {
        "device": {"role": "gateway", "id": "gateway-01", "mesh_only": True},
        "management": {"enabled": True, "mode": "ap", "ssid": "gateway",
                       "password": "unit-test-password", "api_token": TOKEN},
        "mesh": {"enabled": True, "network_id": "lab-mesh", "gateway_id": "gateway-01",
                 "peer_key": TEST_KEY,
                 "peer_macs": {"relay-01": TEST_MAC}},
        "egress": {"enabled": True, "backend": "lora"},
        "lora": {"key": "test-lora-key-01", "frequency": 868000000},
    }
    (tmp_path / "settings.json").write_text(json.dumps(config))
    api = DuckLoggerAPI(mesh=types.SimpleNamespace(status=lambda: {}), api_token=TOKEN)
    result = api._update_gateway_config({"egress": {"backend": "wifi", "url": "http://collector/mesh"}})
    assert result["egress"]["backend"] == "wifi"
    assert "key" not in result["lora"]
    with open(tmp_path / "settings.json") as source:
        saved = json.load(source)
    assert saved["lora"]["key"] == "test-lora-key-01"


def test_gateway_config_rejects_unknown_fields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({}))
    api = DuckLoggerAPI(api_token=TOKEN)
    try:
        api._update_gateway_config({"egress": {"shell": "no"}})
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unsafe setting accepted")
