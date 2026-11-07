import json

from mesh_store import MeshStore


def test_append_writes_ndjson_and_returns_record(tmp_path):
    path = tmp_path / "mesh-log.jsonl"
    store = MeshStore(str(path))
    record = store.append(
        {"n": "lab", "s": "node-01", "b": "boot-1", "q": 7,
         "k": "key_event", "x": "a", "h": 2},
        b"\x01\x02\x03\x04\x05\x06",
    )
    assert record["network_id"] == "lab"
    assert record["source"] == "node-01"
    assert record["boot_id"] == "boot-1"
    assert record["sequence"] == 7
    assert record["kind"] == "key_event"
    assert record["value"] == "a"
    assert record["hop_count"] == 2
    assert record["last_hop"] == "010203040506"
    assert "gateway_received_ms" in record
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == record
