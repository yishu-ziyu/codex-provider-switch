"""Codex auth command: emit the existing Pi credential only to Codex's pipe."""
import json
import sys
from pathlib import Path

try:
    entry = json.loads((Path.home() / ".pi/agent/auth.json").read_text())["opencode-go"]
    key = entry["key"]
    if entry.get("type") != "api_key" or not isinstance(key, str) or not key.strip():
        raise ValueError()
except (OSError, KeyError, ValueError, TypeError):
    sys.exit("Missing or invalid OpenCode Go API key in Pi auth.json")
sys.stdout.write(key.strip())
