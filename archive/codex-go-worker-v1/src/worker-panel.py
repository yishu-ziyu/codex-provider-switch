#!/usr/bin/env python3
"""On-demand, loopback-only progress panel for registered DeepSeek workers."""
import argparse
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "worker-runs"
ACTIVE = {"starting", "running"}
ID = re.compile(r"^[0-9a-f-]{36}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
BODY_LIMIT = 64 * 1024
STALE_SECONDS = 15
# A run that already stopped for these reasons must never be silently restarted.
REFUSED = {"cancelled", "deadline_reached", "deadline", "expired"}
# Credentials must never surface through the read-only activity feed.
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET = re.compile(r"(?i)\b(api[_-]?key|access[_-]?key|secret|token|password|passwd|authorization)\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)")
_REDACT_VALUES = set()


def _load_mailbox():
    spec = importlib.util.spec_from_file_location(
        "worker_mailbox", Path(__file__).resolve().with_name("worker_mailbox.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    mailbox = _load_mailbox()
except (OSError, ImportError):
    mailbox = None


def redact(value):
    text = str(value)
    text = _BEARER.sub("Bearer [redacted]", text)
    text = _SECRET.sub(lambda match: match.group(1) + match.group(2) + "[redacted]", text)
    for known in _REDACT_VALUES:
        if known:
            text = text.replace(known, "[redacted]")
    return text


def _reject_constant(value):
    raise ValueError("non-standard JSON constant: " + str(value))


def register(directory, state):
    if not ID.fullmatch(state.get("run_id", "")):
        return
    REGISTRY.mkdir(mode=0o700, exist_ok=True)
    target = REGISTRY / (state["run_id"] + ".json")
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps({"directory": str(directory.resolve())}))
    temp.chmod(0o600)
    temp.replace(target)


def run_directory(run_id):
    if not ID.fullmatch(run_id):
        raise FileNotFoundError()
    directory = Path(json.loads((REGISTRY / (run_id + ".json")).read_text())["directory"])
    state = json.loads((directory / "status.json").read_text())
    if state.get("format") != "deepseek-worker-v1" or state.get("run_id") != run_id:
        raise FileNotFoundError()
    return directory, state


def read_limited(path, limit=30000):
    try:
        with path.open(errors="replace") as stream:
            text = stream.read(limit + 1)
        return text[:limit] + ("\n[内容较长，面板已截断]" if len(text) > limit else "")
    except FileNotFoundError:
        return ""


def goal_excerpt(directory, state):
    stated = state.get("goal")
    if isinstance(stated, str) and stated.strip():
        return redact(" ".join(stated.split()))[:240]
    try:
        raw = (directory / "task.md").read_text(errors="replace")[:4000]
    except OSError:
        return None
    for line in raw.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return redact(" ".join(line.split()))[:240]
    return None


def message_blocker(directory, state):
    """Return a short reason when this run may not accept live messages."""
    if not state.get("messaging_enabled") and state.get("transport") == "app-server":
        return "Worker is connecting; please wait"
    if not state.get("messaging_enabled"):
        return "Legacy run: live messages are unavailable"
    status = state.get("status")
    if status in REFUSED:
        return "Run can no longer receive messages"
    if status in ACTIVE and time.time() - state.get("updated_at", 0) > STALE_SECONDS:
        return "Supervisor heartbeat is stale; inspect the run before sending"
    return None


def summary(directory, state):
    keys = ["cwd", "role", "status", "quiet_seconds", "needs_attention", "actual_model",
            "actual_provider", "computer_use_enabled", "updated_at", "observed_failed_turn"]
    result = {k: state.get(k) for k in keys}
    result["id"] = state["run_id"]
    result["title"] = state.get("title") or (("复核任务" if state.get("role") == "review" else "执行任务") + " · " + Path(state.get("cwd") or str(directory)).name)
    result["elapsed_seconds"] = round(max(0, (state.get("finished_at") or time.time()) - state.get("started_at", time.time())), 1)
    result["supervisor_stale"] = state["status"] in ACTIVE and time.time() - state.get("updated_at", 0) > 15
    result["cancel_requested"] = (directory / "cancel.request").exists()
    result["transport"] = state.get("transport")
    result["elapsed_seconds"] = state.get("elapsed_seconds", result["elapsed_seconds"])
    result["messaging_enabled"] = bool(state.get("messaging_enabled"))
    result["task_group"] = state.get("task_group")
    result["parent_run_id"] = state.get("parent_run_id")
    result["goal"] = goal_excerpt(directory, state)
    blocker = message_blocker(directory, state)
    result["can_message"] = blocker is None
    result["message_block_reason"] = blocker
    # Verify the model from this worker's own rollout while it is still running.
    if not result["actual_model"] and state.get("thread_id"):
        for receipt in (directory / "home/sessions").glob("**/*" + state["thread_id"] + "*.jsonl"):
            for line in read_limited(receipt, 2_000_000).splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                payload = record.get("payload", {})
                if record.get("type") == "session_meta":
                    result["actual_provider"] = payload.get("model_provider")
                if record.get("type") == "turn_context":
                    result["actual_model"] = payload.get("model")
                    break
            break
    result["title"] = redact(result["title"])
    return result


def recent_events(directory):
    events, images = {}, {}
    path = directory / "events.jsonl"
    if not path.exists():
        return list(events.values()), images
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 4_000_000))
        lines = stream.read().decode("utf-8", errors="replace").splitlines()
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if event.get("type") not in {"item.started", "item.completed"}:
            continue
        args = item.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        title = None
        if kind == "command_execution":
            title = item.get("command", "终端操作")
        elif kind == "mcp_tool_call":
            title = args.get("title") or str(item.get("server")) + " · " + str(item.get("tool"))
        elif kind == "file_change":
            title = "修改文件：" + ", ".join(Path(x.get("path", "")).name for x in (item.get("changes") or []) if isinstance(x, dict) and isinstance(x.get("path"), str))
        elif kind == "agent_message":
            title = item.get("text", "")
        if title:
            events[item.get("id") or str(len(events))] = {"kind": kind, "title": redact(str(title))[:240], "status": item.get("status") or event["type"].split(".")[-1]}
        result = item.get("result") or {}
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            for content in result["content"]:
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "image" and content.get("mimeType") in {"image/png", "image/jpeg", "image/webp"}:
                    data = content.get("data", "")
                    if isinstance(data, str) and len(data) <= 3_000_000:
                        digest = hashlib.sha256(data.encode()).hexdigest()
                        images[digest] = (content["mimeType"], data)
    return list(events.values())[-40:], dict(list(images.items())[-4:])


def public_message(run_id, message):
    """Serialize a stored message for the browser without local paths."""
    public = {}
    for key in ("id", "text", "status", "created_at", "queued_at", "updated_at", "turn_id", "reply"):
        if key in message:
            public[key] = message[key]
    if message.get("error") is not None:
        public["error"] = redact(message["error"])[:500]
    image = message.get("image")
    if isinstance(image, dict) and image.get("digest"):
        public["image"] = {"digest": image.get("digest"), "mimeType": image.get("mimeType"),
                           "url": "/api/runs/" + run_id + "/messages/" + str(message.get("id")) + "/image"}
    else:
        public["image"] = None
    return public


def launcher_path():
    sibling = Path(__file__).resolve().with_name("deepseek-worker.py")
    if sibling.is_file():
        return sibling
    return Path.home() / ".local/bin/deepseek-worker"


def wake(directory):
    """Fire-and-forget the launcher's ``continue`` for this run directory."""
    try:
        subprocess.Popen([sys.executable, str(launcher_path()), "continue", str(directory)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body, kind="application/json"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        for key, value in {"Content-Type": kind, "Content-Length": str(len(body)), "Cache-Control": "no-store",
                           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                           "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get("Host") == self.server.authority

    def authenticated(self):
        return self.valid_host() and hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.token)

    def read_body(self):
        """Return ``(payload, status)``; only a small strict-JSON object passes."""
        header = self.headers.get("Content-Length")
        try:
            length = int(header) if header is not None else -1
        except (TypeError, ValueError):
            length = -1
        if length < 0:
            return None, 400
        if length > BODY_LIMIT:
            return None, 413
        if length == 0:
            return None, 400
        raw = self.rfile.read(length)
        if len(raw) != length:
            return None, 400
        try:
            payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
        except (UnicodeDecodeError, ValueError):
            return None, 400
        if not isinstance(payload, dict):
            return None, 400
        return payload, 200

    def message_image(self, directory, message_id):
        if mailbox is None:
            return self.send(404, {"error": "Image unavailable"})
        try:
            message = mailbox.get_message(directory, message_id)
        except (OSError, mailbox.MailboxError):
            message = None
        image = message.get("image") if isinstance(message, dict) else None
        if not isinstance(image, dict) or not image.get("path"):
            return self.send(404, {"error": "Image unavailable"})
        base = mailbox.messages_dir(directory).resolve()
        try:
            resolved = Path(image["path"]).resolve()
        except OSError:
            return self.send(404, {"error": "Image unavailable"})
        if resolved.parent != base:
            return self.send(404, {"error": "Image unavailable"})
        try:
            data = resolved.read_bytes()
        except OSError:
            return self.send(404, {"error": "Image unavailable"})
        return self.send(200, data, image.get("mimeType") or "application/octet-stream")

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {"error": "Invalid host"})
        if self.path == "/" or self.path.startswith("/?"):
            try:
                return self.send(200, (ROOT / "worker-panel.html").read_bytes(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self.send(503, {"error": "Panel page not installed yet"})
        if not self.authenticated():
            return self.send(401, {"error": "Panel token required"})
        self.server.last_request = time.monotonic()
        if self.path == "/api/ping":
            return self.send(200, {"ok": True})
        if self.path == "/api/runs":
            rows = []
            for file in REGISTRY.glob("*.json"):
                try:
                    rows.append(summary(*run_directory(file.stem)))
                except (OSError, ValueError, KeyError):
                    continue
            rows.sort(key=lambda x: (x["status"] in ACTIVE, x.get("updated_at") or 0), reverse=True)
            return self.send(200, {"runs": rows[:100]})
        match = re.fullmatch(r"/api/runs/([0-9a-f-]{36})(?:/images/([0-9a-f]{64})|/messages/([0-9a-f-]{36})/image)?", self.path)
        if not match:
            return self.send(404, {"error": "Not found"})
        run_id = match[1]
        try:
            directory, state = run_directory(run_id)
            if match[2]:
                events, images = recent_events(directory)
                mime, data = images[match[2]]
                return self.send(200, base64.b64decode(data, validate=True), mime)
            if match[3]:
                return self.message_image(directory, match[3])
            events, images = recent_events(directory)
            messages = []
            if mailbox is not None:
                try:
                    messages = [public_message(run_id, item) for item in mailbox.list_messages(directory)]
                except (OSError, mailbox.MailboxError):
                    messages = []
            return self.send(200, {"run": summary(directory, state), "events": events,
                                   "result": redact(read_limited(directory / "result.txt")),
                                   "messages": messages,
                                   "images": ["/api/runs/" + run_id + "/images/" + key for key in images]})
        except (OSError, ValueError, KeyError):
            return self.send(404, {"error": "Run or image unavailable"})

    def post_message(self, run_id):
        payload, status = self.read_body()
        if payload is None:
            return self.send(status, {"error": "Message must be a small JSON object"})
        if mailbox is None:
            return self.send(503, {"error": "Message mailbox is not installed"})
        try:
            message_id = mailbox.normalize_id(payload.get("id"))
            text = mailbox.check_text(payload.get("text"))
        except mailbox.InvalidMessage:
            return self.send(400, {"error": "Message id or text is invalid"})
        image = payload.get("image")
        if image is not None and not (isinstance(image, str) and DIGEST.fullmatch(image)):
            return self.send(400, {"error": "Image reference is invalid"})
        try:
            directory, state = run_directory(run_id)
        except (OSError, ValueError, KeyError):
            return self.send(404, {"error": "Run unavailable"})
        # A retry must resolve its frozen receipt even after the image event window changed.
        existing = mailbox.get_message(directory, message_id)
        if existing is not None:
            old_digest = (existing.get("image") or {}).get("digest")
            if existing.get("text") != text or old_digest != image:
                return self.send(409, {"error": "Message id already accepted with different content"})
            if existing.get("status") == "queued" and not message_blocker(directory, state):
                wake(directory)
            return self.send(202, {"message": public_message(run_id, existing)})
        blocker = message_blocker(directory, state)
        if blocker:
            return self.send(409, {"error": blocker})
        snapshot = None
        if image is not None:
            try:
                _, images = recent_events(directory)
            except OSError:
                images = {}
            found = images.get(image)
            if not found:
                return self.send(400, {"error": "Image is not part of this run"})
            snapshot = {"digest": image, "mimeType": found[0], "data": found[1]}
        try:
            message = mailbox.enqueue(directory, message_id, text, snapshot)
        except mailbox.Conflict:
            return self.send(409, {"error": "Message id already accepted with different content"})
        except mailbox.InvalidMessage:
            return self.send(400, {"error": "Message is invalid"})
        except (OSError, mailbox.MailboxError):
            return self.send(503, {"error": "Message could not be stored"})
        wake(directory)
        return self.send(202, {"message": public_message(run_id, message)})

    def do_POST(self):
        if not self.authenticated():
            return self.send(401, {"error": "Panel token required"})
        if self.headers.get("Origin") not in {None, "http://" + self.server.authority}:
            return self.send(403, {"error": "Cross-origin action rejected"})
        message_match = re.fullmatch(r"/api/runs/([0-9a-f-]{36})/messages", self.path)
        if message_match:
            return self.post_message(message_match[1])
        cancel_match = re.fullmatch(r"/api/runs/([0-9a-f-]{36})/cancel", self.path)
        if not cancel_match:
            return self.send(404, {"error": "Not found"})
        try:
            directory, state = run_directory(cancel_match[1])
            if state["status"] not in ACTIVE:
                return self.send(409, {"error": "Worker has already finished"})
            (directory / "cancel.request").write_text("User requested cancellation from Worker panel\n")
            return self.send(200, {"ok": True})
        except (OSError, ValueError, KeyError):
            return self.send(404, {"error": "Run unavailable"})


def start_panel():
    descriptor = ROOT / "panel.json"
    try:
        saved = json.loads(descriptor.read_text())
        request = urllib.request.Request(saved["base_url"] + "/api/ping", headers={"Authorization": "Bearer " + saved["token"]})
        with urllib.request.urlopen(request, timeout=1) as response:
            if json.load(response).get("ok"):
                return saved["base_url"] + "/#" + saved["token"]
    except (OSError, ValueError, KeyError):
        pass
    nonce = secrets.token_hex(16)
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", nonce],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(50):
        try:
            saved = json.loads(descriptor.read_text())
            if saved.get("instance") == nonce:
                return saved["base_url"] + "/#" + saved["token"]
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError("Worker panel did not start")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve")
    parser.add_argument("--task-group")
    parser.add_argument("--add", action="append", default=[])
    args = parser.parse_args()
    for path in args.add:
        directory = Path(path).resolve()
        state = json.loads((directory / "status.json").read_text())
        if state.get("format") != "deepseek-worker-v1":
            raise ValueError("Not a worker run")
        register(directory, state)
    if not args.serve:
        url = start_panel()
        if args.task_group:
            base, token = url.split("#", 1)
            url = base + "?task_group=" + urllib.parse.quote(args.task_group, safe="") + "#" + token
        print(url)
        return
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.authority = "127.0.0.1:" + str(server.server_port)
    server.token = secrets.token_urlsafe(32)
    _REDACT_VALUES.add(server.token)
    server.last_request = time.monotonic()
    server.timeout = 1
    descriptor = {"instance": args.serve, "base_url": "http://" + server.authority, "token": server.token}
    temp = ROOT / ("panel-" + args.serve + ".tmp")
    temp.write_text(json.dumps(descriptor)); temp.replace(ROOT / "panel.json")
    while time.monotonic() - server.last_request < 1800:
        server.handle_request()
    server.server_close()


if __name__ == "__main__":
    main()
