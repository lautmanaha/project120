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
    # כיול רב-מערכתי (2019א-2022, דעיכה מעריכית; model/hist_calibration.py -> calibration_hist.json):
    # ממוצע = ההטיה הענפית המתמשכת, סטיית תקן = הפיזור האמפירי בין המערכות (ההטיה כהתפלגות, לא כנקודה).
    # משפחות -> מפלגות 2026: "ימין דתי" מתחלק בין הציונות הדתית ועוצמה יהודית לפי גודלן, "שמאל" -> הדמוקרטים,
    # "מרכז" -> ישר/ביחד/כחול לבן לפי גודלן. עמך ישראל: אין היסטוריה -> ללא ממוצע, סטיית תקן רחבה.
    hist_path = ROOT / "model" / "calibration_hist.json"
    if hist_path.exists():
        fam = json.loads(hist_path.read_text(encoding="utf-8"))["combined"]["families"]
        means = recent[parties].mean()
        groups = {"ימין דתי": ["הציונות הדתית", "עוצמה יהודית"], "שמאל": ["הדמוקרטים"], "מרכז": ["ישר", "ביחד", "כחול לבן"]}
        hist_mean, hist_sd = {}, {}
        for f, r in fam.items():
            members = groups.get(f, [f])
            members = [m for m in members if m in parties]
            tot = sum(float(means[m]) for m in members) or 1.0
            for m in members:
                share = float(means[m]) / tot
                hist_mean[m] = round(r["mean_pp"] * share, 2)
                hist_sd[m] = round(max(0.3, r["sd_pp"] * share), 2)
        for p in parties:
            if p not in hist_sd:
                hist_sd[p] = round(max(0.5, 0.25 * float(means[p])), 2)   # בלי היסטוריה: רחב
        out["hist_mean"] = hist_mean; out["hist_sd"] = hist_sd
        comb_hist = dict(hist_mean)
        for p, v in out["half"].items():
            comb_hist[p] = round(comb_hist.get(p, 0.0) + v, 2)
            # מחצית הפער היא הנחה, לא מדידה: היא נכנסת כממוצע עם סטיית תקן בגודלה (האמת בין הענף למכונים המהימנים)
            hist_sd[p] = round((hist_sd.get(p, 0.3) ** 2 + v ** 2) ** 0.5, 2)
        out["combined_hist"] = comb_hist
    (ROOT / "model" / "anchor_trusted.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("anchor half:", out["half"])

if __name__ == "__main__":
    main()
