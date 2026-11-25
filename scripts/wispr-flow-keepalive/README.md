# Wispr Flow Keep-Alive (macOS)

Wispr Flow가 맥이 켜져 있는 동안 24시간 꺼지지 않도록 하는 설정.

| 장치 | 역할 |
|---|---|
| LaunchAgent (`RunAtLoad` + `KeepAlive`) | 로그인 즉시 워치독 시작, 워치독이 죽어도 launchd가 재시작 |
| 워치독 (5초 주기) | Wispr Flow가 종료·크래시되면 백그라운드로 재실행 |
| `caffeinate -dimsu` | 디스플레이·시스템 유휴 잠자기 방지 |
| `pmset sleep 0 / disablesleep 1` | 시스템 잠자기·덮개 닫힘 잠자기 차단 |
| `pmset autorestart 1` | 정전 후 전원 복구 시 자동 부팅 |
| 로그인 항목 | 이중 안전장치 |

## 설치
```bash
bash install.sh
```

## 해제
```bash
bash uninstall.sh
```

## 한계
- 맥이 완전히 꺼지거나 재부팅되는 동안은 어떤 앱도 실행될 수 없습니다. 부팅 후 **로그인**되면 즉시 다시 켜집니다.
  무인 재부팅 후에도 바로 켜지게 하려면 *시스템 설정 > 사용자 및 그룹 > 자동 로그인*을 켜세요 (FileVault가 켜져 있으면 부팅 시 암호 입력 한 번 필요).
- 배터리 잔량 부족으로 인한 강제 종료, macOS 업데이트 재부팅은 막을 수 없습니다. 전원 어댑터 연결 상태로 사용하세요.
- 덮개를 닫은 채 잠자기를 막으면 발열·배터리 소모가 커집니다.
