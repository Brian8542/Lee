#!/usr/bin/env python3
"""06_MOC 허브와 07_QONE_Wiki/03_Wiki 위키 페이지를 규칙 기반으로 서로 연결한다.

AI 판단 없이 문자열 비교만 사용한다.

  확실한 짝: 허브 이름(" 허브" 앞부분)을 정규화한 값이 위키 페이지의
             파일명·title·aliases·counterparty·tags 중 하나를 정규화한 값과 완전히 같음
  애매한 짝: 완전 일치는 아니지만 한쪽이 다른 쪽을 포함함(2글자 이상),
             또는 허브 이름이 1글자라 완전 일치여도 확신할 수 없음
             -> 링크를 달지 않고 점검 파일에 목록으로만 남긴다

안전 규칙
  - 기본은 미리보기(dry-run). --apply 를 줘야 실제로 쓴다.
  - 수정하는 모든 파일은 쓰기 전에 백업 폴더(기본: 보관함 바깥)에 복사한다.
  - 기존 내용은 지우거나 바꾸지 않고 줄을 추가만 한다. 파일 삭제 없음.
  - 경로에 02_Raw 가 들어간 파일은 절대 수정하지 않는다.
  - 제한 노트(restricted/제한/기밀 표시)는 읽기만 하고 수정·링크 대상에서 뺀다.

사용법
  python link_hub_wiki.py "C:/Obsidian/보관함"           # 미리보기
  python link_hub_wiki.py "C:/Obsidian/보관함" --apply   # 실제 적용
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

MOC_DIR = "06_MOC"
WIKI_DIR = "07_QONE_Wiki/03_Wiki"
RAW_MARK = "02_Raw"
HUB_HEADING = "## 정리된 위키 페이지"
BACK_HEADING = "## 원본 허브"
MAX_LINKS_PER_HUB = 20

RESTRICT_WORDS = ("restricted", "confidential", "private", "제한", "기밀", "비공개")
COMPANY_WORDS = ("company", "companies", "회사", "거래처", "client", "vendor", "업체")
TOPIC_WORDS = ("topic", "topics", "주제", "concept", "개념")
SKIP_STEMS = {"index", "log", "readme"}
CORP_AFFIXES = ("주식회사", "(주)", "㈜", "(유)", "유한회사", "co.,ltd.", "co.,ltd", "co.ltd", "inc.", "inc", "ltd.", "ltd", "corp.", "corp")


# ---------- 프론트매터 ----------

def split_frontmatter(text: str) -> tuple[str, str]:
    """(프론트매터 블록 원문 '---'~'---\n' 포함, 본문) 반환. 없으면 ('', text)."""
    if not text.startswith("---"):
        return "", text
    m = re.match(r"^---[ \t]*\r?\n(.*?\r?\n)?---[ \t]*(\r?\n|$)", text, re.S)
    if not m:
        return "", text
    return text[: m.end()], text[m.end():]


def _scalar(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_scalar(x) for x in _split_inline_list(inner)]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    return v


def _split_inline_list(s: str) -> list[str]:
    out, buf, quote, depth = [], "", None, 0
    for ch in s:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == "[":
            depth += 1
            buf += ch
        elif ch == "]":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf)
    return out


def parse_frontmatter(block: str) -> dict:
    if not block:
        return {}
    lines = block.splitlines()[1:-1]
    data: dict = {}
    key = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line) or re.match(r"^\s*-$", line)
        if item and key is not None:
            val = item.group(1) if item.groups() else ""
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(_scalar(val))
            continue
        kv = re.match(r"^([^\s:#][^:]*):\s*(.*)$", line)
        if kv:
            key = kv.group(1).strip().lower()
            val = kv.group(2)
            data[key] = _scalar(val) if val.strip() else None
    return data


def as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x is not None and str(x).strip()]
    return [str(v)] if str(v).strip() else []


# ---------- 정규화 ----------

def clean_value(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^\[\[(.*?)\]\]$", r"\1", s)  # [[링크|별칭]] -> 링크|별칭
    s = s.split("|")[0]
    s = s.split("/")[-1]  # 경로·중첩 태그는 마지막 조각
    return s.lstrip("#").strip()


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", clean_value(s)).lower()
    s = s.replace(" ", "")
    for a in CORP_AFFIXES:
        if s.startswith(a) and len(s) > len(a):
            s = s[len(a):]
        if s.endswith(a) and len(s) > len(a):
            s = s[: -len(a)]
    return re.sub(r"[\s\-_.,·()\[\]{}'\"`~!@#$%^&*+=:;<>?/\\|]", "", s)


# ---------- 노트 모델 ----------

@dataclass
class Note:
    path: Path
    rel: str  # 보관함 기준 상대 경로(확장자 제외, '/' 구분)
    stem: str
    fm: dict
    restricted: bool
    kind: str = "other"  # company / topic / other (위키만)
    title: str = ""
    keys: dict = field(default_factory=dict)  # 정규화값 -> 출처 필드명


def is_restricted(path: Path, fm: dict) -> bool:
    for k in ("restricted", "confidential", "private", "제한"):
        if fm.get(k) is True or str(fm.get(k, "")).lower() in ("true", "yes", "1"):
            return True
    for k in ("access", "visibility", "security", "보안", "공개", "status"):
        if any(w in str(fm.get(k, "")).lower() for w in RESTRICT_WORDS):
            return True
    for t in as_list(fm.get("tags")):
        if any(w in t.lower() for w in RESTRICT_WORDS):
            return True
    return any(w in part.lower() for part in path.parts for w in ("제한", "기밀", "restricted"))


def classify(rel_parts: tuple[str, ...], fm: dict) -> str:
    for k in ("type", "category", "kind", "유형", "분류"):
        v = " ".join(as_list(fm.get(k))).lower()
        if any(w in v for w in COMPANY_WORDS):
            return "company"
        if any(w in v for w in TOPIC_WORDS):
            return "topic"
    for part in rel_parts[:-1]:
        p = part.lower()
        if any(w in p for w in COMPANY_WORDS):
            return "company"
        if any(w in p for w in TOPIC_WORDS):
            return "topic"
    return "other"


def load_note(vault: Path, path: Path) -> Note:
    text = path.read_text(encoding="utf-8-sig")
    block, _ = split_frontmatter(text)
    fm = parse_frontmatter(block)
    rel = path.relative_to(vault).with_suffix("").as_posix()
    return Note(path=path, rel=rel, stem=path.stem, fm=fm, restricted=is_restricted(path.relative_to(vault), fm))


def hub_key(stem: str) -> str | None:
    m = re.match(r"^\s*(.+?)\s*허브(\s|-|$)", unicodedata.normalize("NFC", stem))
    return m.group(1).strip() if m else None


# ---------- 파일 쓰기 ----------

def wikilink(n: Note) -> str:
    return f"[[{n.rel}|{n.title or n.stem}]]"


def existing_targets(text: str) -> set[str]:
    return {m.split("|")[0].strip() for m in re.findall(r"\[\[([^\]]+)\]\]", text)}


def section_bounds(body: str, heading: str) -> tuple[int, int] | None:
    m = re.search(rf"^{re.escape(heading)}[ \t]*$", body, re.M)
    if not m:
        return None
    nxt = re.search(r"^#{1,2} ", body[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(body)
    return m.start(), end


def add_hub_section(text: str, links: list[str]) -> tuple[str, int]:
    """프론트매터 바로 다음에 절을 추가(이미 있으면 빠진 링크만 절 끝에 추가)."""
    block, body = split_frontmatter(text)
    nl = "\r\n" if "\r\n" in text else "\n"
    b = section_bounds(body, HUB_HEADING)
    if b is None:
        new = [l for l in links][:MAX_LINKS_PER_HUB]
        if not new:
            return text, 0
        sec = HUB_HEADING + nl + nl + nl.join(f"- {l}" for l in new) + nl + nl
        if block and not block.endswith(("\n", "\r\n")):
            block += nl
        return block + sec + body, len(new)
    start, end = b
    present = existing_targets(body[start:end])
    room = MAX_LINKS_PER_HUB - len(present)
    new = [l for l in links if l[2:].split("|")[0] not in present][: max(room, 0)]
    if not new:
        return text, 0
    sec = body[start:end].rstrip("\r\n")
    sec += nl + nl.join(f"- {l}" for l in new) + nl + nl
    return block + body[:start] + sec + body[end:].lstrip("\r\n"), len(new)


def add_back_section(text: str, links: list[str]) -> tuple[str, int]:
    """파일 맨 아래에 절을 추가(이미 있으면 빠진 링크만 그 절 끝에 추가)."""
    nl = "\r\n" if "\r\n" in text else "\n"
    b = section_bounds(text, BACK_HEADING)
    if b is None:
        if not links:
            return text, 0
        tail = nl + BACK_HEADING + nl + nl + nl.join(f"- {l}" for l in links) + nl
        base = text.rstrip("\r\n") + nl if text.strip() else ""
        return base + tail, len(links)
    start, end = b
    present = existing_targets(text[start:end])
    new = [l for l in links if l[2:].split("|")[0] not in present]
    if not new:
        return text, 0
    sec = text[start:end].rstrip("\r\n") + nl + nl.join(f"- {l}" for l in new) + nl
    rest = text[end:]
    if rest:
        sec += nl
    return text[:start] + sec + rest, len(new)


def safe_write(vault: Path, path: Path, new_text: str, backup_root: Path) -> None:
    rel = path.relative_to(vault)
    if RAW_MARK in rel.parts or RAW_MARK in rel.as_posix():
        raise RuntimeError(f"02_Raw 수정 시도 차단: {rel}")
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(path, dest)
    path.write_text(new_text, encoding="utf-8", newline="")


# ---------- 메인 ----------

def main() -> int:
    ap = argparse.ArgumentParser(description="06_MOC 허브 <-> 03_Wiki 위키 자동 연결")
    ap.add_argument("vault", type=Path, help="옵시디언 보관함 폴더")
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 수정한다(없으면 미리보기)")
    ap.add_argument("--backup-dir", type=Path, help="백업 폴더(기본: 보관함 옆 <보관함>_backup_<시각>)")
    args = ap.parse_args()

    vault = args.vault.resolve()
    moc, wiki = vault / MOC_DIR, vault / WIKI_DIR
    for d in (moc, wiki):
        if not d.is_dir():
            print(f"폴더가 없습니다: {d}", file=sys.stderr)
            return 1

    now = dt.datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    backup_root = (args.backup_dir or vault.parent / f"{vault.name}_backup_{stamp}").resolve()
    if backup_root == vault or vault in backup_root.parents:
        print("백업 폴더는 보관함 바깥이어야 합니다(중복 노트 방지).", file=sys.stderr)
        return 1

    def md_files(root: Path):
        return sorted(p for p in root.rglob("*.md")
                      if RAW_MARK not in p.relative_to(vault).parts
                      and not any(x.startswith(".") for x in p.relative_to(vault).parts))

    # 허브 수집
    hubs: list[tuple[Note, str]] = []
    skipped_restricted: list[str] = []
    for p in md_files(moc):
        key = hub_key(p.stem)
        if not key:
            continue
        n = load_note(vault, p)
        if n.restricted:
            skipped_restricted.append(n.rel)
            continue
        n.title = n.stem
        hubs.append((n, key))

    # 위키 수집
    pages: list[Note] = []
    for p in md_files(wiki):
        if p.stem.lower() in SKIP_STEMS:
            continue
        n = load_note(vault, p)
        if n.restricted:
            skipped_restricted.append(n.rel)
            continue
        n.kind = classify(p.relative_to(vault).parts, n.fm)
        titles = as_list(n.fm.get("title"))
        n.title = clean_value(titles[0]) if titles else n.stem
        sources = [("파일명", n.stem)] + [("title", t) for t in titles]
        for f in ("aliases", "alias", "counterparty", "tags"):
            sources += [(f, v) for v in as_list(n.fm.get(f))]
        for f, v in sources:
            k = norm(v)
            if k:
                n.keys.setdefault(k, f)
        pages.append(n)

    # 짝 찾기
    kind_order = {"company": 0, "topic": 1, "other": 2}
    hub_links: dict[str, list[Note]] = {}
    back_links: dict[str, list[Note]] = {}
    ambiguous: list[tuple[str, str, str, str]] = []  # 허브, 위키, 필드, 이유
    for hub, key in hubs:
        hk = norm(key)
        if not hk:
            continue
        matched: list[Note] = []
        for pg in pages:
            if hk in pg.keys:
                if len(hk) < 2:
                    ambiguous.append((hub.rel, pg.rel, pg.keys[hk], f"허브 이름이 1글자('{key}')"))
                else:
                    matched.append(pg)
                continue
            for k, f in pg.keys.items():
                if len(k) >= 2 and len(hk) >= 2 and (hk in k or k in hk):
                    ambiguous.append((hub.rel, pg.rel, f, f"부분 일치('{key}' ~ '{k}')"))
                    break
        matched.sort(key=lambda x: (kind_order[x.kind], x.title))
        if matched:
            hub_links[hub.rel] = matched
            for pg in matched:
                if pg.kind in ("company", "topic"):
                    back_links.setdefault(pg.rel, []).append(hub)

    # 쓰기
    hub_by_rel = {h.rel: h for h, _ in hubs}
    page_by_rel = {p.rel: p for p in pages}
    n_hub_links = n_back_links = 0
    changed: list[str] = []
    for rel, pgs in hub_links.items():
        h = hub_by_rel[rel]
        text = h.path.read_text(encoding="utf-8-sig")
        new, added = add_hub_section(text, [wikilink(p) for p in pgs])
        if added:
            n_hub_links += added
            changed.append(rel)
            if args.apply:
                safe_write(vault, h.path, new, backup_root)
    for rel, hs in back_links.items():
        pg = page_by_rel[rel]
        text = pg.path.read_text(encoding="utf-8-sig")
        new, added = add_back_section(text, [wikilink(h) for h in sorted(hs, key=lambda x: x.rel)])
        if added:
            n_back_links += added
            changed.append(rel)
            if args.apply:
                safe_write(vault, pg.path, new, backup_root)

    mode = "적용" if args.apply else "미리보기"
    summary = (f"허브→위키 링크 {n_hub_links}개, 위키→허브 링크 {n_back_links}개, "
               f"애매한 짝 {len(ambiguous)}개, 수정 파일 {len(changed)}개, 제외한 제한 노트 {len(skipped_restricted)}개")
    print(f"[{mode}] 허브 {len(hubs)}개, 위키 페이지 {len(pages)}개 검사")
    print(summary)
    for rel in changed:
        print(f"  수정{'함' if args.apply else ' 예정'}: {rel}")

    # 점검 파일 + log.md
    report_dir = vault / "07_QONE_Wiki"
    check_path = report_dir / f"점검_허브위키_애매한짝_{stamp}.md"
    if args.apply:
        lines = [f"# 허브-위키 애매한 짝 점검 ({now:%Y-%m-%d %H:%M})", "",
                 "자동 연결하지 않은 후보입니다. 맞는 짝이면 직접 링크하거나 위키 aliases에 허브 이름을 추가한 뒤 스크립트를 다시 실행하세요.", "",
                 "| 허브 | 위키 페이지 | 비교 필드 | 이유 |", "|---|---|---|---|"]
        lines += [f"| [[{h}]] | [[{w}]] | {f} | {r} |" for h, w, f, r in ambiguous]
        if skipped_restricted:
            lines += ["", "## 제외한 제한 노트(수정·링크 안 함)", ""] + [f"- {r}" for r in skipped_restricted]
        check_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        log = next((p for p in (report_dir / "log.md", vault / "log.md") if p.exists()), report_dir / "log.md")
        entry = (f"\n## [{now:%Y-%m-%d %H:%M}] 허브-위키 상호 연결 (스크립트)\n\n"
                 f"- {summary}\n"
                 f"- 점검 파일: [[{check_path.relative_to(vault).with_suffix('').as_posix()}]]\n"
                 f"- 백업: {backup_root}\n")
        if log.exists():
            if backup_root.exists():
                shutil.copy2(log, backup_root / f"log_{stamp}.md")
            old = log.read_text(encoding="utf-8-sig")
            log.write_text(old.rstrip("\n") + "\n" + entry, encoding="utf-8")
        else:
            log.write_text("# log\n" + entry, encoding="utf-8")
        print(f"점검 파일: {check_path}")
        print(f"log 기록: {log}")
        print(f"백업 폴더: {backup_root}")
    else:
        for h, w, f, r in ambiguous:
            print(f"  애매: {h}  <->  {w}  [{f}] {r}")
        print("미리보기만 했습니다. 실제 적용은 --apply 를 붙여 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
