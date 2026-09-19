#!/bin/bash
# Codex 客户端模型模式切换：native（原生 OpenAI）<-> deepseek（OpenCode Go 直连）
# deepseek 模式下记忆提取/合并也走 deepseek-flash；native 模式移除该覆盖
# 用法: switch-mode.sh [native|deepseek|toggle] [--no-restart]
set -euo pipefail

CONFIG="$HOME/.codex/config.toml"
CATALOG="$HOME/.config/codex-go/models.json"
MODE="${1:-toggle}"
NO_RESTART=0
[ "${2:-}" = "--no-restart" ] && NO_RESTART=1

case "$MODE" in
  native|deepseek|toggle) ;;
  *) echo "用法: $(basename "$0") [native|deepseek|toggle] [--no-restart]"; exit 2 ;;
esac

current=native
if grep -q '^model_provider = "opencode_go"' "$CONFIG"; then current=deepseek; fi

if [ "$MODE" = "toggle" ]; then
  if [ "$current" = "deepseek" ]; then MODE=native; else MODE=deepseek; fi
fi

if [ "$MODE" = "$current" ]; then
  echo "已经是 $MODE 模式"
  exit 0
fi

/usr/bin/python3 - "$CONFIG" "$MODE" "$CATALOG" <<'PY'
import sys

path, mode, catalog = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(path, encoding="utf-8").read().split("\n")
drop_prefixes = (
    "model = ",
    "model_provider = ",
    "model_catalog_json = ",
    "extract_model = ",
    "consolidation_model = ",
    "# codex-router 已停用",
)
lines = [l for l in lines if not l.startswith(drop_prefixes)]
if mode == "deepseek":
    idx = next(
        (i for i, l in enumerate(lines) if l.startswith("model_reasoning_effort")),
        0,
    )
    lines[idx:idx] = [
        'model = "deepseek-flash"',
        'model_provider = "opencode_go"',
        f'model_catalog_json = "{catalog}"',
    ]
    memories_header = next(
        (i for i, l in enumerate(lines) if l.strip() == "[memories]"),
        None,
    )
    if memories_header is not None:
        lines[memories_header + 1:memories_header + 1] = [
            'extract_model = "deepseek-flash"',
            'consolidation_model = "deepseek-flash"',
        ]
out = "\n".join(lines)
while "\n\n\n" in out:
    out = out.replace("\n\n\n", "\n\n")
open(path, "w", encoding="utf-8").write(out)
PY

if [ "$MODE" = "deepseek" ]; then LABEL="DeepSeek 直连"; else LABEL="原生 OpenAI"; fi
echo "已切换到 $LABEL"

if [ "$NO_RESTART" -eq 1 ]; then
  exit 0
fi

/usr/bin/osascript -e "display notification \"已切换到 ${LABEL}，Codex 正在重启\" with title \"Codex 模型\"" >/dev/null 2>&1 || true
/usr/bin/osascript -e 'quit app "ChatGPT"' >/dev/null 2>&1 || true
sleep 4
for pid in $(pgrep -f "Resources/codex app-server" || true); do
  kill -TERM "$pid" 2>/dev/null || true
done
sleep 2
open -a "ChatGPT"
sleep 5
echo "Codex 已重启"
