"""Serve templates/index.html with the Jinja tags stripped, for browser tests."""
import http.server
import os
import re
import socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
def _strip(name):
    t = open(os.path.join(os.path.dirname(HERE), "templates", name)).read()
    t = re.sub(r"\{\{.*?\}\}", "", t, flags=re.S)
    return re.sub(r"\{%.*?%\}", "", t, flags=re.S)


HTML = _strip("index.html")
REP = _strip("reputation.html")


class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write((REP if self.path.startswith("/reputation")
                          else HTML).encode())

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
socketserver.TCPServer(("", 5199), H).serve_forever()
