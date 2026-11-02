import asyncio
import os
from microdot import Microdot, send_file, Response
from microdot.websocket import WebSocketError, with_websocket
from queue import Queue
from json import dump as json_dump, load as json_load, dumps as json_dumps

FILE_PATH = "log.txt"


def file_exists():
    try:
        os.stat(FILE_PATH)
        return True
    except OSError:
        return False


class DuckLoggerAPI:
    """wraper for microdot, with two public queues:
     - keys:  for storing incoming keys from remote kbd
     - script: for storing incoming duckyscripts
    """
    def __init__(self, mesh=None, mesh_log_path="mesh-log.jsonl",
                 hid_controls=True) -> None:
        self.app = Microdot()
        self.keys = Queue()
        self.scripts = Queue()
        self.script_execution = Queue()
        self.mesh = mesh
        self.mesh_log_path = mesh_log_path
        self.hid_controls = hid_controls
        self.setup_routes()

    def setup_routes(self):
        @self.app.route("/")
        async def index(request):
            # sends index.html
            return send_file(
                "index.html.gz",
                content_type="text/html",
                compressed=True
            )

        @self.app.route("/log", methods=["GET"])
        async def download_log(request):
            if not file_exists():
                return "<h3>404 Not Found</h3>", 404
            # send file as download
            return send_file(
                FILE_PATH,
                content_type="text/plain",
            )

        @self.app.route("/log", methods=["DELETE"])
        async def delete_log(request):
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
            if not self.hid_controls:
                return Response("HID controls are disabled on this gateway",
                                status_code=409)
            script_text = request.body.decode("utf-8")
            # TODO: wil put validation here later
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
            try:
                return send_file(
                    "settings.json",
                    content_type="application/json",
                )
            except:
                return "file not found", 404
        @self.app.route("/settings", methods=["POST"])
        async def update_settings(request):
            try:
                settings = request.json
                try:
                    with open("settings.json", "r") as f:
                        settings_data = json_load(f)
                except (OSError, ValueError):
                    settings_data = {}
                # Preserve MeshOps/device fields when the legacy web UI edits
                # only the Wi-Fi portion of the settings file.
                settings_data.update({
                    "mode": settings["mode"],
                    "ssid": settings["ssid"],
                    "password": settings["password"],
                })
                with open("settings.json", "w") as f:
                    json_dump(settings_data, f)
                return "Success", 200
            except:
                return "Invalid Settings", 400

        if self.mesh is not None:
            @self.app.route("/mesh/status", methods=["GET"])
            async def mesh_status(request):
                return Response(
                    json_dumps(self.mesh.status()),
                    headers={"Content-Type": "application/json"},
                )

            @self.app.route("/mesh/log", methods=["GET"])
            async def mesh_log(request):
                try:
                    return send_file(
                        self.mesh_log_path,
                        content_type="application/x-ndjson",
                    )
                except OSError:
                    return "file not found", 404

            @self.app.route("/mesh/log", methods=["DELETE"])
            async def delete_mesh_log(request):
                try:
                    os.remove(self.mesh_log_path)
                    return "deleted", 200
                except OSError:
                    return "file not found", 404

    def start_server(self):
        """returns awaitable coroutine"""
        return self.app.start_server(host="0.0.0.0", port=80)
