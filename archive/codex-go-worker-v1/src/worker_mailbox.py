#!/usr/bin/env python3
"""Private per-run message mailbox for the live worker panel.

Messages live in ``<run_dir>/messages/<id>.json`` and any referenced image
snapshot is frozen next to them as ``<run_dir>/messages/<id>.<ext>``. Every
mutation takes a per-message ``flock`` and commits through a temporary file
plus ``os.replace``, so a browser retry and a concurrent runtime receipt can
never tear or duplicate a message.

The runtime owns status transitions through :func:`update_message`. This module
never retries delivery: re-submitting the same id with the same body returns the
stored receipt untouched, including a ``failed`` or ``uncertain`` state.
"""
from __future__ import annotations

import base64
import binascii
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

MESSAGES_DIR = "messages"
STATES = ("queued", "sending", "delivered", "replied", "failed", "uncertain")
IMMUTABLE = ("id", "text", "image", "created_at")
MAX_TEXT = 12000
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class MailboxError(Exception):
    """Base class for mailbox failures. Messages never embed local paths."""


class InvalidMessage(MailboxError):
    """The caller supplied a malformed message field."""


class Conflict(MailboxError):
    """The id already exists with different, immutable content."""


class NotFound(MailboxError):
    """No message is stored for the requested id."""


def messages_dir(directory):
    """Return the private message directory for a run (it may not exist yet)."""
    return Path(directory) / MESSAGES_DIR


def normalize_id(value):
    """Return the canonical lowercase UUID for a caller-supplied id."""
    if not isinstance(value, str):
        raise InvalidMessage("message id must be a string")
    try:
        return str(uuid.UUID(value.strip()))
    except (ValueError, AttributeError):
        raise InvalidMessage("message id must be a UUID")


def check_text(value):
    """Return text after enforcing the nonempty / size / type contract."""
    if not isinstance(value, str):
        raise InvalidMessage("message text must be a string")
    if not value.strip():
        raise InvalidMessage("message text must not be empty")
    if len(value) > MAX_TEXT:
        raise InvalidMessage("message text is too long")
    return value


class _lock:
    """Exclusive advisory lock on a per-message sidecar file."""

    def __init__(self, path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.handle = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if self.handle is not None:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            os.close(self.handle)
            self.handle = None
        return False


def _ensure_dir(directory):
    base = messages_dir(directory)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        pass
    return base


def _atomic_write(path, payload):
    """Write bytes to ``path`` via a same-directory temp file plus replace."""
    path = Path(path)
    handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    return path


def _message_path(base, message_id):
    return base / (message_id + ".json")


def _read(base, message_id):
    try:
        raw = _message_path(base, message_id).read_bytes()
    except FileNotFoundError:
        return None
    try:
        message = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise MailboxError("stored message is unreadable")
    if not isinstance(message, dict) or message.get("id") != message_id:
        raise MailboxError("stored message is unreadable")
    return message


def _write(base, message):
    payload = json.dumps(message, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    return _atomic_write(_message_path(base, message["id"]), payload)


def _image_snapshot(image):
    """Validate a backend-resolved image and return ``(digest, mime, raw)``."""
    if image is None:
        return None
    if not isinstance(image, dict):
        raise InvalidMessage("image must be null or a known run image")
    digest = image.get("digest")
    mime = image.get("mimeType")
    data = image.get("data")
    if not isinstance(digest, str) or not DIGEST_RE.match(digest):
        raise InvalidMessage("image digest is invalid")
    if mime not in MIME_EXT:
        raise InvalidMessage("image type is not supported")
    if not isinstance(data, str) or not data:
        raise InvalidMessage("image payload is invalid")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidMessage("image payload is invalid")
    if not raw:
        raise InvalidMessage("image payload is invalid")
    return digest, mime, raw


def _reuse(existing, text, snapshot):
    current = existing.get("image")
    current_digest = current.get("digest") if isinstance(current, dict) else None
    requested = snapshot[0] if snapshot is not None else None
    if existing.get("text") == text and current_digest == requested:
        return existing
    raise Conflict("message id already stored with different content")


def enqueue(directory, id, text, image=None):
    """Store a queued message idempotently and return its stored receipt.

    ``image`` is ``None`` or a backend-resolved ``{digest, mimeType, data}``
    dict. Same id + same body returns the existing message unchanged (its status
    is never reset); same id + different body raises :class:`Conflict`.
    """
    message_id = normalize_id(id)
    body = check_text(text)
    snapshot = _image_snapshot(image)
    base = _ensure_dir(directory)
    with _lock(base / (message_id + ".lock")):
        existing = _read(base, message_id)
        if existing is not None:
            return _reuse(existing, body, snapshot)
        now = time.time()
        message = {"format": "worker-message-v1", "id": message_id, "text": body,
                   "image": None, "created_at": now, "updated_at": now,
                   "queued_at": now, "status": "queued"}
        if snapshot is not None:
            digest, mime, raw = snapshot
            target = base / (message_id + MIME_EXT[mime])
            _atomic_write(target, raw)
            message["image"] = {"digest": digest, "mimeType": mime,
                                "path": str(target), "bytes": len(raw)}
        _write(base, message)
        return message


def get_message(directory, id):
    """Return the stored message for ``id`` or ``None``; id may be any case."""
    try:
        message_id = normalize_id(id)
    except InvalidMessage:
        return None
    base = messages_dir(directory)
    if not base.is_dir():
        return None
    return _read(base, message_id)


def list_messages(directory):
    """Return every stored message ordered by creation time."""
    base = messages_dir(directory)
    if not base.is_dir():
        return []
    stored = []
    for path in sorted(base.glob("*.json")):
        try:
            message = _read(base, path.stem)
        except (MailboxError, OSError):
            continue
        if message is not None:
            stored.append(message)
    stored.sort(key=lambda item: (item.get("created_at") or 0, item.get("id") or ""))
    return stored


def pending_messages(directory):
    """Return only the still-queued messages for the runtime to consume."""
    return [message for message in list_messages(directory) if message.get("status") == "queued"]


def update_message(directory, id, **fields):
    """Atomically apply runtime receipt fields to a stored message.

    Immutable fields (``id``, ``text``, ``image``, ``created_at``) are ignored if
    supplied, so a receipt write can never rewrite what the user submitted.
    """
    message_id = normalize_id(id)
    if "status" in fields and fields["status"] not in STATES:
        raise InvalidMessage("unknown message status")
    for key in ("turn_id", "reply", "error"):
        if key in fields and fields[key] is not None and not isinstance(fields[key], str):
            raise InvalidMessage("message %s must be a string" % key)
    base = _ensure_dir(directory)
    with _lock(base / (message_id + ".lock")):
        message = _read(base, message_id)
        if message is None:
            raise NotFound("unknown message id")
        for key, value in fields.items():
            if key in IMMUTABLE or key == "format":
                continue
            message[key] = value
        message["updated_at"] = time.time()
        _write(base, message)
        return message
