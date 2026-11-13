#!/usr/bin/env python3
"""consolidate_cheonggiwa.py 로 옮긴 파일을 원래 위치로 되돌리기.

입력: 정리 기록 CSV(_정리기록_<날짜>.csv) 또는 터미널 출력을 저장한 텍스트 파일.
기본은 미리보기. 실제로 되돌리려면 --apply.

  python3 undo_consolidate.py 기록.csv                      # 전체 미리보기
  python3 undo_consolidate.py 기록.csv --only Obsidian --apply   # 경로에 Obsidian 이 든 것만 복원
  python3 undo_consolidate.py 기록.csv --only "Mobile Documents" --only Codex --apply
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import unicodedata
from pathlib import Path

LINE = re.compile(r"^\[(?P<act>[^\]]+)\]\s+(?P<src>.+?)(?:\s{2}->\s{2}(?P<dst>.+))?\s*$")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def load(path: Path):
    rows = []
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig") as f:
            r = csv.reader(f)
            next(r, None)
            rows = [(a, s, d) for a, s, d in r]
    else:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LINE.match(line.strip())
            if m:
                rows.append((m["act"], m["src"].strip(), (m["dst"] or "").strip()))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path, help="정리 기록 CSV 또는 터미널 출력 텍스트")
    ap.add_argument("--only", action="append", help="원래 경로에 이 글자가 든 항목만 복원 (여러 번 가능)")
    ap.add_argument("--apply", action="store_true", help="실제로 되돌리기 (없으면 미리보기)")
    ap.add_argument("--target", type=Path,
                    default=Path.home() / "Desktop" / "[ultimate] 제주청기와장어", help="취합 폴더 경로")
    a = ap.parse_args()

    rows = load(a.log)
    if not rows:
        raise SystemExit("기록에서 작업 줄([이동] ... -> ...)을 찾지 못했습니다. 파일을 확인하세요.")
    only = [nfc(o) for o in (a.only or [])]
    ok = miss = 0
    recreated: set[Path] = set()
    touched: set[Path] = set()
    for act, src, dst in reversed(rows):  # 나중에 한 작업부터 거꾸로
        if only and not any(o in nfc(src) for o in only):
            continue
        s, d = Path(src), Path(dst) if dst else None
        if act.startswith("삭제(") and "빈" in act:
            print(f"[폴더 다시 만들기] {s}")
            if a.apply:
                s.mkdir(parents=True, exist_ok=True)
            recreated.add(s)
            ok += 1
        elif d and (act in ("이동", "평탄화") or act.startswith("삭제대기")):
            if not d.exists():
                print(f"[건너뜀: 옮겨진 파일 없음] {d}")
                miss += 1
                continue
            if s.exists():
                print(f"[건너뜀: 원래 자리에 이미 파일 있음] {s}")
                miss += 1
                continue
            print(f"[복원] {d}  ->  {s}")
            touched.add(d.parent)
            if a.apply:
                s.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(d), str(s))
            ok += 1
    # 스크립트가 새로 만든 흔적 정리: 비게 된 이동 대상 폴더(이미지/, 삭제대기 폴더 등)
    if a.apply and not only:
        for d in sorted(touched, key=lambda x: -len(x.parts)):
            while d.exists() and d not in recreated and d != d.parent:
                kids = [k for k in d.iterdir() if k.name != ".DS_Store"]
                if kids:
                    break
                shutil.rmtree(d)
                print(f"[빈 폴더 정리] {d}")
                d = d.parent
    # 사진 앱에서 내보낸 사본(원본은 사진 앱에 그대로 있음) → 휴지통으로
    exp = a.target / "이미지" / "사진앱_내보내기"
    if exp.exists():
        print(f"[사진앱 사본 → 휴지통] {exp}")
        if a.apply:
            trash = Path.home() / ".Trash"
            shutil.move(str(exp), str(trash / f"사진앱_내보내기_{exp.stat().st_mtime:.0f}"))
            img = exp.parent
            if img.exists() and not [k for k in img.iterdir() if k.name != ".DS_Store"]:
                shutil.rmtree(img)
    mode = "복원 완료" if a.apply else "미리보기 (실제로 하려면 --apply)"
    print(f"\n{mode}: {ok}건, 건너뜀 {miss}건")


if __name__ == "__main__":
    main()
