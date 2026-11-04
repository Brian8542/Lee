#!/usr/bin/env python3
"""외장 드라이브(예: My Passport)에서 내용이 완전히 같은 중복 파일을 찾는다.

파일 이름이 아니라 "내용"을 비교한다. 이름이 달라도 내용이 같으면 중복이고,
이름이 같아도 내용이 다르면 중복이 아니다.

  1) 크기가 같은 파일끼리만 후보로 묶는다
  2) 앞부분 1MB 해시로 한 번 더 거른다
  3) 전체 SHA-256 해시가 같으면 중복으로 확정한다

각 중복 묶음에서 1개는 "남길 파일"로 정하고 나머지를 "지울 후보"로 표시한다.
  남길 파일 우선순위:
    - 백업/다운로드성 폴더(맥북에서_옮김, ZZ 다운로드, 복사본 등)에 있지 않은 파일
    - 파일 이름에 "복사본", "copy", "(1)" 같은 표시가 없는 파일
    - 수정일이 가장 오래된 파일(원본일 가능성이 높음)
    - 경로가 가장 짧은 파일

안전 규칙
  - 기본은 보고서만 만든다. 파일을 건드리지 않는다.
  - --move 를 주면 지울 후보를 드라이브 안 "_중복파일_삭제대기" 폴더로 옮긴다
    (원래 폴더 구조 유지). 확인 후 그 폴더만 휴지통에 버리면 된다.
  - --restore 로 옮긴 파일을 원래 자리로 되돌릴 수 있다.
  - 이 스크립트는 파일을 직접 삭제하지 않는다.

사용법 (맥 터미널)
  python3 find_duplicates.py "/Volumes/My Passport"            # 1단계: 보고서만
  python3 find_duplicates.py "/Volumes/My Passport" --move     # 2단계: 삭제대기 폴더로 이동
  python3 find_duplicates.py "/Volumes/My Passport" --restore  # 되돌리기
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import os
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

HOLD_DIR_NAME = "_중복파일_삭제대기"
MOVE_LOG_NAME = "_이동기록.csv"

# 맥/윈도우가 자동으로 만드는 시스템 파일·폴더는 검사하지 않는다.
SKIP_DIRS = {
    ".Spotlight-V100", ".Trashes", ".fseventsd", ".TemporaryItems",
    ".DocumentRevisions-V100", "System Volume Information", "$RECYCLE.BIN",
    HOLD_DIR_NAME,
}
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini", "Icon\r"}

# 이 단어가 들어간 폴더에 있는 파일은 "사본"일 가능성이 높다고 보고 먼저 지울 후보로 둔다.
LOW_PRIORITY_DIR_WORDS = [
    "맥북에서_옮김", "옮김", "다운로드", "download", "downloads", "백업", "backup",
    "복사본", "copy", "임시", "temp", "tmp", "zz ",
]
COPY_NAME_PATTERNS = [
    re.compile(r"복사본"),
    re.compile(r"\bcopy\b", re.I),
    re.compile(r"\(\d+\)(\.[^.]+)?$"),       # 파일(1).pdf
    re.compile(r" \d{1,2}(\.[^.]+)?$"),       # 맥에서 복제한 파일: 파일 2.pdf
    re.compile(r"사본"),
]

CHUNK = 1024 * 1024  # 1MB


def nfc(s: str) -> str:
    """맥은 한글 파일명을 자모 분리(NFD)로 저장하므로 비교·출력용으로 합친다."""
    return unicodedata.normalize("NFC", s)


def human(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}TB"


def progress(msg: str) -> None:
    sys.stderr.write("\r" + msg[:110].ljust(110))
    sys.stderr.flush()


def scan(root: Path, min_size: int) -> list[tuple[Path, int, float]]:
    files = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name in SKIP_FILES or name.startswith("._"):
                continue
            p = Path(dirpath) / name
            try:
                if p.is_symlink():
                    continue
                st = p.stat()
            except OSError:
                continue
            if st.st_size < min_size:
                continue
            files.append((p, st.st_size, st.st_mtime))
            count += 1
            if count % 500 == 0:
                progress(f"[1/3] 파일 목록 수집 중... {count:,}개")
    progress(f"[1/3] 파일 목록 수집 완료: {count:,}개")
    sys.stderr.write("\n")
    return files


def hash_file(p: Path, limit: int | None = None) -> str | None:
    h = hashlib.sha256()
    read = 0
    try:
        with open(p, "rb") as f:
            while True:
                if limit is not None and read >= limit:
                    break
                buf = f.read(CHUNK)
                if not buf:
                    break
                h.update(buf)
                read += len(buf)
    except OSError:
        return None
    return h.hexdigest()


def find_groups(files, root: Path):
    by_size = defaultdict(list)
    for item in files:
        by_size[item[1]].append(item)
    cands = [g for g in by_size.values() if len(g) > 1]
    total = sum(len(g) for g in cands)

    # 2단계: 앞부분 1MB 해시
    by_head = defaultdict(list)
    done = 0
    for g in cands:
        for item in g:
            hh = hash_file(item[0], limit=CHUNK)
            done += 1
            if done % 50 == 0:
                progress(f"[2/3] 빠른 비교 중... {done:,}/{total:,}")
            if hh:
                by_head[(item[1], hh)].append(item)
    progress(f"[2/3] 빠른 비교 완료: {total:,}개")
    sys.stderr.write("\n")

    # 3단계: 전체 해시 (1MB 이하 파일은 앞부분 해시가 곧 전체 해시)
    cands2 = [g for g in by_head.values() if len(g) > 1]
    total2 = sum(len(g) for g in cands2)
    bytes_total = sum(i[1] for g in cands2 for i in g)
    by_full = defaultdict(list)
    done = 0
    bytes_done = 0
    for g in cands2:
        for item in g:
            if item[1] <= CHUNK:
                fh = "small:" + hash_file(item[0], limit=CHUNK)  # type: ignore[operator]
            else:
                fh = hash_file(item[0])
            done += 1
            bytes_done += item[1]
            progress(f"[3/3] 정밀 비교 중... {done:,}/{total2:,} "
                     f"({human(bytes_done)}/{human(bytes_total)}) {nfc(item[0].name)}")
            if fh:
                by_full[(item[1], fh)].append(item)
    progress(f"[3/3] 정밀 비교 완료: {total2:,}개")
    sys.stderr.write("\n")

    groups = [g for g in by_full.values() if len(g) > 1]
    groups.sort(key=lambda g: g[0][1] * (len(g) - 1), reverse=True)
    return groups


def keep_score(item, root: Path):
    p, size, mtime = item
    rel = nfc(str(p.relative_to(root))).lower()
    parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
    low_dir = any(w in parent for w in LOW_PRIORITY_DIR_WORDS)
    stem = nfc(p.name)
    copy_name = any(pat.search(stem) for pat in COPY_NAME_PATTERNS)
    # 작은 값일수록 남길 파일
    return (low_dir, copy_name, mtime, len(rel), rel)


def fmt_time(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def write_reports(groups, root: Path, out_dir: Path):
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = out_dir / f"중복파일_목록_{stamp}.csv"
    html_path = out_dir / f"중복파일_보고서_{stamp}.html"

    rows = []
    total_waste = 0
    for gi, g in enumerate(groups, 1):
        ordered = sorted(g, key=lambda it: keep_score(it, root))
        total_waste += g[0][1] * (len(g) - 1)
        for idx, (p, size, mtime) in enumerate(ordered):
            rows.append({
                "묶음번호": gi,
                "처리": "남김" if idx == 0 else "삭제후보",
                "크기": human(size),
                "크기(바이트)": size,
                "수정일": fmt_time(mtime),
                "경로": nfc(str(p.relative_to(root))),
            })

    # 엑셀에서 한글이 깨지지 않도록 utf-8-sig 사용
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["경로"])
        w.writeheader()
        w.writerows(rows)

    # 폴더별 낭비 용량 요약
    by_folder = defaultdict(int)
    for r in rows:
        if r["처리"] == "삭제후보":
            top = r["경로"].split("/", 1)[0] if "/" in r["경로"] else "(최상위)"
            by_folder[top] += r["크기(바이트)"]

    del_count = sum(1 for r in rows if r["처리"] == "삭제후보")
    parts = [
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>중복 파일 보고서</title><style>",
        "body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:24px;"
        "background:#fff;color:#222}",
        "table{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:18px}",
        "td,th{border:1px solid #ddd;padding:4px 8px;text-align:left;word-break:break-all}",
        "th{background:#f3f3f3}.keep{background:#eaf7ea}.del{background:#fdeeee}",
        "h2{margin-top:28px}.sum{font-size:16px;line-height:1.7}",
        "@media (prefers-color-scheme:dark){body{background:#1e1e1e;color:#ddd}",
        "th{background:#333}td,th{border-color:#444}.keep{background:#203a20}"
        ".del{background:#402424}}",
        "</style></head><body>",
        f"<h1>중복 파일 보고서</h1><div class='sum'>검사 위치: {html.escape(str(root))}<br>",
        f"중복 묶음: <b>{len(groups):,}개</b> / 삭제 후보 파일: <b>{del_count:,}개</b><br>",
        f"삭제 시 확보 가능한 용량: <b>{human(total_waste)}</b></div>",
        "<h2>폴더별 확보 가능 용량</h2><table><tr><th>최상위 폴더</th><th>용량</th></tr>",
    ]
    for folder, b in sorted(by_folder.items(), key=lambda x: -x[1]):
        parts.append(f"<tr><td>{html.escape(folder)}</td><td>{human(b)}</td></tr>")
    parts.append("</table><h2>중복 묶음 (용량 큰 순)</h2>")
    cur = None
    for r in rows:
        if r["묶음번호"] != cur:
            if cur is not None:
                parts.append("</table>")
            cur = r["묶음번호"]
            parts.append(f"<b>#{cur} · {r['크기']}</b><table><tr><th>처리</th>"
                         "<th>수정일</th><th>경로</th></tr>")
        cls = "keep" if r["처리"] == "남김" else "del"
        parts.append(f"<tr class='{cls}'><td>{r['처리']}</td><td>{r['수정일']}</td>"
                     f"<td>{html.escape(r['경로'])}</td></tr>")
    if cur is not None:
        parts.append("</table>")
    parts.append("</body></html>")
    html_path.write_text("".join(parts), encoding="utf-8")
    return csv_path, html_path, total_waste, del_count, rows


def move_candidates(rows, root: Path):
    hold = root / HOLD_DIR_NAME
    hold.mkdir(exist_ok=True)
    log_path = hold / MOVE_LOG_NAME
    new_log = not log_path.exists()
    moved = 0
    with open(log_path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["원래경로", "이동한경로"])
        for r in rows:
            if r["처리"] != "삭제후보":
                continue
            src = root / r["경로"]
            if not src.exists():
                # NFC로 바꾼 이름으로 못 찾으면 NFD로 다시 시도
                src = root / unicodedata.normalize("NFD", r["경로"])
                if not src.exists():
                    print(f"  건너뜀(파일 없음): {r['경로']}")
                    continue
            dst = hold / r["경로"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                print(f"  건너뜀(이미 있음): {r['경로']}")
                continue
            shutil.move(str(src), str(dst))
            w.writerow([r["경로"], str(dst.relative_to(root))])
            moved += 1
    return moved, hold


def restore(root: Path):
    hold = root / HOLD_DIR_NAME
    log_path = hold / MOVE_LOG_NAME
    if not log_path.exists():
        print("되돌릴 기록이 없습니다.")
        return
    back = 0
    with open(log_path, encoding="utf-8-sig") as f:
        for orig, moved in list(csv.reader(f))[1:]:
            src, dst = root / moved, root / orig
            if src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                back += 1
    log_path.rename(hold / f"_이동기록_되돌림완료_{dt.datetime.now():%Y%m%d_%H%M}.csv")
    print(f"{back:,}개 파일을 원래 자리로 되돌렸습니다.")


def main():
    ap = argparse.ArgumentParser(description="내용이 같은 중복 파일 찾기")
    ap.add_argument("root", help='검사할 위치 (예: "/Volumes/My Passport")')
    ap.add_argument("--move", action="store_true",
                    help=f"삭제 후보를 '{HOLD_DIR_NAME}' 폴더로 이동")
    ap.add_argument("--restore", action="store_true", help="이동한 파일을 원래 자리로 되돌림")
    ap.add_argument("--min-size", type=int, default=1,
                    help="이 크기(바이트) 미만 파일은 무시 (기본 1, 빈 파일 제외)")
    ap.add_argument("--out", default=None,
                    help="보고서 저장 폴더 (기본: 바탕화면)")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"폴더를 찾을 수 없습니다: {root}")

    if args.restore:
        restore(root)
        return

    out_dir = Path(args.out).expanduser() if args.out else Path.home() / "Desktop"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"검사 시작: {root}")
    files = scan(root, args.min_size)
    groups = find_groups(files, root)
    if not groups:
        print("중복 파일이 없습니다.")
        return

    csv_path, html_path, waste, del_count, rows = write_reports(groups, root, out_dir)
    print()
    print(f"중복 묶음 {len(groups):,}개, 삭제 후보 {del_count:,}개, 확보 가능 용량 {human(waste)}")
    print(f"보고서(보기 편함): {html_path}")
    print(f"목록(엑셀용):     {csv_path}")
    print()
    print("상위 10개 (용량 큰 순):")
    shown = 0
    for r in rows:
        if r["처리"] == "삭제후보":
            print(f"  {r['크기']:>9}  {r['경로']}")
            shown += 1
            if shown >= 10:
                break

    if args.move:
        print()
        moved, hold = move_candidates(rows, root)
        print(f"{moved:,}개 파일을 '{hold}' 로 옮겼습니다.")
        print("확인 후 이 폴더를 휴지통에 버리고 휴지통을 비우면 용량이 확보됩니다.")
        print("되돌리려면 같은 명령에 --move 대신 --restore 를 붙여 실행하세요.")
    else:
        print()
        print("파일은 아무것도 바뀌지 않았습니다. 보고서를 확인한 뒤,")
        print("정리하려면 같은 명령 끝에 --move 를 붙여 다시 실행하세요.")


if __name__ == "__main__":
    main()
