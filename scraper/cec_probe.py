#!/usr/bin/env python3
"""
פרויקט 120 - איתור סקרים חדשים ישירות מאתר ועדת הבחירות, בלי ה-API ובלי סוכן חיצוני.

כתובת ה-PDF של כל סקר קבועה:
    https://www.gov.il/BlobFolder/dynamiccollectorresultitem/knesset_election<N>/he/Survey_<REF>.pdf
<N> הוא מספר רץ של הפרסום באתר (1, 2, 3, ...), <REF> מספר האסמכתא (עולה, עם דילוגים).
לכן אפשר "לגשש": לפרסום הבא (N+1) מנסים את האסמכתאות שאחרי האחרונה הידועה; פגיעה = סקר חדש.

המיפוי הידוע (N -> REF) נשמר ב-db/cec_index.json ומתעדכן בכל פגיעה.
הרצה:  python scraper/cec_probe.py [--max-ahead 40] [--dry-run]
מדפיס בסוף: NEW=<n>   (ו-BLOCKED אם Cloudflare חוסם - ואז נשארים על תיקיית ה-Drive)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "polls.sqlite"
PDF_DIR = ROOT / "data" / "pdfs"
INDEX = ROOT / "db" / "cec_index.json"
URL = "https://www.gov.il/BlobFolder/dynamiccollectorresultitem/knesset_election{n}/he/Survey_{ref}.pdf"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/pdf,*/*;q=0.8", "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
    "Referer": "https://www.gov.il/he/Departments/DynamicCollectors/knesset_election_polls_26",
}


def load_index(conn: sqlite3.Connection) -> dict[int, int]:
    idx: dict[int, int] = {}
    for ref, urlname in conn.execute("SELECT reference_number, url_name FROM polls_meta WHERE url_name LIKE 'knesset_election%'"):
        try:
            idx[int(urlname.replace("knesset_election", ""))] = int(ref)
        except ValueError:
            pass
    if INDEX.exists():
        for k, v in json.loads(INDEX.read_text(encoding="utf-8")).items():
            idx[int(k)] = int(v)
    return idx


def save_index(idx: dict[int, int]) -> None:
    INDEX.write_text(json.dumps({str(k): v for k, v in sorted(idx.items())}, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch(session: requests.Session, n: int, ref: int, timeout: int = 40) -> tuple[int, bytes | None]:
    r = session.get(URL.format(n=n, ref=ref), headers=HEADERS, timeout=timeout, allow_redirects=True)
    if r.status_code == 200 and r.content[:5] == b"%PDF-":
        return 200, r.content
    return r.status_code, None


def register(conn: sqlite3.Connection, ref: int, n: int, data: bytes) -> None:
    fname = f"Survey_{ref}.pdf"
    target = PDF_DIR / f"cec_{ref}.pdf"
    target.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    today = dt.date.today().isoformat()
    row = conn.execute("SELECT reference_number FROM polls_meta WHERE reference_number=?", (str(ref),)).fetchone()
    if row:
        conn.execute("UPDATE polls_meta SET url_name=?, file_name=?, file_url=?, file_size=?, local_pdf=?, pdf_sha256=?, last_seen=? WHERE reference_number=?",
                     (f"knesset_election{n}", fname, URL.format(n=n, ref=ref), len(data), str(target), sha, today, str(ref)))
    else:
        conn.execute("INSERT INTO polls_meta (reference_number, url_name, publish_date, file_name, file_size, file_url, local_pdf, pdf_sha256, raw_json, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (str(ref), f"knesset_election{n}", today, fname, len(data), URL.format(n=n, ref=ref), str(target), sha,
                      json.dumps({"source": "cec_probe", "title": fname}, ensure_ascii=False), today, today))
    conn.commit()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-ahead", type=int, default=40, help="כמה אסמכתאות קדימה לנסות לכל פרסום")
    ap.add_argument("--max-new", type=int, default=12, help="כמה פרסומים חדשים לכל היותר בריצה אחת")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    idx = load_index(conn)
    if not idx:
        print("אין מיפוי ידוע (db/cec_index.json) - אין מאיפה להתחיל"); print("NEW=0"); return 1
    n = max(idx); ref = idx[n]
    print(f"אחרון ידוע: knesset_election{n} -> {ref}")
    session = requests.Session()
    new, blocked = 0, False
    for _ in range(a.max_new):
        n += 1
        hit = None
        for cand in range(ref + 1, ref + 1 + a.max_ahead):
            try:
                code, data = fetch(session, n, cand)
            except Exception as ex:
                print(f"  {n}/{cand}: {type(ex).__name__}: {ex}", file=sys.stderr); blocked = True; break
            if code in (403, 429, 503):
                print(f"  {n}/{cand}: HTTP {code} - כנראה Cloudflare", file=sys.stderr); blocked = True; break
            if code == 200 and data:
                hit = (cand, data); break
            time.sleep(0.3)
        if blocked or not hit:
            break
        ref, data = hit
        idx[n] = ref
        print(f"  חדש: knesset_election{n} -> {ref} ({len(data)//1024} KB)")
        if not a.dry_run:
            register(conn, ref, n, data)
            save_index(idx)
        new += 1
    if blocked:
        print("BLOCKED")
    print(f"NEW={new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
