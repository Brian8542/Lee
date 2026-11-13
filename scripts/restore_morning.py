#!/usr/bin/env python3
"""[ultimate] 제주청기와장어 폴더를 오늘 정리 스크립트 실행 전 상태로 되돌림.

기준: 실행 때 터미널 출력(~/Desktop/정리출력.txt). 이 기록에서 '원래 이 폴더 안에 있던' 항목을 뽑아
  1. 제자리에 없으면 Mac 안에서 찾아 원래 자리로 옮김
  2. 지워졌던 하위 폴더는 다시 만듦
  3. 오늘 새로 생긴 항목(iCloud가 만든 ' 2' 사본 등)은 휴지통으로 옮김 (지우지 않음, 휴지통에서 복구 가능)
기본은 미리보기. 실제 실행은 --apply.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import unicodedata
from pathlib import Path

HOME = Path.home()
LINE = re.compile(r"^\[(?P<act>[^\]]+)\]\s+(?P<src>.+?)(?:\s{2}->\s{2}(?P<dst>.+?))?\s*$")
SKIP_DIRS = (".photoslibrary", ".app", ".git", ".Trash", "node_modules")


def nfc(s) -> str:
    return unicodedata.normalize("NFC", str(s))


def key(name: str) -> tuple[str, str]:
    n = nfc(name)
    stem, ext = (n.rsplit(".", 1) if "." in n else (n, ""))
    if len(ext) > 6 or " " in ext:
        stem, ext = n, ""
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    stem = re.sub(r"\s+\d+$", "", stem)
    return re.sub(r"[\s\W_]+", "", stem), ext.lower()


def born_today(p: Path) -> bool:
    st = p.stat()
    t = getattr(st, "st_birthtime", st.st_ctime)
    return dt.date.fromtimestamp(t) == dt.date.today()


def to_trash(p: Path) -> Path:
    trash = HOME / ".Trash"
    trash.mkdir(exist_ok=True)
    dst = trash / p.name
    i = 2
    while dst.exists():
        dst = trash / f"{p.stem} (복원정리 {i}){p.suffix}"
        i += 1
    shutil.move(str(p), str(dst))
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path, nargs="?", default=HOME / "Desktop" / "정리출력.txt")
    ap.add_argument("--target", type=Path, default=HOME / "Desktop" / "[ultimate] 제주청기와장어")
    ap.add_argument("--search", type=Path, action="append",
                    help="찾을 위치 (기본: 바탕화면·문서·다운로드·iCloud Drive)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    tgt = nfc(a.target).rstrip("/") + "/"
    morning: list[Path] = []      # 아침에 이 폴더 안에 있던 항목(원래 경로)
    morning_dirs: list[Path] = []
    all_src: set[str] = set()
    for line in a.log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(line.strip())
        if not m:
            continue
        src = m["src"].strip()
        all_src.add(nfc(src))
        if not nfc(src).startswith(tgt):
            continue
        if m["act"] == "이동" and Path(src) not in morning:
            morning.append(Path(src))
        elif m["act"].startswith("삭제(") and "빈" in m["act"]:
            morning_dirs.append(Path(src))

    missing = [p for p in morning if not p.exists()]
    print(f"오늘 아침 이 폴더 안에 있던 것으로 기록된 항목: {len(morning)}개")
    print(f"  - 지금 제자리에 있음: {len(morning) - len(missing)}개")
    print(f"  - 제자리에 없음(찾아서 되돌릴 것): {len(missing)}개\n")

    # 1) 없는 항목 찾기
    if missing:
        roots = a.search or [HOME / "Desktop", HOME / "Documents", HOME / "Downloads",
                             HOME / "Library/Mobile Documents/com~apple~CloudDocs"]
        want = {}
        for p in missing:
            want.setdefault(key(p.name), []).append(p)
        found: dict[tuple, list[Path]] = {}
        for r in roots:
            for dp, dns, fns in os.walk(r):
                dns[:] = [d for d in dns if not d.endswith(SKIP_DIRS) and not d.startswith(".")]
                for n in dns + fns:
                    k = key(n)
                    if k in want:
                        c = Path(dp) / n
                        if nfc(c) not in all_src or not Path(c).exists():
                            found.setdefault(k, []).append(c)
        for k, origs in want.items():
            cands = [c for c in found.get(k, []) if nfc(c) not in {nfc(o) for o in morning}]
            for orig in origs:
                if not cands:
                    print(f"[못 찾음] {orig}")
                    continue
                c = cands.pop(0)
                print(f"[되돌림] {c}\n      ->  {orig}")
                if a.apply and not orig.exists():
                    orig.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(c), str(orig))

    # 2) 지워졌던 하위 폴더 다시 만들기
    for d in morning_dirs:
        if not d.exists():
            print(f"[폴더 다시 만듦] {d}")
            if a.apply:
                d.mkdir(parents=True, exist_ok=True)

    # 3) 오늘 새로 생긴 항목 → 휴지통
    keep = {nfc(p) for p in morning} | {nfc(d) for d in morning_dirs}
    for p in sorted(a.target.rglob("*"), key=lambda x: -len(x.parts)):
        if p.name == ".DS_Store" or not p.exists():
            continue
        np = nfc(p)
        if np in keep or any(np.startswith(k + "/") or k.startswith(np + "/") for k in keep):
            continue  # 아침 항목 자신, 그 안의 것, 그 상위 폴더는 유지
        copy_like = re.search(r"(\s\d+|\s?\(\d+\))(\.[^.]{1,6})?$", nfc(p.name))
        if copy_like and born_today(p) and not (p.is_dir() and any(nfc(c) in keep for c in p.rglob("*"))):
            print(f"[오늘 생긴 것 → 휴지통] {p.relative_to(a.target)}")
            if a.apply:
                to_trash(p)

    print("\n" + ("완료" if a.apply else "미리보기입니다. 실제로 하려면 끝에 --apply 를 붙여 다시 실행하세요."))


if __name__ == "__main__":
    main()
