#!/usr/bin/env python3
"""本机 Go 网关：只允许白名单模型离开本机去请求 OpenCode Go。

放在 https://opencode.ai/zen/go/v1 前面，客户端把 base_url 指向本机即可。
不在白名单里的模型直接 403，请求根本不会发到 opencode.ai；
请求体解析不出 model 时按拒绝处理（fail closed）。
Authorization 头原样透传，网关不接触也不记录密钥。
"""
import datetime
import http.client
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM_HOST = "opencode.ai"
UPSTREAM_PREFIX = "/zen/go"
ALLOWED = {"deepseek-flash", "deepseek-v4.1-flash", "muse-spark-1.3-contributor"}
LISTEN_HOST, LISTEN_PORT = "127.0.0.1", 8791
LOG_PATH = os.path.expanduser("~/.config/codex-go/go-gateway.log")
TIMEOUT = 900

_lock = threading.Lock()


def log(line):
    with _lock:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_chunked(stream):
    body = b""
    while True:
        size_line = stream.readline().strip()
        if not size_line:
            break
        try:
            size = int(size_line.split(b";")[0], 16)
        except ValueError:
            break
        if size == 0:
            stream.readline()
            break
        body += stream.read(size)
        stream.read(2)
    return body


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "codex-go-gateway"

    def log_message(self, fmt, *args):
        pass

    def deny(self, model):
        payload = json.dumps({
            "error": {
                "type": "model_not_allowed",
                "message": "model %r blocked by local Go gateway; allowed: %s" % (model, sorted(ALLOWED)),
            }
        }).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        log("%s BLOCK path=%s model=%s" % (now(), self.path, model))

    def read_body(self):
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            return read_chunked(self.rfile)
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def proxy(self):
        body = self.read_body()

        if self.command != "GET":
            model = None
            try:
                parsed = json.loads(body.decode("utf-8"))
                if isinstance(parsed, dict):
                    model = parsed.get("model")
            except Exception:
                model = None
            if not isinstance(model, str) or not model.strip():
                self.deny("(missing or unparsable model)")
                return
            if model.strip() not in ALLOWED:
                self.deny(model)
                return
        else:
            model = "-"

        headers = {}
        for key, value in self.headers.items():
            if key.lower() in ("host", "content-length", "connection", "transfer-encoding", "accept-encoding"):
                continue
            headers[key] = value
        if body:
            headers["Content-Length"] = str(len(body))

        try:
            conn = http.client.HTTPSConnection(UPSTREAM_HOST, timeout=TIMEOUT)
            conn.request(self.command, UPSTREAM_PREFIX + self.path, body=body or None, headers=headers)
            resp = conn.getresponse()
        except Exception as exc:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            payload = json.dumps({"error": {"type": "gateway_upstream_error", "message": str(exc)}}).encode("utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            log("%s UPSTREAM_ERROR path=%s model=%s err=%s" % (now(), self.path, model, exc))
            return

        self.send_response(resp.status)
        for key, value in resp.getheaders():
            if key.lower() in ("connection", "transfer-encoding", "content-length", "content-encoding"):
                continue
            self.send_header(key, value)
        self.end_headers()
        try:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except Exception:
            pass
        finally:
            conn.close()
        log("%s ALLOW path=%s model=%s status=%s" % (now(), self.path, model, resp.status))

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = proxy


if __name__ == "__main__":
    log("%s gateway start on %s:%s allowed=%s" % (now(), LISTEN_HOST, LISTEN_PORT, sorted(ALLOWED)))
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()
