#!/usr/bin/env python3
"""
פרויקט 120 - הריצה היומית (מיועדת ל-Task Scheduler / cron).

שלבים:
  1. משיכת רשומות חדשות + PDF מאתר ועדת הבחירות (דפדפן; נופל ל-requests אם Playwright לא מותקן).
  2. חילוץ תוצאות מכל PDF חדש באמצעות Claude (אם יש ANTHROPIC_API_KEY; אחרת - מסמן "ממתין").
  3. בנייה מחדש של הטבלאות המנורמלות והייצוא (CSV/Excel).
  4. כתיבת לוג ל-logs/daily_YYYY-MM-DD.log ושורת סיכום.

הרצה:  python scraper/daily_update.py
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
PY = sys.executable


def step(name: str, cmd: list[str], log) -> int:
    log.write(f"\n=== {name} === {dt.datetime.now():%H:%M:%S}\n")
    log.flush()
    r = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
    log.write(f"--- exit {r.returncode}\n")
    return r.returncode


def main() -> int:
    LOGS.mkdir(exist_ok=True)
    today = dt.date.today().isoformat()
    with open(LOGS / f"daily_{today}.log", "a", encoding="utf-8") as log:
        log.write(f"\n##### daily_update {dt.datetime.now():%Y-%m-%d %H:%M:%S} #####\n")
        try:
            import playwright  # noqa: F401
            rc = step("fetch (browser)", [PY, "scraper/browser_fetch.py"], log)
        except ImportError:
            rc = step("fetch (requests)", [PY, "scraper/cec_scraper.py"], log)
        rc2 = step("extract new PDFs", [PY, "scraper/extract_with_claude.py"], log)
        rc3 = step("rebuild db + exports", [PY, "db/build_db.py"], log)
        rc4 = step("export excel", [PY, "db/export_excel.py"], log)
        rc5 = step("model", [PY, "model/build_input.py"], log) or step("anchor", [PY, "model/anchor.py"], log) or step("model fit", [PY, "model/run_model.py", "--chains", "4", "--industry-lean-json", "model/anchor_trusted.json", "--industry-lean-key", "combined"], log)
        rc6 = step("seats", [PY, "model/seats.py"], log) or step("site data", [PY, "site/build_site_data.py"], log) or step("site html", [PY, "site/build_site.py"], log)
        rc7 = 0
        if (ROOT / ".git").exists() and not any((rc5, rc6)):
            rc7 = step("publish (git push)", ["git", "add", "site/index.html", "site/data.json", "db/polls.sqlite", "data/extracted", "exports", "model/output/forecast.json", "model/output/seats_summary.json"], log) \
                or step("commit", ["git", "commit", "-m", f"daily update {today}", "--allow-empty"], log) or step("push", ["git", "push"], log)
        status = "OK" if not any((rc, rc2, rc3, rc4, rc5, rc6, rc7)) else f"WARN fetch={rc} extract={rc2} db={rc3} xlsx={rc4} model={rc5} site={rc6} publish={rc7}"
        log.write(f"\n##### done: {status}\n")
    print(status)
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
