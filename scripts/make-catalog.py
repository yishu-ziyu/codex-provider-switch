#!/usr/bin/env python3
"""Generate a minimal Codex model catalog for an external provider.

Example:
  ./make-catalog.py --slug deepseek-flash --name "DeepSeek V4.1 Flash" \
    --context-window 1000000 --efforts low,high,max > models.json
"""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, help="model id used by the provider")
    parser.add_argument("--name", default=None, help="display name in the picker")
    parser.add_argument("--description", default=None)
    parser.add_argument("--context-window", type=int, default=None)
    parser.add_argument("--max-context-window", type=int, default=None)
    parser.add_argument("--efforts", default="", help="comma separated, e.g. low,high,max")
    parser.add_argument("--default-effort", default=None)
    args = parser.parse_args()

    entry = {
        "slug": args.slug,
        "display_name": args.name or args.slug,
        "visibility": "list",
        "supported_in_api": True,
        "shell_type": "unified_exec",
    }
    if args.description:
        entry["description"] = args.description
    if args.context_window:
        entry["context_window"] = args.context_window
        entry["max_context_window"] = args.max_context_window or args.context_window
    efforts = [e.strip() for e in args.efforts.split(",") if e.strip()]
    if efforts:
        entry["supported_reasoning_levels"] = [{"effort": e} for e in efforts]
        entry["default_reasoning_level"] = args.default_effort or efforts[-1]

    json.dump({"models": [entry]}, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
