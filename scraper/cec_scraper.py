#!/usr/bin/env python3
"""
פרויקט 120 - איסוף סקרי בחירות מאתר ועדת הבחירות המרכזית (gov.il)
=====================================================================

מקור: https://www.gov.il/he/Departments/DynamicCollectors/knesset_election_polls_26
ה-API הפנימי: POST https://www.gov.il/he/api/DynamicCollector
    {"DynamicTemplateID": "b043127d-d79d-472e-ac10-5567bc9e8d3d",
     "QueryFilters": {"skip": {"Query": N}}, "From": N}
מחזיר 10 רשומות לעמוד, TotalResults בראש.

קובצי ה-PDF:
    https://www.gov.il/BlobFolder/dynamiccollectorresultitem/<UrlName>/he/<FileName>
(מוגנים ב-Cloudflare - ייתכן שיידרש דפדפן/עוגיית אימות. ראו README.)

מה הסקריפט עושה:
  1. מושך את כל רשומות ה-metadata (עורך, מזמין/ערוץ, תאריכים, מס' אסמכתא, קובץ).
  2. מכניס/מעדכן אותן בטבלת polls_meta ב-SQLite (מפתח: reference_number).
  3. מוריד PDF לכל רשומה שעדיין אין לה קובץ מקומי.
  4. מדפיס סיכום: כמה חדשים, כמה עודכנו.

הרצה יומית:  python cec_scraper.py --db ../db/polls.sqlite --pdf-dir ../data/pdfs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

API_URL = "https://www.gov.il/he/api/DynamicCollector"
TEMPLATE_ID = "b043127d-d79d-472e-ac10-5567bc9e8d3d"
BLOB_URL = "https://www.gov.il/BlobFolder/dynamiccollectorresultitem/{urlname}/he/{filename}"
PAGE_SIZE = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": "https://www.gov.il/he/Departments/DynamicCollectors/knesset_election_polls_26",
}
IL_TZ = timezone(timedelta(hours=3))

SCHEMA = """
CREATE TABLE IF NOT EXISTS polls_meta (
    reference_number TEXT PRIMARY KEY,
    url_name         TEXT,
    survey_editor    TEXT,      -- עורך הסקר (המכון) כפי שנרשם
    survey_publisher TEXT,      -- מזמין הסקר / הערוץ כפי שנרשם
    survey_date      TEXT,      -- מועד ביצוע הסקר (YYYY-MM-DD, שעון ישראל)
    transfer_date    TEXT,      -- מועד העברה לוועדה
    publish_date     TEXT,      -- מועד פרסום באתר הוועדה
    update_date      TEXT,      -- מועד עדכון
    notes            TEXT,      -- הערות על דיווח הסקר
    file_name        TEXT,
    file_size        INTEGER,
    file_url         TEXT,
    local_pdf        TEXT,      -- נתיב מקומי אחרי הורדה
    pdf_sha256       TEXT,
    raw_json         TEXT,      -- הרשומה המקורית מה-API
    first_seen       TEXT,
    last_seen        TEXT
);
CREATE TABLE IF NOT EXISTS scrape_log (
    run_at      TEXT,
    total_api   INTEGER,
    new_rows    INTEGER,
    updated     INTEGER,
    downloaded  INTEGER,
    errors      TEXT
);
"""


def il_date(iso: str | None) -> str | None:
    """'2026-08-31T21:00:00Z' -> '2026-09-01' (התאריך שהוועדה התכוונה אליו, שעון ישראל)."""
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(IL_TZ)
    return dt.date().isoformat()


def fetch_all(session: requests.Session, max_pages: int = 200) -> list[dict]:
    out: list[dict] = []
    total = None
    for page in range(max_pages):
        skip = page * PAGE_SIZE
        body = {"DynamicTemplateID": TEMPLATE_ID,
                "QueryFilters": {"skip": {"Query": skip}}, "From": skip}
        r = session.post(API_URL, headers=HEADERS, data=json.dumps(body), timeout=60)
        r.raise_for_status()
        j = r.json()
        total = j.get("TotalResults", total)
        results = j.get("Results") or []
        if not results:
            break
        out.extend(results)
        if total is not None and len(out) >= total:
            break
        time.sleep(0.5)
    return out


def upsert(conn: sqlite3.Connection, items: list[dict]) -> tuple[int, int]:
    now = datetime.now(IL_TZ).isoformat(timespec="seconds")
    new = updated = 0
    for it in items:
        d = it.get("Data", {})
        ref = str(d.get("reference_number") or "").strip()
        if not ref:
            continue
        files = d.get("file_PDF") or []
        f = files[0] if files else {}
        fname = f.get("FileName")
        url = BLOB_URL.format(urlname=it.get("UrlName"), filename=quote(fname)) if fname else None
        row = dict(
            reference_number=ref,
            url_name=it.get("UrlName"),
            survey_editor=(d.get("survey_editor") or "").strip(),
            survey_publisher=(d.get("survey_publisher") or "").strip(),
            survey_date=il_date(d.get("date_the_survey")),
            transfer_date=il_date(d.get("transfer_to_cec")),
            publish_date=il_date(d.get("public_to_cec")),
            update_date=il_date(d.get("update_to_cec")),
            notes=(d.get("Survey_Notes") or d.get("survey_report_comments") or None),
            file_name=fname,
            file_size=int(f.get("FileSize") or 0) or None,
            file_url=url,
            raw_json=json.dumps(it, ensure_ascii=False),
        )
        cur = conn.execute("SELECT raw_json FROM polls_meta WHERE reference_number=?", (ref,))
        existing = cur.fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO polls_meta (reference_number,url_name,survey_editor,survey_publisher,
                   survey_date,transfer_date,publish_date,update_date,notes,file_name,file_size,
                   file_url,raw_json,first_seen,last_seen)
                   VALUES (:reference_number,:url_name,:survey_editor,:survey_publisher,:survey_date,
                   :transfer_date,:publish_date,:update_date,:notes,:file_name,:file_size,:file_url,
                   :raw_json,:now,:now)""", {**row, "now": now})
            new += 1
        else:
            changed = existing[0] != row["raw_json"]
            conn.execute(
                """UPDATE polls_meta SET url_name=:url_name,survey_editor=:survey_editor,
                   survey_publisher=:survey_publisher,survey_date=:survey_date,
                   transfer_date=:transfer_date,publish_date=:publish_date,update_date=:update_date,
                   notes=:notes,file_name=:file_name,file_size=:file_size,file_url=:file_url,
                   raw_json=:raw_json,last_seen=:now,
                   local_pdf=CASE WHEN :changed THEN NULL ELSE local_pdf END
                   WHERE reference_number=:reference_number""",
                {**row, "now": now, "changed": 1 if changed else 0})
            updated += int(changed)
    conn.commit()
    return new, updated


def download_missing(conn: sqlite3.Connection, session: requests.Session, pdf_dir: Path,
                     cookies: dict | None) -> tuple[int, list[str]]:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT reference_number, file_url FROM polls_meta "
        "WHERE file_url IS NOT NULL AND (local_pdf IS NULL OR local_pdf='')").fetchall()
    got, errors = 0, []
    for ref, url in rows:
        target = pdf_dir / f"cec_{ref}.pdf"
        if target.exists() and target.stat().st_size > 1000:
            _register_pdf(conn, ref, target)
            got += 1
            continue
        try:
            r = session.get(url, headers={**HEADERS, "Accept": "application/pdf,*/*"},
                            cookies=cookies, timeout=90)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                errors.append(f"{ref}: HTTP {r.status_code} (Cloudflare?)")
                continue
            target.write_bytes(r.content)
            _register_pdf(conn, ref, target)
            got += 1
            time.sleep(1.0)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{ref}: {e}")
    conn.commit()
    return got, errors


def _register_pdf(conn: sqlite3.Connection, ref: str, path: Path) -> None:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    conn.execute("UPDATE polls_meta SET local_pdf=?, pdf_sha256=? WHERE reference_number=?",
                 (str(path), sha, ref))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="db/polls.sqlite")
    ap.add_argument("--pdf-dir", default="data/pdfs")
    ap.add_argument("--no-download", action="store_true", help="metadata בלבד")
    ap.add_argument("--cf-cookie", default=None,
                    help="ערך cf_clearance מהדפדפן, אם Cloudflare חוסם הורדות ישירות")
    ap.add_argument("--from-json", default=None,
                    help="במקום לפנות ל-API, לטעון רשומות מקובץ JSON שנשמר מהדפדפן")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    session = requests.Session()
    errors: list[str] = []
    if args.from_json:
        items = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        try:
            items = fetch_all(session)
        except Exception as e:  # noqa: BLE001
            print(f"שגיאה בגישה ל-API: {e}", file=sys.stderr)
            return 2
    new, updated = upsert(conn, items)

    downloaded = 0
    if not args.no_download:
        cookies = {"cf_clearance": args.cf_cookie} if args.cf_cookie else None
        downloaded, dl_errors = download_missing(conn, session, Path(args.pdf_dir), cookies)
        errors.extend(dl_errors)

    conn.execute("INSERT INTO scrape_log VALUES (?,?,?,?,?,?)",
                 (datetime.now(IL_TZ).isoformat(timespec="seconds"), len(items), new, updated,
                  downloaded, "\n".join(errors) or None))
    conn.commit()
    print(f"API: {len(items)} רשומות | חדשות: {new} | עודכנו: {updated} | PDF הורדו: {downloaded}")
    if errors:
        print("שגיאות:\n  " + "\n  ".join(errors), file=sys.stderr)
    missing = conn.execute("SELECT COUNT(*) FROM polls_meta WHERE local_pdf IS NULL").fetchone()[0]
    if missing:
        print(f"עדיין חסרים {missing} קובצי PDF.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
