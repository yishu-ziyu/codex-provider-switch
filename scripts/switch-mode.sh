#!/bin/bash
# Switch the Codex desktop app between native OpenAI models and an external
# provider, then restart the app so it reloads provider + model catalog.
#
# Usage: switch-mode.sh [native|external|toggle] [--no-restart]
#
# Environment:
#   CODEX_SWITCH_PROVIDER  provider id defined in config.toml (default: opencode_go)
#   CODEX_SWITCH_MODEL     external model slug (default: deepseek-flash)
#   CODEX_SWITCH_CATALOG   model catalog json (default: ~/.config/codex-go/models.json)
#   CODEX_SWITCH_APP       desktop app name (default: ChatGPT)
set -euo pipefail

CONFIG="$HOME/.codex/config.toml"
PROVIDER="${CODEX_SWITCH_PROVIDER:-opencode_go}"
MODEL="${CODEX_SWITCH_MODEL:-deepseek-flash}"
CATALOG="${CODEX_SWITCH_CATALOG:-$HOME/.config/codex-go/models.json}"
APP="${CODEX_SWITCH_APP:-ChatGPT}"

MODE="${1:-toggle}"
NO_RESTART=0
[ "${2:-}" = "--no-restart" ] && NO_RESTART=1

case "$MODE" in
  native|external|toggle) ;;
  *) echo "用法: $(basename "$0") [native|external|toggle] [--no-restart]"; exit 2 ;;
esac

[ -f "$CONFIG" ] || { echo "找不到 $CONFIG"; exit 1; }

current=native
if grep -q "^model_provider = \"$PROVIDER\"" "$CONFIG"; then current=external; fi

if [ "$MODE" = "toggle" ]; then
  if [ "$current" = "external" ]; then MODE=native; else MODE=external; fi
fi

if [ "$MODE" = "$current" ]; then
  echo "已经是 $MODE 模式"
  exit 0
fi

/usr/bin/python3 - "$CONFIG" "$MODE" "$MODEL" "$PROVIDER" "$CATALOG" <<'PY'
import sys

path, mode, model, provider, catalog = sys.argv[1:6]
lines = open(path, encoding="utf-8").read().split("\n")
drop_prefixes = (
    "model = ",
    "model_provider = ",
    "model_catalog_json = ",
)
lines = [l for l in lines if not l.startswith(drop_prefixes)]
if mode == "external":
    idx = next(
        (i for i, l in enumerate(lines) if l.startswith("model_reasoning_effort")),
        0,
    )
    lines[idx:idx] = [
        f'model = "{model}"',
        f'model_provider = "{provider}"',
        f'model_catalog_json = "{catalog}"',
    ]
out = "\n".join(lines)
while "\n\n\n" in out:
    out = out.replace("\n\n\n", "\n\n")
open(path, "w", encoding="utf-8").write(out)
PY

if [ "$MODE" = "external" ]; then LABEL="$MODEL"; else LABEL="native"; fi
echo "已切换到 $LABEL"

if [ "$NO_RESTART" -eq 1 ]; then
  exit 0
fi

/usr/bin/osascript -e "display notification \"已切换到 ${LABEL}，Codex 正在重启\" with title \"Codex 模型\"" >/dev/null 2>&1 || true
/usr/bin/osascript -e "quit app \"$APP\"" >/dev/null 2>&1 || true
sleep 4
for pid in $(pgrep -f "Resources/codex app-server" || true); do
  kill -TERM "$pid" 2>/dev/null || true
done
sleep 2
open -a "$APP"
sleep 5
echo "Codex 已重启"
