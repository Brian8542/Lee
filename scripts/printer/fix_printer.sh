#!/bin/bash
# 삼성 SL-C513W를 macOS에서 안정적으로 쓰기 위한 설정 스크립트
#
# 삼성 전용 드라이버 대신 macOS에 들어 있는 AirPrint(드라이버 없는 인쇄)로
# 프린터를 다시 등록하고, 오류가 나도 프린터가 멈추지 않도록 설정합니다.
#
# 사용법:
#   ./fix_printer.sh check             현재 상태만 확인 (아무것도 바꾸지 않음)
#   ./fix_printer.sh setup [IP]        프린터 다시 등록 (IP 생략 시 자동 검색)
#   ./fix_printer.sh watchdog-on       2분마다 자동 복구 켜기
#   ./fix_printer.sh watchdog-off      자동 복구 끄기
#   ./fix_printer.sh heal              멈춘 프린터 1회 복구 (자동 복구가 쓰는 동작)

QUEUE="Samsung_SL_C513W"
DESC="Samsung SL-C513W"
DEFAULT_IP="192.168.0.201"
NAME_PATTERN="[Cc]51|[Ss]amsung|[Ss]weetheart"
AGENT_LABEL="com.lee.printer-watchdog"
AGENT_PLIST="$HOME/Library/LaunchAgents/$AGENT_LABEL.plist"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

say() { printf '%s\n' "$*"; }

require_mac() {
  if [ "$(uname)" != "Darwin" ]; then
    say "이 스크립트는 Mac에서만 실행할 수 있습니다."
    exit 1
  fi
}

# 네트워크에서 AirPrint 프린터 주소를 찾습니다.
# .local 주소를 쓰면 공유기가 프린터 IP를 바꿔도 계속 연결됩니다.
find_airprint_uri() {
  command -v ippfind >/dev/null 2>&1 || return 1
  ippfind _ipp._tcp --name "$NAME_PATTERN" -T 5 2>/dev/null | head -n 1
}

ipp_ok() {
  ipptool -q -T 5 "$1" get-printer-attributes.test >/dev/null 2>&1
}

cmd_check() {
  say "== 등록된 프린터 =="
  lpstat -v 2>/dev/null || say "(없음)"
  say ""
  say "== 프린터 상태 =="
  lpstat -p 2>/dev/null || say "(없음)"
  say ""
  say "== 대기 중인 인쇄 작업 =="
  lpstat -o 2>/dev/null | head -n 20
  say ""
  say "== 네트워크 확인 =="
  uri="$(find_airprint_uri)"
  if [ -n "$uri" ]; then
    say "AirPrint 프린터 발견: $uri"
  else
    say "AirPrint 검색 결과 없음"
  fi
  if ping -c 2 -t 3 "$DEFAULT_IP" >/dev/null 2>&1; then
    say "$DEFAULT_IP 응답 있음"
  else
    say "$DEFAULT_IP 응답 없음 (IP가 바뀌었거나 프린터가 꺼져 있을 수 있습니다)"
  fi
}

cmd_setup() {
  ip="$1"
  uri=""
  if [ -n "$ip" ]; then
    uri="ipp://$ip/ipp/print"
  else
    say "네트워크에서 프린터를 찾는 중입니다 (최대 5초)..."
    uri="$(find_airprint_uri)"
    [ -z "$uri" ] && uri="ipp://$DEFAULT_IP/ipp/print"
  fi
  say "사용할 주소: $uri"

  if ! ipp_ok "$uri"; then
    say ""
    say "프린터가 응답하지 않습니다. 다음을 확인해 주세요."
    say "  1) 프린터 전원과 Wi-Fi 연결"
    say "  2) Mac과 프린터가 같은 Wi-Fi에 있는지"
    say "  3) 프린터의 현재 IP (정보 버튼을 길게 눌러 설정 보고서 출력)"
    say "확인한 IP로 다시 실행: ./fix_printer.sh setup 192.168.0.xxx"
    exit 1
  fi

  say ""
  say "기존에 같은 프린터로 등록된 항목을 정리합니다."
  host="$(printf '%s' "$uri" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"
  lpstat -v 2>/dev/null | while IFS= read -r line; do
    name="$(printf '%s' "$line" | sed -E 's/^device for ([^:]+):.*/\1/')"
    dev="${line#*: }"
    case "$dev" in
      *"$host"*|*"$DEFAULT_IP"*|*[Ss]amsung*|*C51*)
        say "  제거: $name ($dev)"
        cancel -a "$name" 2>/dev/null
        lpadmin -x "$name"
        ;;
    esac
  done

  say ""
  say "AirPrint 방식으로 다시 등록합니다. (관리자 암호를 물어보면 입력해 주세요)"
  if ! sudo lpadmin -p "$QUEUE" -D "$DESC" -E -v "$uri" -m everywhere \
        -o printer-error-policy=retry-job \
        -o printer-is-shared=false; then
    say ""
    say "자동 등록에 실패했습니다. 시스템 설정 > 프린터 및 스캐너 > 프린터 추가에서"
    say "프린터를 선택하고 '사용'을 'AirPrint'로 고른 뒤 추가해 주세요."
    exit 1
  fi
  sudo cupsenable "$QUEUE"
  sudo cupsaccept "$QUEUE"
  lpoptions -d "$QUEUE" >/dev/null

  say ""
  say "완료되었습니다. 기본 프린터: $DESC"
  say "시험 인쇄를 하려면: ./fix_printer.sh test"
}

cmd_test() {
  printf '프린터 시험 인쇄\n%s\n' "$(date)" | lp -d "$QUEUE" -t "Test" && say "시험 인쇄를 보냈습니다."
}

# 오류로 멈춘(disabled) 프린터를 다시 켭니다. 인쇄 작업은 지우지 않습니다.
cmd_heal() {
  LANG=C LC_ALL=C lpstat -p 2>/dev/null | awk '/^printer .* disabled/ {print $2}' | while read -r p; do
    cupsenable "$p" 2>/dev/null && logger "printer-watchdog: re-enabled $p"
  done
}

cmd_watchdog_on() {
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$AGENT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$AGENT_LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$SCRIPT_PATH</string><string>heal</string></array>
  <key>StartInterval</key><integer>120</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)" "$AGENT_PLIST" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "$AGENT_PLIST" && say "자동 복구를 켰습니다. (2분마다 확인)"
}

cmd_watchdog_off() {
  launchctl bootout "gui/$(id -u)" "$AGENT_PLIST" 2>/dev/null
  rm -f "$AGENT_PLIST"
  say "자동 복구를 껐습니다."
}

require_mac
case "$1" in
  check) cmd_check ;;
  setup) cmd_setup "$2" ;;
  test) cmd_test ;;
  heal) cmd_heal ;;
  watchdog-on) cmd_watchdog_on ;;
  watchdog-off) cmd_watchdog_off ;;
  *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
