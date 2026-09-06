#!/usr/bin/env python3
"""
פרויקט 120 - משיכת נתונים מאתר הוועדה דרך דפדפן אמיתי (Playwright/Chromium).

למה צריך את זה: קובצי ה-PDF ב-gov.il יושבים מאחורי אימות Cloudflare ("יש לאמת שאינך רובוט").
פנייה ישירה מ-requests מקבלת 403. דפדפן עם פרופיל קבוע עובר את האימות פעם אחת
(בפעם הראשונה בחלון גלוי - לוחצים על התיבה) ושומר את העוגייה לריצות הבאות.

שימוש:
  python browser_fetch.py --init            # ריצה ראשונה: חלון גלוי, לעבור אימות, לסגור
  python browser_fetch.py                   # ריצה רגילה (headless): metadata + PDF חסרים
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "scraper" / ".browser_profile"
PAGE_URL = "https://www.gov.il/he/Departments/DynamicCollectors/knesset_election_polls_26?skip=0"
TEMPLATE_ID = "b043127d-d79d-472e-ac10-5567bc9e8d3d"

FETCH_ALL_JS = """
async (templateId) => {
  const all = []; let total = null;
  for (let skip = 0; skip < 2000; skip += 10) {
    const r = await fetch('/he/api/DynamicCollector', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({DynamicTemplateID: templateId, QueryFilters: {skip: {Query: skip}}, From: skip})});
    const j = await r.json(); total = j.TotalResults;
    if (!j.Results || !j.Results.length) break;
    all.push(...j.Results);
    if (all.length >= total) break;
  }
  return all;
}
"""

FETCH_PDF_JS = """
async (url) => {
  const r = await fetch(url, {credentials: 'include'});
  if (r.status !== 200) return {status: r.status};
  const b = await r.arrayBuffer();
  let s = ''; const bytes = new Uint8Array(b);
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return {status: 200, b64: btoa(s)};
}
"""


def run(init: bool, db_path: Path, pdf_dir: Path, meta_out: Path) -> int:
    from playwright.sync_api import sync_playwright
    import base64
    import hashlib

    pdf_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=not init, channel="chrome" if init else None,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
            locale="he-IL")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)

        # 1. metadata
        items = page.evaluate(FETCH_ALL_JS, TEMPLATE_ID)
        meta_out.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        print(f"metadata: {len(items)} רשומות")

        # 2. עדכון DB (משתמשים בלוגיקה של cec_scraper)
        sys.path.insert(0, str(ROOT / "scraper"))
        import cec_scraper  # noqa: E402
        conn = sqlite3.connect(db_path)
        conn.executescript(cec_scraper.SCHEMA)
        new, updated = cec_scraper.upsert(conn, items)
        print(f"חדשים: {new} | עודכנו: {updated}")

        # 3. PDF חסרים
        rows = conn.execute("SELECT reference_number, file_url FROM polls_meta "
                            "WHERE file_url IS NOT NULL AND (local_pdf IS NULL OR local_pdf='')").fetchall()
        if init and rows:
            # בריצה ראשונה: לנווט ל-PDF אחד בחלון גלוי כדי לעבור את אימות Cloudflare
            print("פותח PDF ראשון בחלון גלוי - אם מופיע 'יש לאמת שאינך רובוט', לחץ על התיבה.")
            page.goto(rows[0][1], timeout=120000)
            for _ in range(60):
                if "רק רגע" not in (page.title() or "") and "Just a moment" not in (page.title() or ""):
                    break
                time.sleep(2)
            page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2000)
        got, errs = 0, []
        for ref, url in rows:
            res = page.evaluate(FETCH_PDF_JS, url)
            if res.get("status") != 200:
                errs.append(f"{ref}: HTTP {res.get('status')}")
                continue
            data = base64.b64decode(res["b64"])
            if not data.startswith(b"%PDF"):
                errs.append(f"{ref}: not a PDF (Cloudflare?)")
                continue
            target = pdf_dir / f"cec_{ref}.pdf"
            target.write_bytes(data)
            conn.execute("UPDATE polls_meta SET local_pdf=?, pdf_sha256=? WHERE reference_number=?",
                         (str(target), hashlib.sha256(data).hexdigest(), ref))
            got += 1
            time.sleep(0.8)
        conn.execute("INSERT INTO scrape_log VALUES (datetime('now','localtime'),?,?,?,?,?)",
                     (len(items), new, updated, got, "\n".join(errs) or None))
        conn.commit()
        print(f"PDF הורדו: {got}")
        if errs:
            print("שגיאות:\n  " + "\n  ".join(errs), file=sys.stderr)
            ctx.close()
            return 1
        ctx.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--init", action="store_true", help="ריצה ראשונה בחלון גלוי (מעבר אימות Cloudflare)")
    ap.add_argument("--db", default=str(ROOT / "db" / "polls.sqlite"))
    ap.add_argument("--pdf-dir", default=str(ROOT / "data" / "pdfs"))
    ap.add_argument("--meta-out", default=str(ROOT / "data" / "cec_polls_meta.json"))
    a = ap.parse_args(argv)
    return run(a.init, Path(a.db), Path(a.pdf_dir), Path(a.meta_out))


if __name__ == "__main__":
    sys.exit(main())
