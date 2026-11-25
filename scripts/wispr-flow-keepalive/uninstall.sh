#!/bin/bash
# Wispr Flow 상시 구동 해제 (원래 상태로 복구)
LABEL="com.wisprflow.keepalive"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Library/Application Support/WisprFlowKeepAlive"
pkill -f "caffeinate -dimsu" 2>/dev/null || true
sudo pmset -a disablesleep 0
sudo pmset -a sleep 1
sudo pmset -a disksleep 10
echo "해제 완료. (로그인 항목의 Wispr Flow는 시스템 설정 > 일반 > 로그인 항목에서 직접 제거하세요.)"
