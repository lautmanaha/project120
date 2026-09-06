# Extraction spec - CEC poll PDFs -> JSON

For each poll `cec_<REF>` you are given:
- rendered page images: `data/pages/cec_<REF>_p<N>.png` (READ EVERY PAGE with the Read tool - many PDFs are scanned images and the text file is empty or garbled)
- text dump (may be reversed-Hebrew or empty): `data/text/cec_<REF>.txt` - use only as a cross-check for numbers.

Write ONE file: `data/extracted/cec_<REF>.json` with exactly this structure:

```json
{
  "ref": "4118",
  "pollster_as_written": "שמואל רוזנר עם חברת פאנל פרוייקט המדגם",
  "commissioner_as_written": "חדשות 13",
  "fieldwork_start": "2026-09-01",
  "fieldwork_end": "2026-09-02",
  "method": "mixed",                 // one of: "internet", "phone", "mixed", "unknown"
  "initial_sample": 7842,            // גודל מדגם התחלתי / מספר המתבקשים - null if absent
  "respondents": 1034,               // מספר המשיבים בפועל (the number the results are based on) - null if absent
  "response_rate_pct": 20.0,         // null if absent
  "margin_error_pct": 3.4,           // null if absent
  "population": "כלל האוכלוסייה הבוגרת 18+",
  "questions": [
    {
      "qid": 1,
      "type": "main",                // "main" = the standard "if elections were held today" question with all parties as they run now; "scenario" = hypothetical mergers/splits/new leaders
      "description": "אם הבחירות היו מתקיימות היום, לאיזו מפלגה היית מצביע",
      "weighted": true,              // false only if the table says the numbers are raw/unweighted
      "results": [
        {"party_as_written": "ישר! עם איזנקוט בראשות גדי איזנקוט", "party": "ישר", "seats": 24, "pct": 17.7},
        {"party_as_written": "הליכוד", "party": "הליכוד", "seats": 23, "pct": 16.7}
      ],
      "undecided_pct": 11.2,         // "לא החליטו"/"עדיין לא החלטתי" - null if absent
      "not_voting_pct": null,        // "לא מתכוון להצביע" - null if absent
      "other_pct": 1.4,              // "מפלגות אחרות" - null if absent
      "blank_pct": null,             // "פתק לבן" - null if absent
      "seats_total": 120,            // sum of seats you recorded - compute it; should be 120 for a full table
      "notes": ""                    // anything odd: e.g. "pct is raw per sector, only seats are national", "table gives seats only"
    }
  ],
  "extraction_notes": ""             // free text: pages that were unreadable, ambiguities, anything you had to guess
}
```

Rules:
1. `party` MUST be one of these canonical names (copy exactly), or `"אחר"` when nothing fits - then explain in notes:
   ישר | הליכוד | ביחד | הדמוקרטים | ישראל ביתנו | יהדות התורה | עוצמה יהודית | ש"ס | הרשימה המשותפת | רע"ם | עמך ישראל | הציונות הדתית | זהות | בית ציוני | הציבור החרדי | הכלכלית החדשה | כחול לבן | האחדות | מפלגת הקהל | מקום לכולנו | ברית אחים | נעם | עוז | חופש כלכלי | אחר
   Hints: "ישר! עם איזנקוט"/"ישר עם איזנקוט"/"איזנקוט" -> ישר. "ביחד בראשות בנט"/"בנט" -> ביחד. "הדמוקרטים - יאיר גולן" -> הדמוקרטים. "ליברמן" -> ישראל ביתנו. "בן גביר" -> עוצמה יהודית. "סמוטריץ'" -> הציונות הדתית. "פייגלין" -> זהות. "עופר וינטר" -> עמך ישראל. "המילואימניקים"/"טרופר" -> בית ציוני. "לייטנר" -> הציבור החרדי. "זליכה" -> הכלכלית החדשה. "גנץ" -> כחול לבן. "ארדן" -> האחדות. "חד"ש-תע"ל-בל"ד"/"המשותפת" -> הרשימה המשותפת. "מנסור עבאס" -> רע"ם.
   When a SCENARIO question presents a merged list (e.g. "הציונות הדתית + זהות"), put the merged label in `party_as_written`, set `party` to the larger component, and mention the merger in that question's `notes`.
2. `seats`: integer, 0 when the party is shown as below threshold / "0" / "-". null only if the table has no seat column at all.
3. `pct`: the percentage shown for that party in the national/total column, as a number (17.7 not "17.7%"). If the table has several pct columns (e.g. per sector, raw vs weighted), use the national weighted one if present; otherwise the national raw one and say so in `notes`. null if there is no pct column.
4. Do NOT invent rows. If a party is not in the table, it is absent.
5. Questions that are NOT vote-intention (approval, suitability for PM, "who won the debate", bloc preferences, issue questions) are NOT extracted - ignore them entirely.
6. The "main" question is the one asked as parties currently stand. If the PDF only has scenario questions, mark the closest one as "main" and explain in notes. If there are two main-looking tables (e.g. one for "all respondents" and one "including leaners"), take the headline one as main and put the other as a scenario with description.
7. Dates: YYYY-MM-DD. If only one date is given, start = end. Israeli dates are D.M.YYYY. If year is missing, it is 2026.
8. Use null, never empty strings, for missing numbers.
9. Output must be valid JSON, UTF-8. Write it with the Write tool.

Work carefully - these numbers feed a statistical model. Double-check every seats figure against the image; the seat column must sum to 120 for a full table.
