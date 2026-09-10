#!/usr/bin/env python3
"""Print the provider API key to stdout for Codex's `auth.command`.

Codex captures stdout, trims whitespace, and uses the value as a bearer token.
The key never enters the config file or any log.

Lookup order:
  1. $OPENCODE_GO_API_KEY
  2. the file at $CODEX_GO_KEY_FILE (default: ~/.config/codex-go/key, mode 600)
"""
import os
import sys
from pathlib import Path


def main():
    key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
    if not key:
        path = Path(
            os.environ.get(
                "CODEX_GO_KEY_FILE",
                Path.home() / ".config" / "codex-go" / "key",
            )
        )
        try:
            key = path.read_text(encoding="utf-8").strip()
        except OSError:
            sys.exit(f"Missing API key: set OPENCODE_GO_API_KEY or write {path}")
    if not key:
        sys.exit("Empty API key")
    sys.stdout.write(key)


if __name__ == "__main__":
    main()
