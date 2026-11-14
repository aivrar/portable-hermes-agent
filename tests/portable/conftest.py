"""Shared fixtures for the portable tests."""

from __future__ import annotations

import http.server
import socket
import struct
import threading

import pytest


class ScriptedServer:
    """A local HTTP server that answers each request with the next scripted action.

    Actions: ``"ok"`` (200 with the body), ``"reset"`` (the connection is cut
    with a TCP reset before any answer), ``"truncate"`` (200 announcing the
    full length, half the body, then the connection is closed), an HTTP status
    code, or ``(status, {header: value})``. Once the script is used up every
    request gets ``"ok"``.
    """

    def __init__(self, body: bytes, script):
        self.body = body
        self.script = list(script)
        self.hits = 0
        self._lock = threading.Lock()
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                action = server._next()
                if action == "reset":
                    self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                               struct.pack("ii", 1, 0))
                    self.close_connection = True
                    self.connection.close()
                    return
                if action == "truncate":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(server.body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(server.body[:len(server.body) // 2])
                    self.close_connection = True
                    return
                status, headers = (200, {}) if action == "ok" else (
                    action if isinstance(action, tuple) else (action, {}))
                body = server.body if status == 200 else f"status {status}\n".encode()
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass        # the scripted resets make socketserver complain

        self.httpd = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def _next(self):
        with self._lock:
            self.hits += 1
            return self.script.pop(0) if self.script else "ok"

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/file.zip"

    def start(self) -> ScriptedServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def scripted_server():
    """``scripted_server(body, script)`` starts a :class:`ScriptedServer`."""
    servers = []

    def start(body: bytes, script=()) -> ScriptedServer:
        server = ScriptedServer(body, script).start()
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.stop()
