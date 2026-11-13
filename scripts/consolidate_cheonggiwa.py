#!/usr/bin/env python3
"""제주청기와장어 관련 파일/폴더를 바탕화면의 "[ultimate] 제주청기와장어" 폴더로 취합하고 정리.

하는 일
  1. 검색 위치(기본: 바탕화면, 문서, 다운로드)에서 이름에 키워드(기본: 청기와)가 들어간
     파일·폴더를 찾아 대상 폴더로 이동
  2. 대상 폴더 안에서 내용이 완전히 같은 파일(SHA-256 동일)은 하나만 남기고 삭제
  3. 옮기고 나서 비어버린 원래 폴더 삭제 (--sweep-empty 면 검색 위치의 모든 빈 폴더)
  4. 의미 없는 파일(.DS_Store, Thumbs.db, desktop.ini, ~$임시파일)과 빈 폴더 삭제
  5. 폴더 하나만 들어 있는 "껍데기 폴더"는 한 단계 평탄화

안전장치
  - 기본은 미리보기(dry-run). 실제 실행은 --apply
  - 삭제 대상은 바로 지우지 않고 바탕화면의 "_청기와정리_삭제대기_<날짜>" 폴더로 이동
    (확인 후 직접 비우면 됨). 즉시 영구삭제는 --permanent
  - 모든 작업 내역은 대상 폴더의 _정리기록_<날짜>.csv 에 기록

사용 예
  python consolidate_cheonggiwa.py                 # 미리보기
  python consolidate_cheonggiwa.py --apply         # 실행
  python consolidate_cheonggiwa.py --apply --keyword 청기와 --keyword 장어
  python consolidate_cheonggiwa.py --root "D:/자료" --apply
  python consolidate_cheonggiwa.py --apply --sweep-empty   # 관련 없는 빈 폴더까지 삭제
  python3 consolidate_cheonggiwa.py --apply --images --photos   # Mac: 관련 이미지 전부
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

TARGET_NAME = "[ultimate] 제주청기와장어"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".tif", ".tiff",
             ".bmp", ".raw", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".psd", ".ai", ".svg"}
# 앱 번들·사진 라이브러리 안의 파일을 빼내면 라이브러리가 망가지므로 절대 들어가지 않음
PACKAGE_EXT = (".photoslibrary", ".app", ".bundle", ".pkg", ".imovielibrary", ".fcpbundle",
               ".photolibrary", ".aplibrary", ".musiclibrary")
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "ehthumbs.db", ".localized"}
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


def nfc(s: str) -> str:
    # macOS는 한글 파일명을 NFD로 저장하므로 비교 전에 정규화
    return unicodedata.normalize("NFC", s)


def find_desktop() -> Path:
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "바탕 화면",
        home / "바탕 화면",
        home / "바탕화면",
    ]
    for c in candidates:
        if (c / TARGET_NAME).is_dir():
            return c
    for c in candidates:
        if c.is_dir():
            return c
    sys.exit("바탕화면 폴더를 찾지 못했습니다. --desktop 으로 경로를 지정하세요.")


class Organizer:
    def __init__(self, target: Path, trash: Path, apply: bool, permanent: bool):
        self.target, self.trash = target, trash
        self.apply, self.permanent = apply, permanent
        self.log: list[tuple[str, str, str]] = []
        self.planned: list[Path] = []   # 취합할 원본 경로 (미리보기용)
        self.emptied: set[Path] = set()

    # ---------- 기본 동작 ----------
    def record(self, action: str, src: Path, dst: Path | str = ""):
        self.log.append((action, str(src), str(dst)))
        print(f"[{action}] {src}" + (f"  ->  {dst}" if dst else ""))

    def move(self, src: Path, dst: Path, action="이동"):
        # 폴더를 자기 자신 안으로 옮기지 않음 (macOS 한글 NFD/NFC 차이로 shutil이
        # 복사 후 원본을 통째로 지우는 사고 방지)
        if nfc(os.path.realpath(dst)).startswith(nfc(os.path.realpath(src)) + os.sep) or \
                nfc(os.path.realpath(src)) == nfc(os.path.realpath(dst)):
            print(f"[건너뜀: 자기 자신 안으로 이동] {src}")
            return src
        dst = unique_path(dst)
        self.record(action, src, dst)
        if self.apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        return dst

    def remove(self, p: Path, reason: str):
        if p.is_dir() and not any(p.iterdir()) or reason == "빈 폴더":
            self.record(f"삭제({reason})", p)  # 빈 폴더는 잃을 게 없으므로 바로 삭제
            if self.apply:
                shutil.rmtree(p)
            return
        if self.permanent:
            self.record(f"삭제({reason})", p)
            if self.apply:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        else:
            self.move(p, self.trash / self.rel(p), action=f"삭제대기({reason})")

    # ---------- 1단계: 취합 ----------
    def collect(self, roots: list[Path], keywords: list[str], sweep: bool):
        kws = [nfc(k).lower() for k in keywords]
        skip = {nfc(self.target.resolve()), nfc(self.trash.resolve())}
        for root in roots:
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                d = Path(dirpath)
                # 대상/삭제대기 폴더, 숨김·시스템 폴더는 건너뜀
                dirnames[:] = [
                    n for n in dirnames
                    if not n.startswith(".") and n not in {"AppData", "Library", "node_modules"}
                    and not n.lower().endswith(PACKAGE_EXT)
                    and not is_protected(d / n)
                    and nfc((d / n).resolve()) not in skip
                ]
                for n in list(dirnames):
                    if any(k in nfc(n).lower() for k in kws):
                        self.planned.append(d / n)
                        self.move(d / n, self.target / n)
                        dirnames.remove(n)  # 통째로 옮겼으니 안으로 들어가지 않음
                        self.emptied.add(d)
                for n in filenames:
                    if any(k in nfc(n).lower() for k in kws):
                        self.planned.append(d / n)
                        self.move(d / n, self.target / n)
                        self.emptied.add(d)
                if sweep and d != root:
                    self.emptied.add(d)
        # 옮기고 나서 비어버린 원래 폴더 정리 (검색 위치 자체는 남김)
        root_set = {r.resolve() for r in roots}
        for d in sorted(self.emptied, key=lambda x: -len(x.parts)):
            while d.resolve() not in root_set and d.exists() and not self.real_children(d):
                self.record("삭제(빈 원본 폴더)", d)
                if self.apply:
                    d.rmdir()
                d = d.parent

    # ---------- Mac 이미지: Spotlight ----------
    def collect_spotlight_images(self, keywords: list[str], home: Path):
        """파일 이름뿐 아니라 이미지 속 글자(라이브 텍스트), 태그, 코멘트, 키워드에
        키워드가 들어간 이미지를 Spotlight(mdfind)로 찾아 대상/이미지 로 이동."""
        if not shutil.which("mdfind"):
            print("  (mdfind 없음: macOS가 아니라서 건너뜀)")
            return
        attrs = ["kMDItemDisplayName", "kMDItemTextContent", "kMDItemKeywords",
                 "kMDItemUserTags", "kMDItemFinderComment", "kMDItemTitle", "kMDItemDescription"]
        cond = " || ".join(f'{a} == "*{k}*"cd' for k in keywords for a in attrs)
        query = f'kMDItemContentTypeTree == "public.image" && ({cond})'
        try:
            out = subprocess.run(["mdfind", "-onlyin", str(home), query],
                                 capture_output=True, text=True, timeout=600).stdout
        except Exception as e:  # noqa: BLE001
            print(f"  Spotlight 검색 실패: {e}")
            return
        skip = [self.target.resolve(), self.trash.resolve()] + [p.resolve() for p in self.planned]
        for line in out.splitlines():
            p = Path(line)
            if not p.is_file() or p.suffix.lower() not in IMAGE_EXT:
                continue
            parts = [x.lower() for x in p.parts]
            if any(x.endswith(PACKAGE_EXT) for x in parts) or "library" in parts[:4] and \
                    "mobile documents" not in parts:
                continue  # 사진 앱 라이브러리·앱 내부 파일은 건드리지 않음 (사진 앱은 --photos 로)
            rp = p.resolve()
            if inside_protected(p, home):
                continue
            if any(rp == s or s in rp.parents for s in skip):
                continue
            self.planned.append(p)
            self.move(p, self.target / "이미지" / p.name)

    # ---------- Mac 이미지: 사진 앱 ----------
    def export_photos_app(self, keywords: list[str]):
        """사진(Photos) 앱에서 키워드로 검색되는 사진을 원본으로 내보내기(복사).
        사진 앱 라이브러리에서는 아무것도 지우지 않음."""
        if not shutil.which("osascript"):
            print("  (osascript 없음: macOS가 아니라서 건너뜀)")
            return
        dest = self.target / "이미지" / "사진앱_내보내기"
        for k in keywords:
            k_as = k.replace('"', '\\"')
            dest_as = str(dest).replace('"', '\\"')
            export = (f'export found to (POSIX file "{dest_as}" as alias) with using originals'
                      if self.apply else "")
            script = f'''
with timeout of 7200 seconds
  tell application "Photos"
    set found to search for "{k_as}"
    if (count of found) > 0 then
      {export}
    end if
    return count of found
  end tell
end timeout'''
            if self.apply:
                dest.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  사진 앱 검색 실패({k}): {r.stderr.strip()}\n"
                      "  → 시스템 설정 > 개인정보 보호 및 보안 > 자동화 에서 터미널의 '사진' 접근을 허용하세요.")
                continue
            n = r.stdout.strip() or "0"
            self.record(f"사진앱 내보내기({k}, {n}장)", Path("Photos"), dest)

    # ---------- 2단계: 중복 파일 ----------
    def dedupe(self):
        by_size: dict[int, list[Path]] = {}
        for p in self.files():
            by_size.setdefault(p.stat().st_size, []).append(p)
        for size, group in by_size.items():
            if len(group) < 2:
                continue
            by_hash: dict[str, list[Path]] = {}
            for p in group:
                by_hash.setdefault(sha256(p), []).append(p)
            for same in by_hash.values():
                if len(same) < 2:
                    continue
                # 보존 우선순위: 얕은 경로 → "복사본/(1)" 없는 이름 → 오래된 파일
                same.sort(key=lambda p: (len(self.rel(p).parts),
                                         looks_like_copy(p.name),
                                         p.stat().st_mtime, len(p.name)))
                keep = same[0]
                for dup in same[1:]:
                    self.remove(dup, f"중복: {self.rel(keep)}")

    # ---------- 3단계: 의미 없는 파일·빈 폴더 ----------
    def cleanup(self):
        for p in self.files():
            n = p.name.lower()
            if n in JUNK_NAMES or n.startswith("~$") or n.startswith("._") or p.stat().st_size == 0:
                self.remove(p, "의미없는 파일")
        # 껍데기 폴더 평탄화: 폴더 안에 하위 폴더 하나만 있고 파일이 없으면 끌어올림
        for d in sorted(self.dirs(), key=lambda x: -len(x.parts)):
            kids = self.children(d)
            if len(kids) == 1 and kids[0].is_dir():
                inner = kids[0]
                for item in self.children(inner):
                    self.move(item, d / item.name, action="평탄화")
        # 빈 폴더 삭제 (깊은 곳부터)
        for d in sorted(self.dirs(), key=lambda x: -len(x.parts)):
            if not self.children(d):
                self.remove(d, "빈 폴더")

    # ---------- 도우미 (미리보기 모드에서도 계획된 이동을 반영) ----------
    def rel(self, p: Path) -> Path:
        """대상 폴더 기준 상대경로. 미리보기에서 아직 원본 위치에 있는 파일도 처리."""
        try:
            return p.relative_to(self.target)
        except ValueError:
            for src in self.planned:
                if p == src or src in p.parents:
                    return Path(src.name) / p.relative_to(src)
            return Path(p.name)

    def gone(self) -> set[str]:
        planned = {str(s) for s in self.planned}
        return {src for act, src, _ in self.log
                if self.apply or (src not in planned and act != "삭제(빈 원본 폴더)")}

    def files(self):
        gone = self.gone()
        pool = [self.target] + ([] if self.apply else self.planned)
        for base in pool:
            items = [base] if base.is_file() else base.rglob("*")
            for p in items:
                if p.is_file() and not any(str(a) in gone for a in [p, *p.parents]):
                    yield p

    def dirs(self):
        gone = self.gone()
        return [p for p in self.target.rglob("*")
                if p.is_dir() and not any(str(a) in gone for a in [p, *p.parents])]

    def children(self, d: Path):
        gone = self.gone()
        return [c for c in d.iterdir() if str(c) not in gone] if d.exists() else []

    def real_children(self, d: Path):
        moved = {src for _, src, _ in self.log}
        return [c for c in d.iterdir() if str(c) not in moved]

    def write_log(self):
        out = self.target / f"_정리기록_{STAMP}.csv"
        if not self.apply:
            out = Path.cwd() / f"_정리미리보기_{STAMP}.csv"
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["작업", "원래 위치", "새 위치"])
            w.writerows(self.log)
        return out


def is_protected(d: Path) -> bool:
    """다른 프로그램이 관리하는 폴더는 건드리지 않음: Obsidian 볼트, git 저장소,
    다른 [ultimate] 정리 폴더."""
    n = nfc(d.name)
    if n.startswith("[ultimate]") and n != TARGET_NAME:
        return True
    return (d / ".obsidian").is_dir() or (d / ".git").exists()


def inside_protected(p: Path, stop: Path) -> bool:
    for parent in p.parents:
        if parent == stop or parent == parent.parent:
            break
        if is_protected(parent):
            return True
    return False


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def looks_like_copy(name: str) -> bool:
    n = nfc(name).lower()
    return any(t in n for t in ("복사본", "사본", "copy", "(1)", "(2)", "(3)", " - 복사"))


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 2
    while True:
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="실제로 실행 (없으면 미리보기)")
    ap.add_argument("--permanent", action="store_true", help="삭제대기 폴더 없이 즉시 영구삭제")
    ap.add_argument("--keyword", action="append", help="파일/폴더 이름 키워드 (기본: 청기와)")
    ap.add_argument("--root", action="append", type=Path, help="검색 위치 추가 (기본: 바탕화면·문서·다운로드)")
    ap.add_argument("--desktop", type=Path, help="바탕화면 경로 직접 지정")
    ap.add_argument("--sweep-empty", action="store_true",
                    help="검색 위치 안의 관련 없는 빈 폴더까지 모두 삭제")
    ap.add_argument("--images", action="store_true",
                    help="[Mac] 사진·iCloud Drive 폴더 추가 검색 + Spotlight로 이미지 속 글자/태그까지 검색해 취합")
    ap.add_argument("--photos", action="store_true",
                    help="[Mac] 사진 앱에서 키워드로 검색되는 사진을 원본으로 내보내기(복사)")
    a = ap.parse_args()

    desktop = a.desktop or find_desktop()
    target = desktop / TARGET_NAME
    trash = desktop / f"_청기와정리_삭제대기_{STAMP}"
    home = Path.home()
    roots = a.root or [desktop, home / "Documents", home / "문서", home / "Downloads", home / "다운로드"]
    keywords = a.keyword or ["청기와"]
    if a.images:
        roots += [home / "Pictures", home / "사진",
                  home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"]  # iCloud Drive

    print(f"대상 폴더 : {target}\n검색 위치 : {', '.join(map(str, roots))}\n키워드    : {keywords}")
    print("모드      : " + ("실행" if a.apply else "미리보기 (실제 변경 없음, --apply 로 실행)") + "\n")
    if a.apply:
        target.mkdir(parents=True, exist_ok=True)
    elif not target.exists():
        print("※ 대상 폴더가 아직 없어서 --apply 시 새로 만듭니다.")

    org = Organizer(target, trash, a.apply, a.permanent)
    print("── 1단계: 관련 파일·폴더 취합"); org.collect(roots, keywords, a.sweep_empty)
    if a.images:
        print("\n── 1-2단계: Spotlight 이미지 검색 (이미지 속 글자·태그·코멘트 포함)")
        org.collect_spotlight_images(keywords, home)
    if a.photos:
        print("\n── 1-3단계: 사진 앱에서 내보내기")
        org.export_photos_app(keywords)
    if target.exists():
        print("\n── 2단계: 중복 파일 제거"); org.dedupe()
        print("\n── 3단계: 의미 없는 파일·빈 폴더 정리"); org.cleanup()

    out = org.write_log()
    print(f"\n완료: 작업 {len(org.log)}건. 기록 파일: {out}")
    if a.apply and not a.permanent and trash.exists() and org.log:
        print(f"삭제 대상은 '{trash}' 에 모아두었습니다. 확인 후 폴더째 지우세요.")


if __name__ == "__main__":
    main()
