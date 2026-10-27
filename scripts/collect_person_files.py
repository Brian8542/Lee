#!/usr/bin/env python3
"""폴더 안에서 특정 인물(기본: 한정훈) 관련 파일을 찾아 한 폴더로 모은다.

찾는 기준
  1) 파일명이나 상위 폴더명에 키워드가 들어감 (띄어쓰기 무시)
  2) 맥(macOS)이면 Spotlight(mdfind)로 파일 내용에 키워드가 들어간 것도 찾음
     (PDF, 워드, 엑셀, 텍스트 등 Spotlight가 읽을 수 있는 파일)

안전 규칙
  - 기본은 미리보기(dry-run). --apply 를 줘야 실제로 복사한다.
  - 기본은 복사. 원본을 옮기려면 --move 를 함께 준다.
  - 같은 이름 파일이 있으면 덮어쓰지 않고 이름 뒤에 (2), (3)을 붙인다.
  - 모은 폴더에 원래 위치 목록(_목록.csv)을 남긴다.

사용법 (맥 터미널)
  python3 collect_person_files.py                              # 미리보기
  python3 collect_person_files.py --apply                      # 복사
  python3 collect_person_files.py --apply --move               # 이동
  python3 collect_person_files.py "다른/폴더" -k 한정훈 -k 청기와 --apply
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

DEFAULT_ROOT = Path.home() / "Desktop" / "40_관계사" / "제주청기와장어"
DEFAULT_KEYWORDS = ["한정훈"]
DEFAULT_OUT = "한정훈_대표이사_관련"
SKIP_NAMES = {".DS_Store", "Icon\r"}


def norm(text: str) -> str:
    # 맥 파일명은 한글 자모가 분리된(NFD) 형태라 NFC로 맞춘 뒤 비교한다.
    return unicodedata.normalize("NFC", text).replace(" ", "").lower()


def name_matches(path: Path, root: Path, keywords: list[str]) -> bool:
    rel = norm(str(path.relative_to(root)))
    return any(norm(k) in rel for k in keywords)


def spotlight_matches(root: Path, keywords: list[str]) -> set[Path]:
    if sys.platform != "darwin" or not shutil.which("mdfind"):
        return set()
    found: set[Path] = set()
    for k in keywords:
        try:
            out = subprocess.run(
                ["mdfind", "-onlyin", str(root), k],
                capture_output=True, text=True, timeout=60,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        found.update(Path(line) for line in out.splitlines() if line)
    return {p for p in found if p.is_file()}


def unique_dest(dest_dir: Path, name: str) -> Path:
    dest = dest_dir / name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while dest.exists():
        dest = dest_dir / f"{stem} ({n}){suffix}"
        n += 1
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="인물 관련 파일을 한 폴더로 모은다.")
    ap.add_argument("root", nargs="?", default=str(DEFAULT_ROOT), help="찾을 폴더")
    ap.add_argument("-k", "--keyword", action="append", help="찾을 단어 (여러 번 지정 가능)")
    ap.add_argument("-o", "--out", default=DEFAULT_OUT, help="모을 폴더 이름 (찾을 폴더 안에 만듦)")
    ap.add_argument("--apply", action="store_true", help="실제로 복사/이동")
    ap.add_argument("--move", action="store_true", help="복사 대신 이동")
    ap.add_argument("--no-content", action="store_true", help="파일 내용 검색(Spotlight) 끄기")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"폴더가 없습니다: {root}")
        return 1
    keywords = args.keyword or DEFAULT_KEYWORDS
    out_dir = root / args.out

    hits: dict[Path, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name in SKIP_NAMES or out_dir in p.parents:
            continue
        if name_matches(p, root, keywords):
            hits[p] = "파일명/폴더명"
    if not args.no_content:
        for p in spotlight_matches(root, keywords):
            if out_dir not in p.parents and p not in hits:
                hits[p] = "파일 내용"

    action = "이동" if args.move else "복사"
    print(f"찾을 폴더: {root}")
    print(f"키워드: {', '.join(keywords)}")
    print(f"찾은 파일: {len(hits)}개 -> {out_dir}\n")
    for p, why in sorted(hits.items()):
        print(f"  [{why}] {p.relative_to(root)}")

    if not hits:
        return 0
    if not args.apply:
        print(f"\n미리보기입니다. 실제로 {action}하려면 --apply 를 붙여 다시 실행하세요.")
        return 0

    out_dir.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = out_dir / f"_목록_{stamp}.csv"
    with log_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["새 파일명", "원래 위치", "찾은 기준", "처리"])
        for p, why in sorted(hits.items()):
            dest = unique_dest(out_dir, p.name)
            if args.move:
                shutil.move(str(p), dest)
            else:
                shutil.copy2(p, dest)
            w.writerow([dest.name, str(p.relative_to(root)), why, action])
    print(f"\n{len(hits)}개 {action} 완료. 목록: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
