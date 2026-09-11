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


def notify_issues(log) -> None:
    """Issue ב-GitHub לכל סקר בהסגר שעדיין אין לו Issue פתוח (gh CLI; ב-Actions יש GH_TOKEN)."""
    import json
    q = json.loads((ROOT / "db" / "quarantine.json").read_text(encoding="utf-8"))
    report = (ROOT / "qa_report.md").read_text(encoding="utf-8") if (ROOT / "qa_report.md").exists() else ""
    for ref, e in q.get("polls", {}).items():
        if e.get("status") != "pending" or e.get("issue"):
            continue
        title = f"[QA] סקר {ref} - {e.get('pollster') or ''} - ממתין לאישור"
        body = report if f"## סקר {ref}" in report else "\n".join(f"- {f}" for f in e.get("flags", []))
        r = subprocess.run(["gh", "issue", "create", "--title", title, "--body", body, "--label", "qa"],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode and "not found" in (r.stderr or ""):     # אין תווית qa עדיין
            r = subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], cwd=ROOT, capture_output=True, text=True)
        log.write(f"\n=== issue {ref} ===\n{r.stdout}{r.stderr}--- exit {r.returncode}\n")
        if r.returncode == 0:
            e["issue"] = r.stdout.strip()
    (ROOT / "db" / "quarantine.json").write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["cec", "drive"], default="cec", help="cec = אתר הוועדה (דפדפן, מהמחשב); drive = תיקיית Google Drive (שרת)")
    ap.add_argument("--no-push", action="store_true", help="בלי git (ב-GitHub Actions ה-workflow עושה commit)")
    ap.add_argument("--skip-model-if-no-new", action="store_true", help="אם אין סקרים חדשים - לא להריץ את המודל")
    ap.add_argument("--notify-issues", action="store_true", help="לפתוח GitHub Issue לכל סקר שנכנס להסגר (דורש gh + GH_TOKEN)")
    a = ap.parse_args(argv)
    LOGS.mkdir(exist_ok=True)
    today = dt.date.today().isoformat()
    with open(LOGS / f"daily_{today}.log", "a", encoding="utf-8") as log:
        log.write(f"\n##### daily_update {dt.datetime.now():%Y-%m-%d %H:%M:%S} #####\n")
        n_new = None
        if a.source == "drive":
            import io
            buf = io.StringIO()
            cmd = [PY, "scraper/drive_fetch.py"] + (["--payload", "payload.json"] if (ROOT / "payload.json").exists() else [])
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            log.write(f"\n=== fetch (drive) ===\n{r.stdout}{r.stderr}--- exit {r.returncode}\n"); rc = r.returncode
            m = [l for l in r.stdout.splitlines() if l.startswith("NEW=")]
            n_new = int(m[-1].split("=")[1]) if m else None
            print(f"new polls: {n_new}")
        else:
            try:
                import playwright  # noqa: F401
                rc = step("fetch (browser)", [PY, "scraper/browser_fetch.py"], log)
            except ImportError:
                rc = step("fetch (requests)", [PY, "scraper/cec_scraper.py"], log)
        if a.skip_model_if_no_new and n_new == 0:
            log.write("\n##### no new polls - skipping model\n"); print("NO_NEW"); return 0
        rc2 = step("extract new PDFs", [PY, "scraper/extract_with_claude.py"], log)
        step("db (pre-QA)", [PY, "db/build_db.py"], log)
        # בקרת איכות: סקרים חדשים עם דגלים נכנסים להסגר (db/quarantine.json) ולא למודל עד אישור
        r = subprocess.run([PY, "scraper/qa_check.py", "--review"], cwd=ROOT, capture_output=True, text=True)
        log.write(f"\n=== QA ===\n{r.stdout}{r.stderr}--- exit {r.returncode}\n")
        m = [l for l in r.stdout.splitlines() if l.startswith("QUARANTINE=")]
        n_q = int(m[-1].split("=")[1]) if m else 0
        if n_q:
            print(f"quarantined: {n_q}")
            if a.notify_issues:
                notify_issues(log)
        rc3 = step("rebuild db + exports", [PY, "db/build_db.py"], log)
        rc4 = step("export excel", [PY, "db/export_excel.py"], log)
        rc5 = step("model", [PY, "model/build_input.py"], log) or step("anchor", [PY, "model/anchor.py"], log) or step("model fit", [PY, "model/run_model.py", "--chains", "4", "--draws", "1500", "--industry-lean-json", "model/anchor_trusted.json", "--industry-lean-key", "combined"], log)
        rc6 = step("seats", [PY, "model/seats.py"], log) or step("history", [PY, "model/history.py"], log) or step("site data", [PY, "site/build_site_data.py"], log) or step("site html", [PY, "site/build_site.py"], log) or step("gate", [PY, "site/gate.py"], log)
        rc7 = 0
        if (ROOT / ".git").exists() and not a.no_push and not any((rc5, rc6)):
            rc7 = step("publish (git push)", ["git", "add", "site/index.html", "site/en/index.html", "site/data.json", "db/polls.sqlite", "data/extracted", "exports", "model/output/forecast.json", "model/output/seats_summary.json"], log) \
                or step("commit", ["git", "commit", "-m", f"daily update {today}", "--allow-empty"], log) or step("push", ["git", "push"], log)
        status = "OK" if not any((rc, rc2, rc3, rc4, rc5, rc6, rc7)) else f"WARN fetch={rc} extract={rc2} db={rc3} xlsx={rc4} model={rc5} site={rc6} publish={rc7}"
        log.write(f"\n##### done: {status}\n")
    print(status)
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
