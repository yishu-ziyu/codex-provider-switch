#!/bin/bash
# Build the double-clickable switcher app in ~/Applications (icon included).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/Codex 模型切换.app"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>Codex 模型切换</string>
	<key>CFBundleDisplayName</key>
	<string>Codex 模型切换</string>
	<key>CFBundleIdentifier</key>
	<string>local.codex.model-switch</string>
	<key>CFBundleExecutable</key>
	<string>CodexModelSwitch</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>CFBundleIconName</key>
	<string>AppIcon</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>LSMinimumSystemVersion</key>
	<string>13.0</string>
	<key>LSUIElement</key>
	<true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/CodexModelSwitch" <<EOF
#!/bin/bash
exec "$ROOT/scripts/switch-mode.sh" toggle
EOF
chmod +x "$APP/Contents/MacOS/CodexModelSwitch"

if command -v python3 >/dev/null 2>&1; then
  (cd "$ROOT/scripts" && python3 render_icon.py >/dev/null 2>&1) || true
  if [ -f "$ROOT/scripts/AppIcon.icns" ]; then
    cp "$ROOT/scripts/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
  fi
fi

touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true
echo "已生成: $APP"
