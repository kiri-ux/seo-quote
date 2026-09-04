"""Serve templates/index.html with the Jinja tags stripped, for browser tests."""
import http.server
import os
import re
import socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(os.path.dirname(HERE), "templates", "index.html")).read()
HTML = re.sub(r"\{\{.*?\}\}", "", HTML, flags=re.S)
HTML = re.sub(r"\{%.*?%\}", "", HTML, flags=re.S)


class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
socketserver.TCPServer(("", 5199), H).serve_forever()
