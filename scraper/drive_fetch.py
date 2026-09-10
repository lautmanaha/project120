#!/usr/bin/env python3
"""
פרויקט 120 - משיכת סקרים חדשים מתיקיית Google Drive ציבורית.

שירות חיצוני דוגם את אתר ועדת הבחירות ומעתיק כל PDF חדש לתיקייה משותפת ("כל מי שיש לו את הקישור").
תיקייה כזו ניתנת לרשימה ולהורדה בלי מפתח API, ובלי Cloudflare - ולכן זה רץ בשרת (GitHub Actions).

שם הקובץ בתיקייה: "סקר בחירות מיום 8.9.2026 4128 - נקסט דאטה.pdf"  -> מספר סימוכין 4128, תאריך, עורך.
לכל מספר סימוכין נשמר קובץ אחד (data/pdfs/cec_<ref>.pdf); כפילויות באותו מספר מתעלמות אלא אם התוכן שונה.
המטא-דאטה נכתב ל-polls_meta (עורך מתוך שם הקובץ; המזמין יגיע מהחילוץ).

הרצה:  python scraper/drive_fetch.py [--folder ID]   (ברירת מחדל: P120_DRIVE_FOLDER או המזהה הקבוע)
מדפיס בסוף: NEW=<n>
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data" / "pdfs"
DB = ROOT / "db" / "polls.sqlite"
DEFAULT_FOLDER = "1gjFnIeHgFHy9QdoWKuuUXE7Vqc6-zVDA"
UA = {"User-Agent": "Mozilla/5.0 (project120 poll fetcher)"}

NAME_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\D+(\d{4})(?:\s*-\s*(.+?))?\.pdf$", re.I)


def list_folder(folder_id: str) -> list[dict]:
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    html = r.text
    out = []
    for m in re.finditer(r'<div class="flip-entry" id="entry-([^"]+)"(.*?)<div class="flip-entry-last-modified">', html, re.S):
        fid, body = m.group(1), m.group(2)
        t = re.search(r'<div class="flip-entry-title">([^<]*)</div>', body)
        title = (t.group(1) if t else "").strip()
        out.append({"id": fid, "title": title})
    return out


def parse_title(title: str) -> dict | None:
    m = NAME_RE.search(title.replace("׳", "'").replace("’", "'"))
    if not m:
        return None
    d, mo, y, ref, editor = m.groups()
    try:
        date = dt.date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        date = None
    return {"ref": ref, "date": date, "editor": (editor or "").strip() or None}


def download(file_id: str) -> bytes:
    s = requests.Session()
    r = s.get("https://drive.google.com/uc", params={"export": "download", "id": file_id}, headers=UA, timeout=120)
    r.raise_for_status()
    if b"%PDF" in r.content[:1024]:
        return r.content
    # אישור סריקת וירוסים (קבצים גדולים) - לא צפוי ב-PDF של סקר, אבל ליתר ביטחון
    m = re.search(r'confirm=([0-9A-Za-z_-]+)', r.text)
    if m:
        r = s.get("https://drive.google.com/uc", params={"export": "download", "id": file_id, "confirm": m.group(1)}, headers=UA, timeout=120)
        r.raise_for_status()
        if b"%PDF" in r.content[:1024]:
            return r.content
    raise RuntimeError(f"לא התקבל PDF עבור {file_id}")


def upsert_meta(conn: sqlite3.Connection, ref: str, info: dict, fname: str, size: int, sha: str, file_id: str) -> None:
    now = dt.datetime.now().isoformat(timespec="seconds")
    today = dt.date.today().isoformat()
    exists = conn.execute("SELECT 1 FROM polls_meta WHERE reference_number=?", (ref,)).fetchone()
    if exists:
        conn.execute("UPDATE polls_meta SET file_name=?, file_size=?, local_pdf=?, pdf_sha256=?, last_seen=?, raw_json=? WHERE reference_number=?",
                     (fname, size, f"data/pdfs/cec_{ref}.pdf", sha, now, json.dumps({"source": "google-drive", "file_id": file_id, "title": fname}, ensure_ascii=False), ref))
    else:
        conn.execute("INSERT INTO polls_meta VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (ref, None, info.get("editor"), None, info.get("date"), today, today, today, None, fname, size,
                      f"https://drive.google.com/uc?export=download&id={file_id}", f"data/pdfs/cec_{ref}.pdf", sha,
                      json.dumps({"source": "google-drive", "file_id": file_id, "title": fname}, ensure_ascii=False), now, now))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=os.environ.get("P120_DRIVE_FOLDER", DEFAULT_FOLDER))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--payload", default=None, help="קובץ JSON מה-webhook (client_payload): פרטי הסקר + קישור ל-PDF")
    a = ap.parse_args(argv)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    new_from_payload = 0
    if a.payload and Path(a.payload).exists():
        try:
            new_from_payload = from_payload(json.loads(Path(a.payload).read_text(encoding="utf-8")))
        except Exception as ex:  # ה-webhook הוא קיצור דרך; אם נכשל - סריקת התיקייה תתפוס את הסקר
            print("payload נכשל:", ex)
    entries = list_folder(a.folder)
    print(f"בתיקייה: {len(entries)} קבצים")
    conn = sqlite3.connect(DB)
    new = 0
    seen_refs: dict[str, dict] = {}
    for e in entries:
        info = parse_title(e["title"])
        if not info:
            print("  דילוג (שם לא מזוהה):", e["title"]); continue
        # אם אותו מספר סימוכין מופיע פעמיים - מעדיפים את התאריך המאוחר בשם הקובץ
        prev = seen_refs.get(info["ref"])
        if prev and (prev["info"]["date"] or "") >= (info["date"] or ""):
            continue
        seen_refs[info["ref"]] = {"entry": e, "info": info}
    for ref, item in sorted(seen_refs.items()):
        e, info = item["entry"], item["info"]
        target = PDF_DIR / f"cec_{ref}.pdf"
        if target.exists():
            # אותו מספר סימוכין כבר אצלנו. אם בתיקייה יש גרסה עם שם חדש (הוגש מחדש עם תיקונים) - בודקים אם התוכן השתנה
            row = conn.execute("SELECT raw_json FROM polls_meta WHERE reference_number=?", (ref,)).fetchone()
            stored_title = (json.loads(row[0]).get("title") if row and row[0] else None)
            if stored_title == e["title"] or a.dry_run:
                continue
            data = download(e["id"]); sha = hashlib.sha256(data).hexdigest()
            if sha == hashlib.sha256(target.read_bytes()).hexdigest():
                upsert_meta(conn, ref, info, e["title"], len(data), sha, e["id"]); continue
            target.write_bytes(data)
            (ROOT / "data" / "extracted" / f"cec_{ref}.json").unlink(missing_ok=True)   # לחלץ מחדש
            upsert_meta(conn, ref, info, e["title"], len(data), sha, e["id"])
            new += 1; print(f"  הוחלף (גרסה מתוקנת): {ref} {e['title']}"); continue
        if a.dry_run:
            print("  חדש:", ref, e["title"]); new += 1; continue
        data = download(e["id"])
        sha = hashlib.sha256(data).hexdigest()
        dup = conn.execute("SELECT reference_number FROM polls_meta WHERE pdf_sha256=?", (sha,)).fetchone()
        target.write_bytes(data)
        upsert_meta(conn, ref, info, e["title"], len(data), sha, e["id"])
        new += 1
        print(f"  הורד: {ref} ({len(data)//1024} KB) {e['title']}" + (f"  [תוכן זהה ל-{dup[0]}]" if dup else ""))
    conn.commit()
    print(f"NEW={new + new_from_payload}")
    return 0


def from_payload(pl: dict) -> int:
    """סקר אחד שהגיע ב-webhook: מטא-דאטה מלא + קישור ישיר ל-PDF. מחזיר 1 אם נוסף."""
    if not pl or not pl.get("reference_number"):
        return 0
    ref = str(pl["reference_number"]).strip()
    url = pl.get("pdf_url") or ""
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})|[?&]id=([A-Za-z0-9_-]{20,})", url)
    file_id = (m.group(1) or m.group(2)) if m else None
    target = PDF_DIR / f"cec_{ref}.pdf"
    conn = sqlite3.connect(DB)
    if target.exists():
        conn.execute("UPDATE polls_meta SET survey_editor=COALESCE(?,survey_editor), survey_publisher=COALESCE(?,survey_publisher), publish_date=COALESCE(?,publish_date) WHERE reference_number=?",
                     (pl.get("survey_editor"), pl.get("survey_publisher"), pl.get("publish_date"), ref))
        conn.commit(); print(f"  webhook: {ref} כבר קיים - עודכן מטא-דאטה"); return 0
    if file_id:
        data = download(file_id)
    else:
        r = requests.get(url, headers=UA, timeout=120); r.raise_for_status(); data = r.content
        if b"%PDF" not in data[:1024]:
            raise RuntimeError("הקישור לא מחזיר PDF")
    sha = hashlib.sha256(data).hexdigest()
    target.write_bytes(data)
    now = dt.datetime.now().isoformat(timespec="seconds"); today = dt.date.today().isoformat()
    conn.execute("INSERT OR REPLACE INTO polls_meta VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (ref, None, pl.get("survey_editor"), pl.get("survey_publisher"), pl.get("survey_date"), pl.get("publish_date") or today,
                  pl.get("publish_date") or today, today, pl.get("notes"), pl.get("file_name"), len(data), url,
                  f"data/pdfs/cec_{ref}.pdf", sha, json.dumps({"source": "webhook", "file_id": file_id, "title": pl.get("file_name")}, ensure_ascii=False), now, now))
    conn.commit()
    print(f"  webhook: הורד {ref} ({len(data)//1024} KB) {pl.get('survey_editor') or ''}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
