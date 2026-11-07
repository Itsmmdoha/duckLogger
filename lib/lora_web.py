"""Authenticated HTTP API for the LoRa receiver console."""

try:
    import ujson as json
except ImportError:
    import json
from microdot import Microdot, Response, send_file


class LoRaSinkAPI:
    def __init__(self, sink, api_token, index_path="receiver.html.gz"):
        self.sink, self.api_token, self.index_path = sink, api_token, index_path
        self.app = Microdot(); self._routes()

    def _authorized(self, request):
        return bool(self.api_token) and (
            request.headers.get("Authorization", "") == "Bearer " + self.api_token or
            (request.args and request.args.get("token", "") == self.api_token) or
            request.headers.get("X-API-Key", "") == self.api_token)

    def _deny(self, request):
        if self._authorized(request): return None
        return Response("Unauthorized", status_code=401,
                        headers={"WWW-Authenticate": "Bearer"})

    def _json(self, value, status=200):
        return Response(json.dumps(value), status_code=status,
                        headers={"Content-Type": "application/json"})

    def _body(self, request):
        value = request.json
        if not isinstance(value, dict): raise ValueError("JSON object required")
        return value

    def _routes(self):
        @self.app.route("/")
        async def index(request):
            try: return send_file(self.index_path, content_type="text/html", compressed=True)
            except OSError: return "not found", 404

        @self.app.route("/api/status")
        async def status(request):
            denied = self._deny(request)
            return denied or self._json(self.sink.status())

        @self.app.route("/api/events")
        async def events(request):
            denied = self._deny(request)
            if denied: return denied
            args = request.args or {}
            try: since = max(0, int(args.get("since", 0))); limit = min(500, max(1, int(args.get("limit", 100))))
            except ValueError: return self._json({"error": "invalid pagination"}, 400)
            values = self.sink.query(since, limit, args.get("implant", ""),
                                     args.get("kind", ""), args.get("session", ""), args.get("q", ""))
            oldest = self.sink.events[0]["event_id"] if self.sink.events else self.sink.event_id
            return self._json({"events": values,
                               "next_since": values[-1]["event_id"] if values else since,
                               "truncated": bool(since and since < oldest - 1)})

        @self.app.route("/api/implants")
        async def implants(request):
            denied = self._deny(request); return denied or self._json(self.sink.implants)

        @self.app.route("/api/text")
        async def text_streams(request):
            denied = self._deny(request)
            if denied: return denied
            args = request.args or {}
            return self._json({"streams": self.sink.text_streams(
                args.get("implant", ""), args.get("session", ""))})

        @self.app.route("/api/implants/<implant_id>", methods=["PUT"])
        async def update_implant(request, implant_id):
            denied = self._deny(request)
            if denied: return denied
            try: return self._json(self.sink.update_implant(implant_id[:64], self._body(request)))
            except (ValueError, TypeError): return self._json({"error": "invalid implant"}, 400)

        @self.app.route("/api/sessions")
        async def sessions(request):
            denied = self._deny(request); return denied or self._json(self.sink.sessions)

        @self.app.route("/api/sessions/<session_id>", methods=["PUT"])
        async def update_session(request, session_id):
            denied = self._deny(request)
            if denied: return denied
            try: return self._json(self.sink.update_session(session_id, self._body(request)))
            except (ValueError, TypeError): return self._json({"error": "invalid session"}, 400)

        @self.app.route("/api/topology")
        async def topology(request):
            denied = self._deny(request)
            if denied: return denied
            latest = {}
            for event in self.sink.events:
                latest[event["source"]] = {"id": event["source"], "label": event["implant_label"],
                    "hops": event["hop_count"], "path": event["path"],
                    "last_hop": event["last_hop"], "last_event_id": event["event_id"]}
            return self._json({"nodes": list(latest.values())})

        @self.app.route("/api/logs")
        async def logs(request):
            denied = self._deny(request); return denied or self._json(self.sink.log_index())

        @self.app.route("/api/logs/<name>", methods=["GET"])
        async def get_log(request, name):
            denied = self._deny(request)
            if denied: return denied
            if name not in [entry["name"] for entry in self.sink.log_index()]: return "not found", 404
            return send_file(self.sink.directory + "/" + name, content_type="application/x-ndjson")

        @self.app.route("/api/logs/<name>", methods=["DELETE"])
        async def delete_log(request, name):
            denied = self._deny(request)
            if denied: return denied
            return ("deleted", 200) if self.sink.delete_log(name) else ("not found", 404)

    def start_server(self):
        return self.app.start_server(host="0.0.0.0", port=80)
