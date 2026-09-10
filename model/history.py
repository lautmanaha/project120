#!/usr/bin/env python3
"""
פרויקט 120 - יומן תחזיות: שורה לכל ריצה (תאריך, גושים, מפלגות, מספר סקרים) ב-model/output/history.jsonl.
משמש ל"מה השתנה השבוע" באתר. רשומה אחת לתאריך (הריצה האחרונה באותו יום מחליפה).

  python model/history.py            # מוסיף את הריצה הנוכחית (model/output/seats_summary.json + forecast.json)
  python model/history.py --from-git # משחזר את כל ההיסטוריה מה-commits של seats_summary.json (דורש git מלא)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "model" / "output"
HIST = OUT / "history.jsonl"


def entry(seats: dict, forecast: dict, n_polls: int | None = None) -> dict:
    return {
        "date": forecast["today"],
        "n_polls": n_polls,
        "blocs": {b["bloc"]: {"median": b["seats_median"], "mean": round(b["seats_mean"], 1), "p05": b["seats_p05"], "p95": b["seats_p95"],
                             "p_majority": round(b["p_majority"], 3)} for b in seats["blocs"]},
        "parties": {p["party"]: {"median": p["seats_median"], "mean": round(p["seats_mean"], 1), "p_threshold": round(p["p_threshold"], 3)}
                    for p in seats["parties"]},
        "scenarios": seats.get("scenarios", {}),
    }


def load() -> list[dict]:
    if not HIST.exists():
        return []
    return [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]


def save(rows: list[dict]) -> None:
    rows = sorted({r["date"]: r for r in rows}.values(), key=lambda r: r["date"])
    HIST.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def n_polls_now() -> int | None:
    try:
        import csv
        with open(ROOT / "model" / "polls_model.csv", encoding="utf-8") as f:
            return sum(1 for _ in csv.reader(f)) - 1
    except Exception:
        return None


def from_git() -> list[dict]:
    shas = subprocess.run(["git", "log", "--format=%H", "--reverse", "--", "model/output/seats_summary.json"],
                          cwd=ROOT, capture_output=True, text=True).stdout.split()
    rows = []
    for sha in shas:
        try:
            s = json.loads(subprocess.run(["git", "show", f"{sha}:model/output/seats_summary.json"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
            f = json.loads(subprocess.run(["git", "show", f"{sha}:model/output/forecast.json"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
            csv_txt = subprocess.run(["git", "show", f"{sha}:model/polls_model.csv"], cwd=ROOT, capture_output=True, text=True).stdout
            n = (csv_txt.count("\n") - 1) if csv_txt else None
            rows.append(entry(s, f, n))
        except Exception as ex:
            print("דילוג", sha[:7], ex)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-git", action="store_true")
    a = ap.parse_args(argv)
    rows = load()
    if a.from_git:
        rows += from_git()
    seats = json.loads((OUT / "seats_summary.json").read_text(encoding="utf-8"))
    forecast = json.loads((OUT / "forecast.json").read_text(encoding="utf-8"))
    rows.append(entry(seats, forecast, n_polls_now()))
    save(rows)
    rows = load()
    print(f"history: {len(rows)} רשומות, {rows[0]['date']} .. {rows[-1]['date']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
