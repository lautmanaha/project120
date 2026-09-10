# פרויקט 120 - מסד סקרי הבחירות לכנסת ה-26

מסד נתונים של כל סקרי הבחירות שפורסמו באתר ועדת הבחירות המרכזית (חובת דיווח לפי סעיף 16ה לחוק דרכי תעמולה),
וכלי שמושך מדי יום את הסקרים החדשים, מחלץ מהם את התוצאות ומעדכן את המסד.

מקור הנתונים: https://www.gov.il/he/Departments/DynamicCollectors/knesset_election_polls_26

## מבנה

```
project120/
  db/polls.sqlite            מסד הנתונים (SQLite)
  db/build_db.py             בניית הטבלאות המנורמלות + ייצוא CSV
  db/export_excel.py         ייצוא ל-Excel
  data/pdfs/cec_<ref>.pdf    קובצי הסקר המקוריים כפי שהוגשו לוועדה
  data/pages/                עמודי ה-PDF כתמונות
  data/extracted/cec_<ref>.json   התוצאות שחולצו מכל סקר (מבנה: data/EXTRACTION_SPEC.md)
  data/cec_polls_meta.json   רשומות הוועדה כפי שהתקבלו מה-API
  exports/                   polls_wide_seats.csv, polls_wide_pct.csv, polls_long.csv, project120_polls.xlsx
  scraper/cec_scraper.py     משיכת רשומות + PDF ב-requests (metadata תמיד עובד; PDF תלוי Cloudflare)
  scraper/browser_fetch.py   משיכה דרך דפדפן אמיתי (Playwright) - עוקף את אימות Cloudflare
  scraper/extract_with_claude.py   חילוץ תוצאות מ-PDF חדש באמצעות Claude
  scraper/daily_update.py    הריצה היומית: משיכה -> חילוץ -> בנייה -> ייצוא
  scraper/setup_windows_task.ps1   רישום משימה יומית ב-Windows
  logs/                      לוג לכל ריצה
```

## טבלאות ב-polls.sqlite

| טבלה | מה יש בה |
|---|---|
| `polls_meta` | הרשומה הגולמית של הוועדה: עורך הסקר, מזמין, מועדי ביצוע/העברה/פרסום, מס' אסמכתא, קובץ |
| `pollsters` | מכונים - שם קנוני + כל הכתיבים שנתקלנו בהם |
| `publishers` | ערוצי פרסום - שם קנוני, סוג (טלוויזיה/עיתון/אתר) |
| `polls` | סקר אחד לשורה: מכון, ערוץ, תאריכי שדה, שיטה, מדגם, משיבים, היענות, טעות דגימה, `in_model` |
| `poll_questions` | שאלת הצבעה אחת לשורה: ראשית (`main`) או תרחיש (`scenario`), % לא החליטו |
| `poll_results` | מפלגה אחת לשורה: שם קנוני, שם כפי שנכתב, מנדטים, אחוז |
| `scrape_log` | מה קרה בכל ריצה |

`in_model = 0` לסקרים שלא נכנסים למודל: הגשה כפולה, סקר ללא שאלת הצבעה, מדגם של תת-אוכלוסייה (למשל מילואימניקים בלבד). הסיבה ב-`exclude_reason`.

## שמות מפלגות קנוניים

ישר | הליכוד | ביחד | הדמוקרטים | ישראל ביתנו | יהדות התורה | עוצמה יהודית | ש"ס | הרשימה המשותפת | רע"ם | עמך ישראל | הציונות הדתית | זהות | בית ציוני | הציבור החרדי | הכלכלית החדשה | כחול לבן | האחדות | מפלגת הקהל | מקום לכולנו | ברית אחים | נעם | עוז | חופש כלכלי | אחר

הערות מיפוי: "חד"ש-תע"ל" (עם או בלי בל"ד) -> הרשימה המשותפת; בל"ד לבד -> אחר; מפלגה היפותטית של ארדן/אדלשטיין -> האחדות; מפלגה של עופר וינטר -> עמך ישראל. השם המקורי נשמר תמיד ב-`party_as_written`.

## התקנה (Windows, פעם אחת)

```powershell
pip install -r requirements.txt
playwright install chromium
python scraper\browser_fetch.py --init     # חלון גלוי: לעבור את אימות Cloudflare פעם אחת
setx ANTHROPIC_API_KEY "sk-ant-..."        # לחילוץ אוטומטי של PDF חדשים
.\scraper\setup_windows_task.ps1           # משימה יומית 09:30
```

## ריצה ידנית

```powershell
python scraper\daily_update.py             # הכל
python scraper\browser_fetch.py            # רק משיכה
python scraper\extract_with_claude.py      # רק חילוץ PDF חדשים
python db\build_db.py; python db\export_excel.py
```

## למודל (kronikas)

`exports/polls_wide_pct.csv` ו-`polls_wide_seats.csv` הם בפורמט שהמנוע מצפה לו: `date, pollster, sample_size` + עמודה למפלגה.
תאים ריקים = המפלגה לא הופיעה בסקר (לא אפס).

## מגבלות ידועות

- הסקרים מוגשים לוועדה בפורמטים שונים (טבלאות, סריקות, צילומי מסך). החילוץ נעשה בקריאה ממוחשבת של התמונות ואומת מול סכום 120 מנדטים; קבצים שנכשלו באימות מסומנים `needs_review` ב-JSON.
- חלק מהמכונים (רוזנר/חדשות 13) מפרסמים רק מנדטים ואחוזים גולמיים לפי מגזר - אצלם `pct` ריק והמגזרים בהערות.
- הוועדה מפרסמת "מועד ביצוע" כיום אחד; תאריכי השדה המדויקים נלקחו מה-PDF.

## קרדיט

מודל החיזוי מבוסס על [kronikas](https://github.com/vtisza/kronikas) (Viktor Tisza, Apache 2.0) - מנוע החיזוי של szazkilencvenkilenc.hu להונגריה.
ההתאמה לישראל, מסד הנתונים והבנייה: ד"ר אהרון לאוטמן.

## פרסום (DevOps)

הזרימה: המחשב של אהרון (משימה יומית 09:30) -> משיכה מהוועדה -> חילוץ -> מודל (4 שרשראות, ~15 דק') -> `site/index.html` -> `git push`
-> GitHub Actions (`.github/workflows/pages.yml`) מפרסם את `site/` ב-GitHub Pages -> הדומיין `project120.co.il` (CNAME).

הגדרה חד-פעמית:
1. ריפו ב-GitHub (ציבורי, בשם `project120`), `git init` בתיקייה הזו, `git remote add origin ...`, push ראשון.
2. Settings -> Pages -> Source: GitHub Actions. Settings -> Pages -> Custom domain: `project120.co.il` (הקובץ `site/CNAME` כבר קיים).
3. ב-DNS של lautman.org: רשומת CNAME `120` -> `<user>.github.io`. לסמן Enforce HTTPS אחרי שהאימות עובר.
4. במחשב: `git config user.name/email`, ו-credential helper (Git Credential Manager) כדי ש-push ירוץ ללא סיסמה מהמשימה היומית.

חלופה שקולה: Cloudflare Pages / Netlify מחוברים לאותו ריפו - אותו CNAME, אותו קובץ.

## כיול המודל (הטיה ענפית מוצהרת)

`model/anchor.py` מייצר בכל ריצה את `anchor_trusted.json` עם שלושה מפתחות:
- `cal2022` - טעויות הענף בשלושת השבועות האחרונים לפני בחירות 2022 (`model/calibrate_2022.py` על `data/k25/`), ממופות למפלגות 2026: ש"ס -2.0, הציונות הדתית/עוצמה -0.6, רע"ם/המשותפת -0.8, הדמוקרטים +2.0 (נק' אחוז; שלילי = הסקרים מפחיתים).
- `half` - מחצית הפער ב-21 הימים האחרונים בין המכונים המהימנים (נקסט דאטה, דיירקט פולס) לשאר, לכל מפלגה.
- `combined` - הסכום; זה מה שהריצה היומית מעבירה ל-`run_model.py --industry-lean-json ... --industry-lean-key combined`.
המספרים מופיעים באתר בחלק "איך זה עובד".


## עדכון אוטומטי בענן (GitHub Actions)

שירות חיצוני מעתיק כל PDF חדש מאתר הוועדה לתיקיית Google Drive ציבורית. ה-workflow `.github/workflows/update.yml`
בודק את התיקייה כל שעתיים (`scraper/drive_fetch.py`), מחלץ סקרים חדשים עם Claude, מריץ את המודל, בונה את האתר
בשתי השפות, עושה commit ופורס. פעם ביום (09:00 ישראל) ריצה מלאה גם בלי סקרים חדשים.

secrets (Settings -> Secrets and variables -> Actions): `ANTHROPIC_API_KEY` (חובה), `P120_GATE_CODE` (שער גישה מוקדמת; להסרה - למחוק את ה-secret).
ריצה ידנית: Actions -> Update forecast -> Run workflow.

### עדכון בזמן אמת (webhook)
השירות שמזהה סקר חדש יכול להפעיל את ה-workflow מיד, במקום לחכות לבדיקה הבאה:
```
POST https://api.github.com/repos/lautmanaha/project120/dispatches
Authorization: Bearer <fine-grained token: Repository permissions -> Contents: Read and write>
Accept: application/vnd.github+json
Content-Type: application/json
{"event_type": "new_poll",
 "client_payload": {"reference_number": "4133", "survey_editor": "מכון די אר איי", "survey_publisher": "ערוץ 13",
                    "survey_date": "2026-09-09", "publish_date": "2026-09-10", "file_name": "סקר בחירות מיום 9.9.2026 4133 - מכון די אר איי.pdf",
                    "pdf_url": "https://drive.google.com/file/d/<FILE_ID>/view", "notes": ""}}
```
`client_payload` אופציונלי: אם יש בו `reference_number` ו-`pdf_url` (קישור Drive או קישור ישיר ל-PDF) - הסקר יורד מיד מהקישור והמטא-דאטה נשמר;
אחרת (או אם ההורדה נכשלה) ה-workflow ממתין דקה, סורק את תיקיית ה-Drive ומושך משם. המודל רץ רק אם באמת יש סקר חדש. הבדיקה כל שעתיים נשארת כגיבוי.
