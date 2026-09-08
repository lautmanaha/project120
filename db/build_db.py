#!/usr/bin/env python3
"""
פרויקט 120 - בניית מסד הנתונים המנורמל מתוך קובצי ה-JSON שחולצו מה-PDF.

קלט:  db/polls.sqlite (טבלת polls_meta מה-scraper) + data/extracted/cec_<ref>.json
פלט:  טבלאות pollsters, publishers, polls, poll_questions, poll_results ב-polls.sqlite
       + exports/polls_wide.csv (מוכן ל-kronikas), exports/polls_long.csv, exports/project120_polls.xlsx
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "polls.sqlite"
EXTRACTED = ROOT / "data" / "extracted"
EXPORTS = ROOT / "exports"

# --- מיפוי שמות קנוניים -----------------------------------------------------
# מפתח: תת-מחרוזת שמופיעה ב"עורך הסקר" (ברשומת הוועדה או ב-PDF) -> שם קנוני
POLLSTER_CANON = [
    ("רוזנר", "פרויקט המדגם (רוזנר)"),
    ("קנטאר", "קנטאר"), ("קאנטר", "קנטאר"),
    ("לזר", "לזר מחקרים"),
    ("מאגר מוחות", "מאגר מוחות"),
    ("דיירקט", "דיירקט פולס"),
    ("טאטיקה", "טאטיקה"),
    ("Next Data", "נקסט דאטה"), ("נקסט", "נקסט דאטה"), ("פילבר", "נקסט דאטה"),
    ("מדגם", "מדגם"),
    ("דיאלוג", "דיאלוג"),
]
PUBLISHER_CANON = [
    ("ערוץ 13", "חדשות 13"), ("חדשות 13", "חדשות 13"),
    ("חדשות 12", "חדשות 12"), ("ערוץ 12", "חדשות 12"),
    ("תאגיד", "כאן 11"), ("כאן", "כאן 11"),
    ("ישראל היום", "ישראל היום"),
    ("מעריב", "מעריב"),
    ("וואלה", "וואלה"),
    ("ערוץ 14", "ערוץ 14"), ("עכשיו 14", "ערוץ 14"),
    ("ערוץ 16", "ערוץ 16"),
    ("המזרח התיכון 24", "i24NEWS"), ("i24", "i24NEWS"),
    ("זמן ישראל", "זמן ישראל"),
    ("ידיעות", "ידיעות אחרונות / ynet"), ("ynet", "ידיעות אחרונות / ynet"),
    ("סרוגים", "סרוגים"),
]
# ערוצי הפרסום - סוג
PUBLISHER_TYPE = {
    "חדשות 13": "טלוויזיה", "חדשות 12": "טלוויזיה", "כאן 11": "טלוויזיה",
    "ערוץ 14": "טלוויזיה", "ערוץ 16": "טלוויזיה", "i24NEWS": "טלוויזיה",
    "ישראל היום": "עיתון", "מעריב": "עיתון", "ידיעות אחרונות / ynet": "עיתון",
    "וואלה": "אתר", "זמן ישראל": "אתר", "סרוגים": "אתר",
}
# מפלגות - סדר קבוע לקובץ הרחב (הסדר לפי ממוצע מנדטים בערך)
PARTIES = ["ישר", "הליכוד", "ביחד", "הדמוקרטים", "ישראל ביתנו", "יהדות התורה", "עוצמה יהודית",
           "ש\"ס", "הרשימה המשותפת", "רע\"ם", "הציונות הדתית", "עמך ישראל", "בית ציוני",
           "כחול לבן", "האחדות", "זהות", "הכלכלית החדשה", "הציבור החרדי", "מקום לכולנו",
           "מפלגת הקהל", "נעם", "ברית אחים", "עוז", "חופש כלכלי", "אחר"]

SCHEMA = """
DROP TABLE IF EXISTS poll_results;
DROP TABLE IF EXISTS poll_questions;
DROP TABLE IF EXISTS polls;
DROP TABLE IF EXISTS pollsters;
DROP TABLE IF EXISTS publishers;

CREATE TABLE pollsters (
    pollster_id   INTEGER PRIMARY KEY,
    name          TEXT UNIQUE,          -- שם קנוני
    aliases       TEXT                  -- כל הכתיבים שנתקלנו בהם, מופרדים ב-|
);
CREATE TABLE publishers (
    publisher_id  INTEGER PRIMARY KEY,
    name          TEXT UNIQUE,
    type          TEXT,                 -- טלוויזיה / עיתון / אתר
    aliases       TEXT
);
CREATE TABLE polls (
    reference_number   TEXT PRIMARY KEY REFERENCES polls_meta(reference_number),
    pollster_id        INTEGER REFERENCES pollsters(pollster_id),
    publisher_id       INTEGER REFERENCES publishers(publisher_id),
    pollster_as_written    TEXT,
    commissioner_as_written TEXT,
    fieldwork_start    TEXT,
    fieldwork_end      TEXT,
    method             TEXT,           -- internet / phone / mixed / unknown
    initial_sample     INTEGER,
    respondents        INTEGER,
    response_rate_pct  REAL,
    margin_error_pct   REAL,
    population         TEXT,
    has_main_question  INTEGER,        -- 1 אם יש שאלת הצבעה ראשית
    in_model           INTEGER,        -- 1 = נכנס למודל (כלל האוכלוסייה, לא כפול, יש תוצאות)
    exclude_reason     TEXT,
    extraction_notes   TEXT
);
CREATE TABLE poll_questions (
    question_id      INTEGER PRIMARY KEY,
    reference_number TEXT REFERENCES polls(reference_number),
    qid              INTEGER,
    type             TEXT,             -- main / scenario
    description      TEXT,
    weighted         INTEGER,
    undecided_pct    REAL,
    not_voting_pct   REAL,
    other_pct        REAL,
    blank_pct        REAL,
    seats_total      INTEGER,
    notes            TEXT
);
CREATE TABLE poll_results (
    question_id      INTEGER REFERENCES poll_questions(question_id),
    reference_number TEXT,
    party            TEXT,             -- שם קנוני
    party_as_written TEXT,
    seats            INTEGER,
    pct              REAL
);
CREATE INDEX idx_results_party ON poll_results(party);
CREATE INDEX idx_results_ref ON poll_results(reference_number);
"""


def canon(text: str | None, table: list[tuple[str, str]]) -> str | None:
    if not text:
        return None
    for needle, name in table:
        if needle.lower() in text.lower():
            return name
    return text.strip()


def main() -> int:
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    meta = {r[0]: r for r in conn.execute(
        "SELECT reference_number, survey_editor, survey_publisher, survey_date, publish_date FROM polls_meta")}

    pollster_ids: dict[str, int] = {}
    pollster_alias: dict[str, set] = {}
    publisher_ids: dict[str, int] = {}
    publisher_alias: dict[str, set] = {}

    def get_pollster(*names: str | None) -> int | None:
        c = None
        for n in names:
            c = canon(n, POLLSTER_CANON)
            if c:
                break
        if not c:
            return None
        if c not in pollster_ids:
            pollster_ids[c] = len(pollster_ids) + 1
            pollster_alias[c] = set()
        pollster_alias[c].update(n.strip() for n in names if n)
        return pollster_ids[c]

    def get_publisher(*names: str | None) -> int | None:
        c = None
        for n in names:
            c = canon(n, PUBLISHER_CANON)
            if c:
                break
        if not c:
            return None
        if c not in publisher_ids:
            publisher_ids[c] = len(publisher_ids) + 1
            publisher_alias[c] = set()
        publisher_alias[c].update(n.strip() for n in names if n)
        return publisher_ids[c]

    # כפילויות ידועות: 4036 הוגש מחדש כ-4048 (טור מנדטים מתוקן)
    superseded = {"4036": "הוגש מחדש כ-4048 עם טור מנדטים מתוקן"}

    seen_fingerprints: dict[tuple, str] = {}
    qid_counter = 0
    for f in sorted(EXTRACTED.glob("cec_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        ref = str(d["ref"])
        m = meta.get(ref)
        editor_cec = m[1] if m else None
        publisher_cec = m[2] if m else None
        pid = get_pollster(editor_cec, d.get("pollster_as_written"))
        pubid = get_publisher(publisher_cec, d.get("commissioner_as_written"))

        mains = [q for q in d["questions"] if q["type"] == "main"]
        has_main = int(bool(mains))
        exclude = None
        if ref in superseded:
            exclude = superseded[ref]
        elif not has_main:
            exclude = "אין שאלת הצבעה"
        else:
            pop = (d.get("population") or "")
            notes = (mains[0].get("notes") or "")
            sector_pop = ("מילואימ", "ימין בלבד", "מצביעי ימין", "reservist", "הזרם הדתי", "דתי-לאומי", "הדתי הלאומי",
                          "האוכלוסייה הערבית", "החברה הערבית", "המגזר הערבי", "ערביי ישראל", "Arab population")
            # שדה האוכלוסייה קובע; ההערות רק אם מצוין במפורש שהמדגם כולו מגזרי
            if any(k in pop for k in sector_pop) or any(k in notes for k in ("מילואימ", "reservists only")):
                exclude = "מדגם של תת-אוכלוסייה"
        # זיהוי כפילות לפי (סוקר, תאריכים, מנדטים)
        if mains and not exclude:
            fp = (pid, d["fieldwork_start"], d["fieldwork_end"],
                  tuple(sorted((r["party"], r["seats"]) for r in mains[0]["results"])))
            if fp in seen_fingerprints:
                exclude = f"כפול של {seen_fingerprints[fp]}"
            else:
                seen_fingerprints[fp] = ref

        conn.execute(
            """INSERT INTO polls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ref, pid, pubid, d.get("pollster_as_written"), d.get("commissioner_as_written"),
             d.get("fieldwork_start"), d.get("fieldwork_end"), d.get("method"),
             d.get("initial_sample"), d.get("respondents"), d.get("response_rate_pct"),
             d.get("margin_error_pct"), d.get("population"), has_main,
             int(exclude is None), exclude, d.get("extraction_notes")))
        for q in d["questions"]:
            qid_counter += 1
            conn.execute(
                "INSERT INTO poll_questions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (qid_counter, ref, q["qid"], q["type"], q.get("description"),
                 int(bool(q.get("weighted", True))), q.get("undecided_pct"), q.get("not_voting_pct"),
                 q.get("other_pct"), q.get("blank_pct"), q.get("seats_total"), q.get("notes")))
            for r in q["results"]:
                conn.execute("INSERT INTO poll_results VALUES (?,?,?,?,?,?)",
                             (qid_counter, ref, r["party"], r.get("party_as_written"),
                              r.get("seats"), r.get("pct")))

    for name, i in pollster_ids.items():
        conn.execute("INSERT INTO pollsters VALUES (?,?,?)", (i, name, " | ".join(sorted(pollster_alias[name]))))
    for name, i in publisher_ids.items():
        conn.execute("INSERT INTO publishers VALUES (?,?,?,?)",
                     (i, name, PUBLISHER_TYPE.get(name), " | ".join(sorted(publisher_alias[name]))))
    conn.commit()

    export(conn)
    n_polls = conn.execute("SELECT COUNT(*) FROM polls").fetchone()[0]
    n_model = conn.execute("SELECT COUNT(*) FROM polls WHERE in_model=1").fetchone()[0]
    print(f"polls: {n_polls} (במודל: {n_model}) | pollsters: {len(pollster_ids)} | publishers: {len(publisher_ids)}")
    for r in conn.execute("SELECT reference_number, exclude_reason FROM polls WHERE in_model=0"):
        print("  לא במודל:", *r)
    return 0


def export(conn: sqlite3.Connection) -> None:
    EXPORTS.mkdir(exist_ok=True)
    # --- long ---
    rows = conn.execute("""
        SELECT p.reference_number, ps.name, pb.name, p.fieldwork_start, p.fieldwork_end, p.respondents,
               p.method, q.type, q.qid, q.description, r.party, r.party_as_written, r.seats, r.pct,
               q.undecided_pct, p.in_model, m.publish_date
        FROM poll_results r JOIN poll_questions q ON q.question_id=r.question_id
        JOIN polls p ON p.reference_number=q.reference_number
        LEFT JOIN pollsters ps ON ps.pollster_id=p.pollster_id
        LEFT JOIN publishers pb ON pb.publisher_id=p.publisher_id
        LEFT JOIN polls_meta m ON m.reference_number=p.reference_number
        ORDER BY p.fieldwork_end, p.reference_number, q.qid, r.seats DESC""").fetchall()
    with open(EXPORTS / "polls_long.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "pollster", "publisher", "fieldwork_start", "fieldwork_end", "respondents", "method",
                    "question_type", "qid", "question", "party", "party_as_written", "seats", "pct",
                    "undecided_pct", "in_model", "cec_publish_date"])
        w.writerows(rows)

    # --- wide (kronikas-ready): main question, model polls only, seats + pct ---
    for measure in ("seats", "pct"):
        polls = conn.execute("""
            SELECT p.reference_number, p.fieldwork_end, ps.name, p.respondents, q.question_id, pb.name
            FROM polls p JOIN poll_questions q ON q.reference_number=p.reference_number AND q.type='main'
            LEFT JOIN pollsters ps ON ps.pollster_id=p.pollster_id
            LEFT JOIN publishers pb ON pb.publisher_id=p.publisher_id
            WHERE p.in_model=1 ORDER BY p.fieldwork_end, p.reference_number""").fetchall()
        with open(EXPORTS / f"polls_wide_{measure}.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "pollster", "sample_size", "ref", "publisher"] + PARTIES)
            for ref, date, pollster, n, qid, pub in polls:
                vals = dict(conn.execute(
                    f"SELECT party, {measure} FROM poll_results WHERE question_id=?", (qid,)).fetchall())
                w.writerow([date, pollster, n, ref, pub] + [vals.get(p, "") for p in PARTIES])


if __name__ == "__main__":
    sys.exit(main())
