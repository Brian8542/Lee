#!/bin/bash
# Wispr Flow 상시 구동 설치 스크립트 (macOS)
# - 로그인 즉시 Wispr Flow 실행
# - 종료/크래시 시 5초 안에 자동 재실행 (launchd KeepAlive 워치독)
# - 맥 잠자기 방지 (caffeinate + pmset)
# - 정전 후 자동 재부팅
set -euo pipefail

LABEL="com.wisprflow.keepalive"
APP_NAME="Wispr Flow"
SUPPORT_DIR="$HOME/Library/Application Support/WisprFlowKeepAlive"
WATCHDOG="$SUPPORT_DIR/watchdog.sh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/WisprFlowKeepAlive.log"

[[ "$(uname)" == "Darwin" ]] || { echo "macOS에서만 실행하세요."; exit 1; }

APP_PATH="$(mdfind "kMDItemFSName == '$APP_NAME.app'" 2>/dev/null | head -n1 || true)"
[[ -z "$APP_PATH" && -d "/Applications/$APP_NAME.app" ]] && APP_PATH="/Applications/$APP_NAME.app"
[[ -n "$APP_PATH" ]] || { echo "'$APP_NAME.app'을 찾을 수 없습니다. 먼저 설치하세요."; exit 1; }
echo "앱 위치: $APP_PATH"

mkdir -p "$SUPPORT_DIR" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

# 1) 워치독: 5초마다 확인, 꺼져 있으면 재실행. 실행 중엔 caffeinate로 잠자기 방지.
cat > "$WATCHDOG" <<WD
#!/bin/bash
APP_PATH="$APP_PATH"
MAIN_BIN="\$APP_PATH/Contents/MacOS/"
caffeinate -dimsu -w \$\$ &   # 이 워치독이 사는 동안 디스플레이/시스템 잠자기 방지
while true; do
  if ! pgrep -f "\$MAIN_BIN" >/dev/null 2>&1; then
    echo "\$(date '+%F %T') Wispr Flow 미실행 감지 → 재실행"
    open -g -a "\$APP_PATH"
  fi
  sleep 5
done
WD
chmod +x "$WATCHDOG"

# 2) LaunchAgent: 로그인 시 시작, 워치독 자체가 죽어도 launchd가 즉시 재시작
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$WATCHDOG</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PL

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"

# 3) 로그인 항목에도 등록 (이중 안전장치)
osascript -e "tell application \"System Events\" to if not (exists login item \"$APP_NAME\") then make login item at end with properties {path:\"$APP_PATH\", hidden:true}" >/dev/null 2>&1 || true

# 4) 시스템 전원 설정 (관리자 암호 필요)
echo "전원 설정을 변경합니다. 맥 로그인 암호를 입력하세요."
sudo pmset -a sleep 0            # 시스템 잠자기 안 함
sudo pmset -a disksleep 0        # 디스크 잠자기 안 함
sudo pmset -a disablesleep 1     # 덮개를 닫아도 잠자기 안 함
sudo pmset -a autorestart 1      # 정전 후 전원 복구 시 자동 부팅
sudo pmset -a womp 1             # 네트워크 접근 시 깨우기
sudo pmset -a powernap 0         # Power Nap으로 인한 반수면 방지

echo
echo "✅ 설치 완료. Wispr Flow는 이제 로그인 시 자동 실행되고, 꺼지면 5초 안에 다시 켜집니다."
echo "   상태 확인: launchctl print gui/$(id -u)/$LABEL | grep state"
echo "   로그:      $LOG"
