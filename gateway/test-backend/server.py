"""
Dummy backend – Phase 1
Single-file HTTP server (stdlib only) that identifies itself so
load-balancing across backend-1 and backend-2 can be verified.
No frameworks. No external dependencies.
"""
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

BACKEND_NAME = os.getenv("BACKEND_NAME", "backend-unknown")
PORT = int(os.getenv("BACKEND_PORT", "8000"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: N802
        # Forward access logs to stdout (visible via docker logs)
        print(f"[{BACKEND_NAME}] {fmt % args}", flush=True)

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Served-By", BACKEND_NAME)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send_json({"status": "ok", "backend": BACKEND_NAME})
        else:
            self._send_json(
                {
                    "message": f"Hello from {BACKEND_NAME}",
                    "backend": BACKEND_NAME,
                    "hostname": socket.gethostname(),
                    "path": self.path,
                }
            )


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[{BACKEND_NAME}] listening on :{PORT}", flush=True)
    server.serve_forever()
