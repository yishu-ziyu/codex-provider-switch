#!/bin/bash
# 开关本机 Go 网关：on 让 Go 流量走 127.0.0.1 白名单网关，off 还原直连并停掉网关。
set -euo pipefail

DIR="$HOME/.config/codex-go"
PLIST="$HOME/Library/LaunchAgents/com.mahaoxuan.codex-go-gateway.plist"
OVERRIDES="$DIR/config-overrides.json"
OPENCODE="$HOME/.config/opencode/opencode.json"
LOCAL="http://127.0.0.1:8791/v1"
REAL="https://opencode.ai/zen/go/v1"
UID_NUM="$(id -u)"

MODE="${1:-}"
if [ -z "$MODE" ]; then
  case "$(basename "$0")" in
    nogw) MODE=off ;;
    gw) MODE=on ;;
  esac
fi
case "${MODE:-}" in
  on|off) ;;
  *) echo "用法: gw 开启 / nogw 取消"; exit 2 ;;
esac

if [ "$MODE" = on ]; then TARGET="$LOCAL"; else TARGET="$REAL"; fi

/usr/bin/python3 - "$OVERRIDES" "$TARGET" "$LOCAL" <<'PY'
import json, sys
path, target, local = sys.argv[1], sys.argv[2], sys.argv[3]
items = json.load(open(path, encoding="utf-8"))
found = False
out = []
for item in items:
    if isinstance(item, str) and item.startswith("model_providers.opencode_go.base_url="):
        item = 'model_providers.opencode_go.base_url="%s"' % target
        found = True
    out.append(item)
if not found:
    out.append('model_providers.opencode_go.base_url="%s"' % target)
json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
open(path, "a", encoding="utf-8").write("\n")
print("codex-go base_url ->", target)
PY

if [ -f "$OPENCODE" ]; then
  /usr/bin/python3 - "$OPENCODE" "$TARGET" "$REAL" <<'PY'
import json, sys
path, target, real = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(path, encoding="utf-8"))
provider = d.setdefault("provider", {}).setdefault("opencode-go", {})
options = provider.setdefault("options", {})
if target == real:
    options.pop("baseURL", None)
    options.pop("baseUrl", None)
    if not options:
        provider.pop("options", None)
else:
    options["baseURL"] = target
json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
open(path, "a", encoding="utf-8").write("\n")
print("opencode-go baseURL ->", "直连" if target == real else target)
PY
fi

if [ "$MODE" = on ]; then
  LABEL="gui/$UID_NUM/com.mahaoxuan.codex-go-gateway"
  launchctl enable "$LABEL" >/dev/null 2>&1 || true
  if launchctl print "$LABEL" >/dev/null 2>&1; then
    launchctl kickstart -k "$LABEL" >/dev/null 2>&1 || true
  else
    launchctl bootstrap "gui/$UID_NUM" "$PLIST" >/dev/null 2>&1 || launchctl load -w "$PLIST" >/dev/null 2>&1 || true
  fi
  for _ in $(seq 1 60); do
    if nc -z 127.0.0.1 8791 2>/dev/null; then break; fi
    sleep 0.5
  done
  if nc -z 127.0.0.1 8791 2>/dev/null; then
    echo "Go 网关已开启：只有 deepseek-flash / deepseek-v4.1-flash / muse-spark-1.3-contributor 能通过，取消用 nogw"
  else
    echo "Go 网关启动失败，查看 $DIR/go-gateway.launchd.err"; exit 1
  fi
else
  LABEL="gui/$UID_NUM/com.mahaoxuan.codex-go-gateway"
  launchctl bootout "$LABEL" >/dev/null 2>&1 || launchctl unload -w "$PLIST" >/dev/null 2>&1 || true
  launchctl disable "$LABEL" >/dev/null 2>&1 || true
  pkill -f "codex-go/go-gateway.py" >/dev/null 2>&1 || true
  echo "Go 网关已取消：Go 流量恢复直连，可随时用 gw 重新开启"
fi
