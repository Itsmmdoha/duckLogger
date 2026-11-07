import asyncio
import os
from microdot import Microdot, send_file, Response
from microdot.websocket import WebSocketError, with_websocket
from queue import Queue
from json import dump as json_dump, load as json_load, dumps as json_dumps
from settings import is_placeholder_secret
from settings import Settings

FILE_PATH = "log.txt"
INDEX_PATH = "index.html.gz"
SETTINGS_PATH = "settings.json"
MAX_SCRIPT_BYTES = 4096


def file_exists(path=FILE_PATH):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


class DuckLoggerAPI:
    """wraper for microdot, with two public queues:
     - keys:  for storing incoming keys from remote kbd
     - script: for storing incoming duckyscripts
    """
    def __init__(self, mesh=None, mesh_log_path="mesh-log.jsonl",
                 hid_controls=True, api_token="", egress=None) -> None:
        self.app = Microdot()
        self.keys = Queue()
        self.scripts = Queue()
        self.script_execution = Queue()
        self.mesh = mesh
        self.mesh_log_path = mesh_log_path
        self.hid_controls = hid_controls
        self.api_token = api_token
        self.egress = egress
        self.setup_routes()

    def _authorized(self, request):
        if not self.api_token:
            return False
        if request.headers.get("Authorization", "") == "Bearer " + self.api_token:
            return True
        if request.args and request.args.get("token", "") == self.api_token:
            return True
        return request.headers.get("X-API-Key", "") == self.api_token

    def _require_auth(self, request):
        if self._authorized(request):
            return None
        return Response(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _public_settings(self):
        with open(SETTINGS_PATH, "r") as f:
            data = json_load(f)
        data.pop("password", None)
        data.pop("api_token", None)
        management = data.get("management")
        if isinstance(management, dict):
            management.pop("password", None)
            management.pop("api_token", None)
        mesh = data.get("mesh")
        if isinstance(mesh, dict):
            mesh.pop("peer_key", None)
            mesh.pop("peer_macs", None)
        return data

    def _mesh_status(self):
        status = self.mesh.status()
        status["egress"] = (
            self.egress.status() if self.egress is not None else {
                "enabled": False, "backend": "none", "pending": 0
            }
        )
        return status

    def _gateway_config(self):
        with open(SETTINGS_PATH, "r") as source:
            data = json_load(source)
        egress = data.get("egress", {})
        lora = data.get("lora", {})
        management = data.get("management", {})
        return {
            "egress": {
                "enabled": bool(egress.get("enabled", False)),
                "backend": egress.get("backend", "none"),
                "url": egress.get("url", ""),
                "batch_size": int(egress.get("batch_size", 10)),
                "interval_ms": int(egress.get("interval_ms", 5000)),
            },
            "lora": {
                "frequency": int(lora.get("frequency", 868000000)),
                "spreading_factor": int(lora.get("spreading_factor", 7)),
                "bandwidth": int(lora.get("bandwidth", 125000)),
                "coding_rate": int(lora.get("coding_rate", 5)),
                "tx_power": int(lora.get("tx_power", 14)),
            },
            "management": {
                "mode": management.get("mode", "ap"),
                "ssid": management.get("ssid", ""),
            },
        }

    def _update_gateway_config(self, updates):
        if not isinstance(updates, dict):
            raise ValueError("configuration must be an object")
        with open(SETTINGS_PATH, "r") as source:
            data = json_load(source)
        allowed = {
            "egress": ("enabled", "backend", "url", "batch_size", "interval_ms"),
            "lora": ("frequency", "spreading_factor", "bandwidth",
                     "coding_rate", "tx_power"),
            "management": ("mode", "ssid", "password"),
        }
        for section, keys in allowed.items():
            values = updates.get(section)
            if values is None:
                continue
            if not isinstance(values, dict):
                raise ValueError("%s must be an object" % section)
            target = data.setdefault(section, {})
            for key in values:
                if key not in keys:
                    raise ValueError("unsupported %s setting" % key)
                target[key] = values[key]
        temporary = SETTINGS_PATH + ".pending"
        with open(temporary, "w") as output:
            json_dump(data, output)
        try:
            Settings(temporary)
            try:
                os.remove(SETTINGS_PATH)
            except OSError:
                pass
            os.rename(temporary, SETTINGS_PATH)
        except Exception:
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise
        return self._gateway_config()

    def setup_routes(self):
        @self.app.route("/")
        async def index(request):
            if not file_exists(INDEX_PATH):
                return "not found", 404
            return send_file(
                INDEX_PATH,
                content_type="text/html",
                compressed=True
            )

        @self.app.route("/log", methods=["GET"])
        async def download_log(request):
            denied = self._require_auth(request)
            if denied is not None:
                return denied
            if not file_exists():
                return "<h3>404 Not Found</h3>", 404
            return send_file(
                FILE_PATH,
                content_type="text/plain",
            )

        @self.app.route("/log", methods=["DELETE"])
        async def delete_log(request):
            denied = self._require_auth(request)
            if denied is not None:
                return denied
            try:
                os.remove(FILE_PATH)
                return "deleted", 200
            except OSError:
                return "file not found", 404

        @self.app.route("/script", methods=["POST"])
        async def script_upload(request):
            """
            Accepts a duckyscript via POST (raw text)
            and enqueues it for processing.
            """
            denied = self._require_auth(request)
            if denied is not None:
                return denied
            if not self.hid_controls:
                return Response("HID controls are disabled on this gateway",
                                status_code=409)
            if request.body is None:
                return Response("Empty script", status_code=400)
            if len(request.body) > MAX_SCRIPT_BYTES:
                return Response("Script too large", status_code=413)
            script_text = request.body.decode("utf-8")
            if not script_text.strip():
                return Response("Empty script", status_code=400)

            self.scripts.enqueue(script_text)

            while self.script_execution.is_empty():
                await asyncio.sleep_ms(50)
            execution_status = self.script_execution.dequeue()
            if execution_status != "Success":
                return Response(execution_status, status_code=400)
            return Response("Script Executed Successfully", status_code=200)

        @self.app.route('/kbd')
        @with_websocket
        async def kbd(request, ws):
            denied = self._require_auth(request)
            if denied is not None:
                await ws.close()
                return
            if not self.hid_controls:
                await ws.close()
                return
            while True:
                try:
                    message = await ws.receive()
                    self.keys.enqueue(message)
                    await ws.send(message)
                except WebSocketError:
                    break

        @self.app.route("/settings", methods=["GET"])
        async def get_settings(request):
            denied = self._require_auth(request)
            if denied is not None:
                return denied
            try:
                return Response(
                    json_dumps(self._public_settings()),
                    headers={"Content-Type": "application/json"},
                )
            except (OSError, ValueError):
                return "file not found", 404

        @self.app.route("/settings", methods=["POST"])
        async def update_settings(request):
            denied = self._require_auth(request)
            if denied is not None:
                return denied
            try:
                settings = request.json
                if settings.get("mode") not in ("ap", "sta"):
                    return Response("Invalid mode", status_code=400)
                password = str(settings.get("password", ""))
                if is_placeholder_secret(password) or len(password) < 8:
                    return Response("Invalid password", status_code=400)
                try:
                    with open(SETTINGS_PATH, "r") as f:
                        settings_data = json_load(f)
                except (OSError, ValueError):
                    settings_data = {}
                # Preserve MeshOps/device fields when the legacy web UI edits
                # only the Wi-Fi portion of the settings file.
                updates = {
                    "mode": settings["mode"],
                    "ssid": settings["ssid"],
                    "password": settings["password"],
                }
                management = settings_data.get("management")
                if isinstance(management, dict):
                    management.update(updates)
                else:
                    settings_data.update(updates)
                with open(SETTINGS_PATH, "w") as f:
                    json_dump(settings_data, f)
                return "Success", 200
            except (KeyError, TypeError, ValueError):
                return "Invalid Settings", 400

        if self.mesh is not None:
            @self.app.route("/mesh/status", methods=["GET"])
            async def mesh_status(request):
                denied = self._require_auth(request)
                if denied is not None:
                    return denied
                return Response(
                    json_dumps(self._mesh_status()),
                    headers={"Content-Type": "application/json"},
                )

            @self.app.route("/mesh/log", methods=["GET"])
            async def mesh_log(request):
                denied = self._require_auth(request)
                if denied is not None:
                    return denied
                try:
                    return send_file(
                        self.mesh_log_path,
                        content_type="application/x-ndjson",
                    )
                except OSError:
                    return "file not found", 404

            @self.app.route("/mesh/log", methods=["DELETE"])
            async def delete_mesh_log(request):
                denied = self._require_auth(request)
                if denied is not None:
                    return denied
                try:
                    os.remove(self.mesh_log_path)
                    return "deleted", 200
                except OSError:
                    return "file not found", 404

            @self.app.route("/gateway/config", methods=["GET"])
            async def gateway_config(request):
                denied = self._require_auth(request)
                if denied is not None:
                    return denied
                try:
                    return Response(json_dumps(self._gateway_config()),
                                    headers={"Content-Type": "application/json"})
                except (OSError, ValueError):
                    return "configuration unavailable", 404

            @self.app.route("/gateway/config", methods=["POST"])
            async def update_gateway_config(request):
                denied = self._require_auth(request)
                if denied is not None:
                    return denied
                try:
                    result = self._update_gateway_config(request.json)
                    return Response(json_dumps({"config": result, "reboot_required": True}),
                                    headers={"Content-Type": "application/json"})
                except (OSError, TypeError, ValueError) as exc:
                    return Response(str(exc), status_code=400)

    def start_server(self):
        """returns awaitable coroutine"""
        return self.app.start_server(host="0.0.0.0", port=80)
