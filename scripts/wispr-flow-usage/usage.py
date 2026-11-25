#!/usr/bin/env python3
"""Wispr Flow 사용량 분석 (macOS 로컬 DB, 읽기 전용).

받아쓰기 원문은 출력하지 않고 집계 숫자만 보여준다.
사용법:  python3 usage.py            # 분석
        python3 usage.py --schema   # DB 구조만 출력 (문제 해결용)
"""
import glob, os, re, shutil, sqlite3, sys, tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

HOME = os.path.expanduser("~")
SEARCH_DIRS = [f"{HOME}/Library/Application Support/Wispr Flow",
               f"{HOME}/Library/Application Support/wispr-flow",
               f"{HOME}/Library/Application Support/Flow"]
TIME_HINTS = ("timestamp", "createdat", "created_at", "time", "date")
TEXT_HINTS = ("formattedtext", "editedtext", "asrtext", "text", "transcript")
WORD_HINTS = ("numwords", "wordcount", "words")
DUR_HINTS = ("duration", "audioduration", "length")
APP_HINTS = ("app", "appname", "application", "bundleid")
DOW = "월화수목금토일"


def find_dbs():
    out = []
    for d in SEARCH_DIRS:
        for ext in ("*.sqlite", "*.sqlite3", "*.db"):
            out += glob.glob(os.path.join(d, "**", ext), recursive=True)
    return sorted(set(out), key=os.path.getsize, reverse=True)


def open_copy(path):
    tmp = tempfile.mkdtemp()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            shutil.copy2(path + suffix, os.path.join(tmp, "db" + suffix))
    return sqlite3.connect(os.path.join(tmp, "db"))


def pick(cols, hints):
    low = {c.lower(): c for c in cols}
    for h in hints:
        if h in low:
            return low[h]
    for h in hints:
        for lc, c in low.items():
            if h in lc:
                return c
    return None


def parse_time(v):
    if v is None:
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d+(\.\d+)?", v)):
        x = float(v)
        if x > 1e12: x /= 1000          # ms
        if x < 9e8: return None
        return datetime.fromtimestamp(x, timezone.utc).astimezone()
    s = str(v).strip()
    s = re.sub(r"\s([+-]\d{2}):?(\d{2})$", r"\1\2", s)   # "... +00:00" -> "+0000"
    s = s.replace("Z", "+0000").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone()
        except ValueError:
            pass
    return None


def best_table(con):
    best = None
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
        tc, xc = pick(cols, TIME_HINTS), pick(cols, TEXT_HINTS)
        if not tc or not (xc or pick(cols, WORD_HINTS)):
            continue
        n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        score = n + (10**9 if t.lower() == "history" else 0)
        if not best or score > best[0]:
            best = (score, t, cols)
    return best


def bar(v, vmax, width=24):
    return "█" * (round(v / vmax * width) if vmax else 0)


def main():
    dbs = find_dbs()
    if not dbs:
        sys.exit("Wispr Flow DB를 찾지 못했습니다. 다음 결과를 알려주세요:\n"
                 "  ls -la ~/Library/Application\\ Support/ | grep -i -E 'wispr|flow'")
    if "--schema" in sys.argv:
        for p in dbs:
            print(f"\n== {p} ({os.path.getsize(p)//1024} KB)")
            con = open_copy(p)
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                print(f"  {t} ({n} rows): {', '.join(cols)}")
        return

    found = None
    for p in dbs:
        con = open_copy(p)
        bt = best_table(con)
        if bt:
            found = (p, con, bt[1], bt[2]); break
    if not found:
        sys.exit("받아쓰기 기록 테이블을 찾지 못했습니다. `python3 usage.py --schema` 결과를 알려주세요.")
    path, con, table, cols = found
    tc = pick(cols, TIME_HINTS); xc = pick(cols, TEXT_HINTS)
    wc = pick(cols, WORD_HINTS); dc = pick(cols, DUR_HINTS); ac = pick(cols, APP_HINTS)
    sel = [tc, xc or "NULL", wc or "NULL", dc or "NULL", ac or "NULL"]
    q = "SELECT " + ", ".join(f'"{c}"' if c != "NULL" else c for c in sel) + f' FROM "{table}"'

    rows = []
    for t, text, nw, dur, app in con.execute(q):
        dt = parse_time(t)
        if not dt:
            continue
        words = int(nw) if isinstance(nw, (int, float)) and nw else len(str(text or "").split())
        if words == 0 and not text:
            continue                     # 빈/실패 기록 제외
        d = float(dur) if isinstance(dur, (int, float)) else 0.0
        if d > 3600 * 3: d /= 1000       # ms로 저장된 경우
        rows.append((dt, words, d, (str(app).split("/")[-1] if app else None)))
    if not rows:
        sys.exit("유효한 기록이 없습니다. `python3 usage.py --schema` 결과를 알려주세요.")
    rows.sort()

    day = defaultdict(lambda: [0, 0, 0.0])
    week = defaultdict(lambda: [0, 0, 0.0])
    dow, hour, apps = Counter(), Counter(), Counter()
    for dt, w, d, app in rows:
        for bucket in (day[dt.date()], week[dt.date() - timedelta(days=dt.weekday())]):
            bucket[0] += 1; bucket[1] += w; bucket[2] += d
        dow[dt.weekday()] += w; hour[dt.hour] += w
        if app: apps[app] += w

    first, last = rows[0][0].date(), rows[-1][0].date()
    span_days = (last - first).days + 1
    tot_n = len(rows); tot_w = sum(r[1] for r in rows); tot_d = sum(r[2] for r in rows)
    act = len(day)
    full_weeks = max(span_days / 7, 1)

    print(f"\n📊 Wispr Flow 사용량 분석   (DB: {os.path.basename(path)} / 테이블: {table})")
    print(f"기간: {first} ~ {last}  ({span_days}일, 사용한 날 {act}일 = {act/span_days:.0%})")
    print(f"총계: 받아쓰기 {tot_n:,}회 · {tot_w:,}단어" + (f" · 말한 시간 {tot_d/3600:.1f}시간" if tot_d else ""))

    print("\n■ 하루 평균")
    print(f"  사용한 날 기준 : {tot_n/act:6.1f}회 · {tot_w/act:7,.0f}단어" + (f" · {tot_d/act/60:5.1f}분" if tot_d else ""))
    print(f"  전체 날짜 기준 : {tot_n/span_days:6.1f}회 · {tot_w/span_days:7,.0f}단어" + (f" · {tot_d/span_days/60:5.1f}분" if tot_d else ""))
    wsorted = sorted(v[1] for v in day.values())
    print(f"  중앙값(사용한 날) {wsorted[len(wsorted)//2]:,}단어 · 최대 {max(wsorted):,}단어 "
          f"({max(day, key=lambda k: day[k][1])})")

    print("\n■ 주 평균")
    print(f"  {tot_n/full_weeks:6.1f}회 · {tot_w/full_weeks:7,.0f}단어" + (f" · {tot_d/full_weeks/60:5.1f}분" if tot_d else "")
          + f" · 주당 {act/full_weeks:.1f}일 사용")

    print("\n■ 최근 8주 (월요일 시작)")
    recent = sorted(week)[-8:]
    mx = max(week[k][1] for k in recent)
    for k in recent:
        n, w, d = week[k]
        print(f"  {k}  {n:4d}회 {w:7,d}단어 " + (f"{d/60:5.0f}분 " if tot_d else "") + bar(w, mx))

    print("\n■ 최근 14일")
    mx = max((day[k][1] for k in day), default=0)
    for i in range(13, -1, -1):
        k = last - timedelta(days=i)
        n, w, d = day.get(k, [0, 0, 0.0])
        print(f"  {k} ({DOW[k.weekday()]})  {n:4d}회 {w:6,d}단어 " + bar(w, mx))

    print("\n■ 요일별 (단어, 해당 요일 평균)")
    ndow = Counter(k.weekday() for k in (first + timedelta(days=i) for i in range(span_days)))
    avg = {i: dow[i] / ndow[i] if ndow[i] else 0 for i in range(7)}
    mx = max(avg.values())
    for i in range(7):
        print(f"  {DOW[i]}  {avg[i]:7,.0f}  {bar(avg[i], mx)}")

    print("\n■ 시간대별 (전체 단어 비중)")
    mx = max(hour.values())
    for h in range(24):
        if hour[h]:
            print(f"  {h:02d}시  {hour[h]/tot_w:5.1%}  {bar(hour[h], mx)}")

    if apps:
        print("\n■ 많이 쓴 앱 Top 10 (단어)")
        for a, w in apps.most_common(10):
            print(f"  {w/tot_w:5.1%}  {a}")
    print()


if __name__ == "__main__":
    main()
