"""Tiny single-shot HTTP catcher for the FYERS OAuth redirect.

Listens on 127.0.0.1:5555, captures the first request's auth_code,
writes it to /tmp/fyers_auth_code, and exits.
"""

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

OUT = "/tmp/fyers_auth_code"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        code = qs.get("auth_code", [""])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if code:
            with open(OUT, "w") as f:
                f.write(code)
            self.wfile.write(b"<h1>OK</h1><p>auth_code captured. You can close this tab.</p>")
            print(f"auth_code received, written to {OUT}")
        else:
            self.wfile.write(b"<h1>No auth_code in query</h1>")
            print(f"no auth_code in request: {self.path}")

        self.server._received = True

    def log_message(self, *args):
        pass


def main():
    server = HTTPServer(("127.0.0.1", 5555), Handler)
    server._received = False
    print("listening on http://127.0.0.1:5555/callback")
    while not server._received:
        server.handle_request()
    sys.exit(0)


if __name__ == "__main__":
    main()
