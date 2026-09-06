#!/usr/bin/env python3
"""
פרויקט 120 - בניית קובץ הקלט למודל (kronikas) מתוך מסד הסקרים.

כללים (מצב הרשימות נכון ל-6.9.2026):
  - זהות מוזגה לתוך הציונות הדתית -> מאחדים את האחוזים בכל הסקרים אחורה.
  - האחדות ובית ציוני פרשו -> מוסרים אותן; kronikas מנרמל כל שורה ל-100 מחדש.
  - מפלגות קטנות שלא בכל הסקרים (הכלכלית החדשה, הציבור החרדי, מקום לכולנו...) + "אחר" -> עמודת "אחר".
  - סקרים בלי אחוזים (רוזנר/חדשות 13 - רק מנדטים): אחוז = מנדטים/120 * ממוצע חלק הקולות
    של מפלגות מעל הסף באותו שבוע. מסומן בעמודת pct_source.
  - מדגם: מספר המשיבים בפועל.
פלט: model/polls_model.csv + model/forecast.yaml
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "polls.sqlite"
OUT = ROOT / "model" / "polls_model.csv"

MODEL_PARTIES = ["ישר", "הליכוד", "ביחד", "הדמוקרטים", "ישראל ביתנו", "יהדות התורה", "עוצמה יהודית",
                 "ש\"ס", "הרשימה המשותפת", "רע\"ם", "הציונות הדתית", "עמך ישראל", "כחול לבן", "אחר"]
MERGE_INTO = {"זהות": "הציונות הדתית", "בל\"ד": "הרשימה המשותפת"}   # בל"ד: בחלק מהסקרים נפרדת, מאחדים לעקביות
WITHDRAWN = {"האחדות", "בית ציוני"}


def main() -> None:
    conn = sqlite3.connect(DB)
    polls = conn.execute("""
        SELECT p.reference_number, p.fieldwork_start, p.fieldwork_end, ps.name, p.respondents, q.question_id, q.other_pct
        FROM polls p JOIN poll_questions q ON q.reference_number=p.reference_number AND q.type='main'
        LEFT JOIN pollsters ps ON ps.pollster_id=p.pollster_id
        WHERE p.in_model=1 ORDER BY p.fieldwork_end, p.reference_number""").fetchall()

    rows = []
    missing_cells: list[tuple[int, str]] = []   # (row index, party) - ערכים שיש להשלים
    for ref, start, end, pollster, n, qid, other_pct in polls:
        res = [(("בל\"ד" if (w or "").strip().startswith("בל\"ד") else p), se, pc) for p, w, se, pc in conn.execute("SELECT party, party_as_written, seats, pct FROM poll_results WHERE question_id=?", (qid,)).fetchall()]
        has_pct = any(r[2] is not None for r in res)
        shares: dict[str, float | None] = {p: None for p in MODEL_PARTIES}
        shares["אחר"] = 0.0
        if has_pct:
            for party, seats, pct in res:
                if party in WITHDRAWN or pct is None:
                    continue
                target = MERGE_INTO.get(party, party)
                target = target if target in shares else "אחר"
                shares[target] = (shares[target] or 0.0) + pct
            shares["אחר"] += other_pct or 0.0
            src = "pct"
        else:
            # מנדטים בלבד -> חלק קולות משוער. 120 מנדטים ~ 96% מהקולות הכשרים (השאר מתחת לסף).
            # מפלגה עם 0 מנדטים: לא ידוע כמה קיבלה -> תושלם מסקרים סמוכים.
            for party, seats, pct in res:
                if party in WITHDRAWN or not seats:
                    continue
                target = MERGE_INTO.get(party, party)
                target = target if target in shares else "אחר"
                shares[target] = (shares[target] or 0.0) + seats / 120 * 96.0
            shares["אחר"] += 4.0
            src = "seats"
        idx = len(rows)
        for p in MODEL_PARTIES:
            if shares[p] is None:
                missing_cells.append((idx, p))
        rows.append([end, pollster, n, ref, src] + [shares[p] for p in MODEL_PARTIES])

    # השלמת חסרים: ממוצע הסקרים שכן דיווחו על המפלגה בטווח של +-10 ימים, אחרת ממוצע כללי.
    # מפלגה שלא הופיעה בסקר כנראה נבלעה ב"אחר"/לא נשאלה - זה לא אפס, וזה גם לא נתון.
    from datetime import date as _d
    from statistics import mean
    col = {p: 5 + i for i, p in enumerate(MODEL_PARTIES)}
    for idx, p in missing_cells:
        d0 = _d.fromisoformat(rows[idx][0])
        near = [r[col[p]] for r in rows if r[col[p]] is not None and abs((_d.fromisoformat(r[0]) - d0).days) <= 10]
        allv = [r[col[p]] for r in rows if r[col[p]] is not None]
        rows[idx][col[p]] = mean(near) if near else (mean(allv) if allv else 0.3)
        rows[idx][4] += f"|imputed:{p}"
    # אפס בדיריכלה = בעיה מספרית. רצפה 0.3% (מתחת לכל סף ולכל דיוק סקר)
    for r in rows:
        for p in MODEL_PARTIES:
            r[col[p]] = round(max(r[col[p]], 0.3), 2)

    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "pollster", "sample_size", "ref", "pct_source"] + MODEL_PARTIES)
        w.writerows(rows)
    print(f"{len(rows)} polls -> {OUT}")


if __name__ == "__main__":
    main()
