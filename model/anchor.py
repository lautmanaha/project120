#!/usr/bin/env python3
"""
פרויקט 120 - חישוב "ההטיה הענפית המוצהרת": הפער בין קבוצת המכונים המהימנים (לפי הרקורד ההיסטורי)
לשאר הענף, ב-3 השבועות האחרונים. ברירת המחדל: "באמצע" - מחצית הפער.
פלט: model/anchor_trusted.json  {"full": {...}, "half": {...}}  (ערך חיובי = הסקרים מפריזים במפלגה)
"""
import json, sys
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TRUSTED = ["נקסט דאטה", "דיירקט פולס"]
WINDOW_DAYS = 21

def main():
    df = pd.read_csv(ROOT / "model" / "polls_model.csv"); parties = list(df.columns[5:])
    df[parties] = df[parties].div(df[parties].sum(axis=1), axis=0) * 100
    cutoff = (pd.to_datetime(df.date).max() - timedelta(days=WINDOW_DAYS)).date().isoformat()
    recent = df[df.date >= cutoff]
    t = recent[recent.pollster.isin(TRUSTED)]; o = recent[~recent.pollster.isin(TRUSTED)]
    gap = (t[parties].mean() - o[parties].mean())
    out = {"trusted": TRUSTED, "window_from": cutoff, "n_trusted": int(len(t)), "n_others": int(len(o)),
           "gap_trusted_minus_others": {p: round(float(g), 2) for p, g in gap.items()},
           "full": {p: round(-float(g), 2) for p, g in gap.items() if abs(g) >= 0.3},
           "half": {p: round(-float(g) / 2, 2) for p, g in gap.items() if abs(g) >= 0.3}}
    # שילוב עם כיול 2022 (טעויות הענף בשלושת השבועות האחרונים לפני בחירות 2022)
    cal_path = ROOT / "model" / "industry_lean_2022.json"
    if cal_path.exists():
        cal = json.loads(cal_path.read_text(encoding="utf-8"))["cal2022"]
        combined = dict(cal)
        for p, v in out["half"].items(): combined[p] = round(combined.get(p, 0.0) + v, 2)
        out["cal2022"] = cal; out["combined"] = combined
    (ROOT / "model" / "anchor_trusted.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("anchor half:", out["half"])

if __name__ == "__main__":
    main()
