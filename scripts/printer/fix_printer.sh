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

# macOS는 lpstat 결과를 시스템 언어로 번역하므로, 번역되지 않는 값만 사용합니다.
#   lpstat -e        : 프린터 이름 목록
#   lpoptions -p 이름 : device-uri=..., printer-state=... 같은 영문 키=값
queue_attr() {
  lpoptions -p "$1" 2>/dev/null | tr ' ' '\n' | sed -n "s/^$2=//p" | head -n 1
}

# 등록된 프린터를 "이름 주소" 형식으로 한 줄씩 출력합니다.
list_queues() {
  lpstat -e 2>/dev/null | while read -r name; do
    printf '%s %s\n' "$name" "$(queue_attr "$name" device-uri)"
  done
}

# 이미 등록된 이 프린터(삼성 C51x)의 이름을 찾습니다.
find_queue() {
  list_queues | while read -r name dev; do
    case "$dev" in
      *SEC*|*C51*|*[Ss]amsung*) printf '%s\n' "$name"; break ;;
    esac
  done
}

queue_driver() {
  grep -h '^\*NickName' "/etc/cups/ppd/$1.ppd" 2>/dev/null | cut -d'"' -f2
}

cmd_setup() {
  q="$(find_queue)"

  # 예전 IP(192.168.0.201)로 등록된 항목은 IP가 바뀌어 더 이상 쓸 수 없으므로 지웁니다.
  list_queues | while read -r name dev; do
      case "$dev" in
        *"$DEFAULT_IP"*)
          say "예전 IP 항목 제거: $name"
          cancel -a "$name" 2>/dev/null
          sudo lpadmin -x "$name"
          ;;
      esac
    done

  if [ -z "$q" ]; then
    say "등록된 프린터가 없어 새로 등록합니다."
    uri="${1:+ipp://$1/ipp/print}"
    [ -z "$uri" ] && uri="$(find_airprint_uri)"
    if [ -z "$uri" ] || ! ipp_ok "$uri"; then
      say "프린터를 찾지 못했습니다. 프린터 전원과 Wi-Fi 연결을 확인해 주세요."
      exit 1
    fi
    if ! sudo lpadmin -p "$QUEUE" -D "$DESC" -E -v "$uri" -m everywhere; then
      say "자동 등록에 실패했습니다. 시스템 설정 > 프린터 및 스캐너 > 프린터 추가에서"
      say "프린터를 선택하고 '사용'을 'AirPrint'로 고른 뒤 추가하고, 이 명령을 다시 실행해 주세요."
      exit 1
    fi
    q="$QUEUE"
  fi

  say "대상 프린터: $q"
  drv="$(queue_driver "$q")"
  [ -n "$drv" ] && say "사용 중인 드라이버: $drv"
  case "$drv" in
    *[Ss]amsung*)
      say ""
      say "주의: 아직 삼성 드라이버를 쓰고 있습니다. 시스템 설정 > 프린터 및 스캐너에서"
      say "이 프린터를 제거한 뒤 다시 추가할 때 '사용'을 'AirPrint'로 골라 주세요."
      say "그다음 이 명령을 한 번 더 실행하면 나머지 설정이 적용됩니다."
      ;;
  esac

  say ""
  say "오류가 나도 멈추지 않고 다시 시도하도록 설정합니다. (관리자 암호를 물어보면 입력해 주세요)"
  sudo lpadmin -p "$q" -o printer-error-policy=retry-job -o printer-is-shared=false || exit 1
  sudo cupsenable "$q"
  sudo cupsaccept "$q"
  lpoptions -d "$q" >/dev/null

  say ""
  say "완료되었습니다. 기본 프린터: $q"
}

cmd_test() {
  q="$(find_queue)"
  [ -z "$q" ] && { say "등록된 프린터가 없습니다. 먼저 setup을 실행해 주세요."; exit 1; }
  printf 'Printer test page\n%s\n' "$(date)" | lp -d "$q" -t "Test" && say "시험 인쇄를 보냈습니다: $q"
}

# 오류로 멈춘(disabled) 프린터를 다시 켭니다. 인쇄 작업은 지우지 않습니다.
cmd_heal() {
  # printer-state 값 5 = 멈춤(stopped)
  lpstat -e 2>/dev/null | while read -r p; do
    [ "$(queue_attr "$p" printer-state)" = "5" ] || continue
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
