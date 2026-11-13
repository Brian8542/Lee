#!/usr/bin/env python3
"""복원 후 취합 폴더에 남은 파일(iCloud가 ' 2' 등으로 이름을 바꿔 복원 못 한 것)을
이름 유사도로 짝지어 원래 위치로 되돌림. 기본은 미리보기, 실행은 --apply.
파일을 지우거나 덮어쓰지 않음.

  python3 fix_leftovers.py ~/Desktop/정리출력.txt
  python3 fix_leftovers.py ~/Desktop/정리출력.txt --apply
"""
from __future__ import annotations

import argparse
import difflib
import re
import shutil
import unicodedata
from pathlib import Path

LINE = re.compile(r"^\[이동\]\s+(.+?)\s{2}->\s{2}(.+?)\s*$")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def key(name: str) -> tuple[str, str]:
    n = nfc(name)
    stem, ext = (n.rsplit(".", 1) + [""])[:2] if "." in n else (n, "")
    if len(ext) > 6 or " " in ext:  # 확장자가 아닌 점
        stem, ext = n, ""
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    stem = re.sub(r"\s+\d+$", "", stem)
    stem = re.sub(r"[\s\W_]+", "", stem)
    return stem, ext.lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--target", type=Path, default=Path.home() / "Desktop" / "[ultimate] 제주청기와장어")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    missing = []
    for line in a.log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(line.strip())
        if m:
            src, dst = Path(m[1]), Path(m[2])
            if not src.exists() and not dst.exists() and src not in missing:
                missing.append(src)
    left = [p for p in a.target.iterdir()
            if p.name != ".DS_Store" and not p.name.startswith("_정리기록_")]
    print(f"원래 자리로 못 돌아간 항목: {len(missing)}개 / 취합 폴더에 남은 항목: {len(left)}개\n")

    pairs = []
    for s in missing:
        ks = key(s.name)
        for c in left:
            kc = key(c.name)
            if ks[1] != kc[1]:
                continue
            r = difflib.SequenceMatcher(None, ks[0], kc[0]).ratio()
            pairs.append((r, s, c))
    pairs.sort(key=lambda x: -x[0])
    used_s, used_c, plan = set(), set(), []
    for r, s, c in pairs:
        if r < 0.85 or s in used_s or c in used_c:
            continue
        used_s.add(s); used_c.add(c); plan.append((r, s, c))

    for r, s, c in plan:
        print(f"[복원 {r:.0%}] {c.name}\n        ->  {s}")
        if a.apply:
            if s.exists():
                print("        (건너뜀: 원래 자리에 이미 있음)")
                continue
            s.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(c), str(s))
    for s in missing:
        if s not in used_s:
            print(f"[짝 못 찾음] {s}")
    for c in left:
        if c not in used_c:
            print(f"[그대로 둠: 원래 이 폴더에 있던 것으로 보임] {c.name}")
    print("\n" + ("복원 완료" if a.apply else "미리보기 (실제로 하려면 --apply)") + f": {len(plan)}건")


if __name__ == "__main__":
    main()
