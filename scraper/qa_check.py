#!/usr/bin/env python3
"""
פרויקט 120 - בקרת איכות אוטומטית לסקר שחולץ, לפני שהוא נכנס למודל ("הסגר").

לכל סקר חדש (JSON ב-data/extracted שטרם נבדק) מורצות בדיקות דטרמיניסטיות, ואופציונלית "מבקר" (Claude)
שמשווה את החילוץ לתמונת העמוד. סקר עם דגל נכנס להסגר: נשמר ב-DB אבל לא במודל, עד אישור אדם.

  db/quarantine.json:
    {"checked": [refs שנבדקו], "polls": {ref: {"status": pending|approved|rejected, "flags": [...], "review": {...}, ...}}}

הרצה:
  python scraper/qa_check.py                 # בדיקת כל הסקרים שטרם נבדקו
  python scraper/qa_check.py --refs 4135     # סקרים ספציפיים (בדיקה מחדש)
  python scraper/qa_check.py --review        # גם מבקר Claude (דורש ANTHROPIC_API_KEY)
  python scraper/qa_check.py --approve 4135 [--note "..."]   /   --reject 4135 [--note "..."]
מדפיס בסוף: QUARANTINE=<מספר סקרים חדשים בהסגר>   וכותב qa_report.md (גוף ה-Issue) כשיש כאלה.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "db"))
sys.path.insert(0, str(ROOT / "scraper"))
from build_db import POLLSTER_CANON, canon, fix_party  # noqa: E402

EXTRACTED = ROOT / "data" / "extracted"
DB = ROOT / "db" / "polls.sqlite"
QFILE = ROOT / "db" / "quarantine.json"
MODEL_CSV = ROOT / "model" / "polls_model.csv"
REPORT = ROOT / "qa_report.md"

# מפלגות שחסרונן בסקר ארצי הוא כמעט בוודאות טעות חילוץ (המודל היה "ממציא" להן ערך)
MAJOR = ["ישר", "הליכוד", "ביחד", "הדמוקרטים", "ישראל ביתנו", "יהדות התורה", "עוצמה יהודית", "ש\"ס",
         "הרשימה המשותפת", "רע\"ם", "הציונות הדתית"]
OTHER_MAX_PCT = 3.0      # שורה שמופתה ל"אחר" עם יותר מזה = כנראה מפלגה אמיתית שלא זוהתה
OUTLIER_PTS = 5.0        # סטייה מהסקרים הקודמים של אותו מכון (או 7 מהממוצע הכללי למכון חדש) שמדליקה דגל
SMALL_KNOWN = ("בל\"ד", "בלד", "נעם", "הציבור החרדי", "הכלכלית", "יסודות", "ישראל תחילה", "אל הדגל")   # מפלגות קטנות אמיתיות - "אחר" לגיטימי


def load_q() -> dict:
    if QFILE.exists():
        return json.loads(QFILE.read_text(encoding="utf-8"))
    return {"checked": [], "polls": {}}


def save_q(q: dict) -> None:
    QFILE.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")


def recent_means(exclude_ref: str, pollster: str | None = None, n: int = 10) -> tuple[dict[str, float], bool]:
    """ממוצע הסקרים האחרונים במודל (בלי הסקר הנבדק): של אותו מכון אם יש לו, אחרת של כולם. מחזיר (ממוצעים, האם של המכון)."""
    import pandas as pd
    if not MODEL_CSV.exists():
        return {}, False
    df = pd.read_csv(MODEL_CSV)
    df = df[df["ref"].astype(str) != str(exclude_ref)]
    own = df[df["pollster"] == pollster].tail(3) if pollster else df.iloc[0:0]
    use, is_own = (own, True) if len(own) >= 1 else (df.tail(n), False)
    if use.empty:
        return {}, False
    parties = list(use.columns[5:])
    vals = use[parties].div(use[parties].sum(axis=1), axis=0) * 100
    return {p: float(vals[p].mean()) for p in parties}, is_own


def check_one(ref: str, d: dict, conn: sqlite3.Connection) -> list[str]:
    flags: list[str] = []
    # סקר ש-build_db כבר מחריג (מגזרי, כפול, הוגש מחדש, בלי שאלת הצבעה) - לא נכנס למודל ממילא, אין מה להסגיר
    ex = conn.execute("SELECT exclude_reason FROM polls WHERE reference_number=?", (ref,)).fetchone()
    if ex and ex[0] and not ex[0].startswith(("ממתין", "נדחה")):
        return []
    mains = [q for q in d.get("questions", []) if q.get("type") == "main"]
    if not mains:
        return ["אין שאלת הצבעה ראשית"]
    m = mains[0]
    rows = [dict(r, party=fix_party(r.get("party_as_written"), r.get("party"))) for r in m["results"]]

    # 1. מכון לא מוכר (אין לו סקר קודם במאגר)
    row = conn.execute("SELECT ps.name FROM polls p JOIN pollsters ps ON ps.pollster_id=p.pollster_id WHERE p.reference_number=?", (ref,)).fetchone()
    name = row[0] if row else canon(d.get("pollster_as_written"), POLLSTER_CANON)
    prev = conn.execute("""SELECT COUNT(*) FROM polls p JOIN pollsters ps ON ps.pollster_id=p.pollster_id
                           WHERE ps.name=? AND p.reference_number<>?""", (name, ref)).fetchone()[0]
    if not prev:
        flags.append(f"מכון חדש במאגר: {name} (אין סקר קודם - לבדוק שהשם עקבי ושזה מכון אמיתי)")

    # 2. "אחר" משמעותי - כנראה מפלגה שלא זוהתה
    for r in rows:
        w = r.get("party_as_written") or ""
        if r["party"] == "אחר" and not any(k in w for k in SMALL_KNOWN) and ((r.get("pct") or 0) >= OTHER_MAX_PCT or (r.get("seats") or 0) >= 3):
            flags.append(f"מופה ל'אחר' עם {r.get('pct')}% / {r.get('seats')} מנדטים: \"{r.get('party_as_written')}\"")

    # 3. מפלגה גדולה חסרה
    present = {r["party"] for r in rows}
    written_all = " ".join((r.get("party_as_written") or "") for r in rows)
    missing = [p for p in MAJOR if p not in present and p not in written_all]   # רע"ם בתוך רשימה מאוחדת = לא חסרה
    if missing:
        flags.append("מפלגות חסרות בסקר ארצי (היו מקבלות ערך מוערך): " + ", ".join(missing))

    # 4. מפלגה מופיעה פעמיים
    seen: dict[str, int] = {}
    for r in rows:
        if r["party"] != "אחר":
            seen[r["party"]] = seen.get(r["party"], 0) + 1
    for p, k in seen.items():
        if k > 1:
            flags.append(f"{p} מופיעה {k} פעמים")

    # 5. סכומים
    seats = [r.get("seats") for r in rows if r.get("seats") is not None]
    if seats and not 118 <= sum(seats) <= 120:
        flags.append(f"סכום מנדטים {sum(seats)} (צפוי 120)")
    pcts = [r.get("pct") for r in rows if r.get("pct") is not None]
    if pcts and not 85 <= sum(pcts) <= 102:
        flags.append(f"סכום אחוזים {sum(pcts):.1f} (צפוי ~100)")
    if d.get("needs_review"):
        flags.append("החילוץ נכשל באימות (needs_review)")

    # 6. כפילות רכה: סקר אחר עם אותם תאריכי שדה ומספרים כמעט זהים (גם אם שם המכון שונה)
    mine = {r["party"]: r.get("pct") for r in rows if r.get("pct") is not None and r["party"] != "אחר"}
    for other in conn.execute("""SELECT reference_number, exclude_reason FROM polls WHERE reference_number<>? AND fieldwork_start=? AND fieldwork_end=?""",
                              (ref, d.get("fieldwork_start"), d.get("fieldwork_end"))):
        oref = other[0]
        if other[1] and ref in other[1]:      # השני כבר מסומן ככפול/הוגש-מחדש של זה - הוכרע
            continue
        theirs = dict(conn.execute("""SELECT r.party, r.pct FROM poll_results r JOIN poll_questions q ON q.question_id=r.question_id
                                      WHERE r.reference_number=? AND q.type='main' AND r.pct IS NOT NULL""", (oref,)).fetchall())
        common = [p for p in mine if p in theirs]
        if oref < ref and len(common) >= 6 and sum(abs(mine[p] - theirs[p]) <= 0.3 for p in common) / len(common) >= 0.8:
            flags.append(f"כמעט זהה לסקר {oref} (אותם תאריכי שדה, אותם מספרים) - כפילות/הגשה חוזרת?")

    # 7. חריג מול הממוצע האחרון
    means, own = recent_means(ref, name)
    if means and mine:
        tot = sum(mine.values()) or 1
        lim = OUTLIER_PTS if own else OUTLIER_PTS + 2
        for p, v in mine.items():
            if p in means and abs(v / tot * 100 - means[p]) > lim:
                flags.append(f"חריג: {p} {v:.1f}% מול {'הסקרים הקודמים של המכון' if own else 'הממוצע הכללי'} {means[p]:.1f}% (לא בהכרח שגיאה)")
    return flags


def review_with_claude(ref: str, d: dict) -> dict:
    """מבקר עצמאי: מקבל את תמונות העמודים + מה שחולץ, ומחפש אי-התאמות. מחזיר {"ok": bool, "issues": [...]}."""
    import anthropic
    from extract_with_claude import MODEL, PDF_DIR, _png_b64, render_pages
    mains = [q for q in d.get("questions", []) if q.get("type") == "main"]
    if not mains:
        return {"ok": True, "issues": []}
    rows = [{"as_written": r.get("party_as_written"), "mapped_to": fix_party(r.get("party_as_written"), r.get("party")),
             "seats": r.get("seats"), "pct": r.get("pct")} for r in mains[0]["results"]]
    pages = render_pages(PDF_DIR / f"cec_{ref}.pdf", ref)
    content = [{"type": "text", "text":
        "You are auditing a data extraction from an Israeli election poll (PDF pages attached). "
        "Below is the extracted main vote-intention table: each row = the party name as printed, the canonical party it was "
        "mapped to, seats, percent. Canonical parties: הליכוד, ישר, ביחד, הדמוקרטים, ישראל ביתנו, יהדות התורה, עוצמה יהודית, "
        "ש\"ס (=התאחדות הספרדים שומרי תורה), הציונות הדתית, הרשימה המשותפת (=חד\"ש-תע\"ל[-בל\"ד]), רע\"ם (=הרשימה הערבית המאוחדת), "
        "עמך ישראל, כחול לבן (=המחנה הממלכתי / בני גנץ), בית ציוני, נעם, הציבור החרדי, הכלכלית החדשה, אחר.\n"
        "Check against the images: (1) every party row in the printed table appears in the extraction, (2) each mapping is correct, "
        "(3) seats and percent match the printed numbers, (4) the extracted table is the main national vote-intention question, "
        "not a sub-sample or a scenario question. Ignore rounding and party-name typos.\n"
        f"Extracted rows:\n{json.dumps(rows, ensure_ascii=False, indent=0)}\n\n"
        "Reply ONLY with JSON: {\"ok\": true|false, \"issues\": [\"short Hebrew description of each real discrepancy\"]}. "
        "Empty issues list if everything matches."}]
    for i, p in enumerate(pages[:4]):
        content.append({"type": "text", "text": f"--- page {i + 1} ---"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _png_b64(p)}})
    client = anthropic.Anthropic()
    resp = client.messages.create(model=MODEL, max_tokens=1500, messages=[{"role": "user", "content": content}])
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        out = json.loads(text)
        return {"ok": bool(out.get("ok", True)), "issues": [str(x) for x in out.get("issues", [])][:10]}
    except json.JSONDecodeError:
        return {"ok": False, "issues": ["המבקר החזיר תשובה לא תקינה: " + text[:200]]}


def write_report(q: dict, refs: list[str], conn: sqlite3.Connection) -> None:
    parts = []
    for ref in refs:
        e = q["polls"][ref]
        parts.append(f"## סקר {ref} - {e.get('pollster') or ''} ({e.get('fieldwork') or ''})\n")
        parts.append("**דגלים:**\n" + "\n".join(f"- {f}" for f in e["flags"]) + "\n")
        rv = e.get("review")
        if rv:
            parts.append("**מבקר (Claude):** " + ("לא נמצאו אי-התאמות" if rv.get("ok") and not rv.get("issues") else
                         "\n".join(f"- {x}" for x in rv.get("issues", []))) + "\n")
        parts.append(f"קובץ: [data/pdfs/cec_{ref}.pdf](../blob/main/data/pdfs/cec_{ref}.pdf) | "
                     f"חילוץ: [data/extracted/cec_{ref}.json](../blob/main/data/extracted/cec_{ref}.json)\n")
    parts.append("\n---\nהסקר שמור במאגר אבל **לא נכנס למודל** עד אישור.\n"
                 "לאישור - תגובה עם המילה **אישור** (או approve). לדחייה - **דחייה** (או reject). "
                 "אפשר להוסיף הערה אחרי המילה.\n")
    REPORT.write_text("\n".join(parts), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", nargs="*", help="לבדוק סקרים ספציפיים (גם אם כבר נבדקו)")
    ap.add_argument("--review", action="store_true", help="גם מבקר Claude (אם יש ANTHROPIC_API_KEY)")
    ap.add_argument("--approve", help="לאשר סקר בהסגר")
    ap.add_argument("--reject", help="לדחות סקר בהסגר")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    q = load_q()

    if a.approve or a.reject:
        ref = a.approve or a.reject
        e = q["polls"].setdefault(ref, {"flags": []})
        e["status"] = "approved" if a.approve else "rejected"
        e["decided"] = dt.datetime.now().isoformat(timespec="seconds")
        e["note"] = a.note
        save_q(q)
        print(f"{ref}: {e['status']} {a.note}")
        return 0

    conn = sqlite3.connect(DB)
    refs = a.refs or sorted(p.stem.split("_", 1)[1] for p in EXTRACTED.glob("cec_*.json")
                            if p.stem.split("_", 1)[1] not in q["checked"])
    new_pending = []
    for ref in refs:
        f = EXTRACTED / f"cec_{ref}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        flags = check_one(ref, d, conn)
        review = None
        # המבקר (Claude) הוא חוות דעת שנייה לאדם שמאשר - לא שופט: הוא רץ רק על סקר שכבר סומן, וממצאיו נכנסים ל-Issue בלבד.
        # (בניסיון הראשון הוא סימן 39 מ-64 סקרים על דקדוקי מיפוי של רשימות קטנות - לא מספיק מדויק כדי להחריג לבד)
        if flags and a.review and os.environ.get("ANTHROPIC_API_KEY"):
            try:
                review = review_with_claude(ref, d)
            except Exception as ex:  # המבקר הוא תוספת; כשל שלו לא עוצר את הצינור
                review = {"ok": True, "issues": [f"המבקר לא רץ: {ex}"]}
        if ref not in q["checked"]:
            q["checked"].append(ref)
        if flags:
            prev = q["polls"].get(ref, {})
            if prev.get("status") in ("approved", "rejected"):
                print(f"{ref}: דגלים ({len(flags)}) - כבר הוכרע: {prev['status']}"); continue
            q["polls"][ref] = {"status": "pending", "flags": flags, "review": review,
                               "pollster": canon(d.get("pollster_as_written"), POLLSTER_CANON),
                               "fieldwork": f"{d.get('fieldwork_start')}..{d.get('fieldwork_end')}",
                               "created": dt.datetime.now().isoformat(timespec="seconds")}
            new_pending.append(ref)
            print(f"{ref}: הסגר - " + " | ".join(flags))
        else:
            print(f"{ref}: תקין")
    save_q(q)
    if new_pending:
        write_report(q, new_pending, conn)
    print(f"QUARANTINE={len(new_pending)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
