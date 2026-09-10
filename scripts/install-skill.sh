#!/bin/bash
# Install this repo as a Codex skill (SKILL.md + scripts + references).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${CODEX_HOME:-$HOME/.codex}/skills/codex-provider-setup"

mkdir -p "$DEST"
for item in SKILL.md scripts references agents; do
  [ -e "$ROOT/$item" ] || continue
  cp -R "$ROOT/$item" "$DEST/"
done
chmod +x "$DEST/scripts/"* 2>/dev/null || true

echo "已安装到 $DEST"
echo "新开一个 Codex 会话，用 \$codex-provider-setup 触发，或直接描述需求让它自动匹配。"
