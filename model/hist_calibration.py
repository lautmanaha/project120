#!/usr/bin/env python3
"""פרויקט 120 - טעויות הענף בארבע מערכות הבחירות 2019-2021 (מקור: טבלאות הסקרים בוויקיפדיה, data/hist/wiki_*.json),
באותה שיטה כמו כיול 2022: ממוצע הסקרים ב-3 השבועות האחרונים מול התוצאה, במנדטים -> נקודות אחוז (מנדט ~ 0.8 נק')."""
import json, re, sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
ROOT = Path(__file__).resolve().parent.parent
MON = {m: i for i, m in enumerate(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
# מיפוי מפלגות היסטוריות למשפחות של 2026
FAMILY = {
    "Likud": "הליכוד", "Shas": 'ש"ס', "UTJ": "יהדות התורה", "Yisrael Beiteinu": "ישראל ביתנו", "YB": "ישראל ביתנו",
    "Joint List": "הרשימה המשותפת", "Hadash –Ta'al": "הרשימה המשותפת", "Ra'am": 'רע"ם', "Ra'am –Balad": 'רע"ם',
    "Yamina": "ימין דתי", "New Right": "ימין דתי", "URWP": "ימין דתי", "Religious Zionist": "ימין דתי", "Otzma": "ימין דתי", "Otzma Yehudit": "ימין דתי", "Zehut": "ימין דתי",
    "Meretz": "שמאל", "Labor": "שמאל", "Labor- Gesher": "שמאל", "Dem. Union": "שמאל", "Emet": "שמאל",
    "Blue & White": "מרכז", "Yesh Atid": "מרכז", "New Hope": "מרכז", "Kulanu": "מרכז", "Gesher": "מרכז", "New Economic": "מרכז",
}
def val(s):
    s = (s or "").strip()
    if not s or s in ("–", "—", "N/A", "— N/a"): return None
    m = re.match(r"^(\d+)", s)
    if m: return float(m.group(1))            # מנדטים
    m = re.search(r"\(([\d.]+)%\)", s)
    if m: return round(float(m.group(1)) * 1.25, 2)   # מתחת לסף: שווה-ערך מנדטים (אחוז x 120/96)
    return None
def pdate(s, year):
    s = s.replace("–", "-").split("-")[-1].strip()      # סוף השדה
    parts = s.split()
    d, mon = int(parts[0]), MON[parts[1][:3]]
    return date(year if len(parts) < 3 else int("20" + parts[2][-2:]), mon, d)
# תוצאות אמת (אחוזי קולות) למפלגות שנפלו בסף - שווה-ערך מנדטים במקום 0, כדי שהטעות תימדד בקולות ולא בסף
BELOW = {"2019-04-09": {"New Right": 3.22, "Zehut": 2.74, "Gesher": 1.73}, "2019-09-17": {"Otzma Yehudit": 1.88},
         "2020-03-02": {"Otzma": 0.42}, "2021-03-23": {"New Economic": 0.79}}
def analyse(fn, window_days=21):
    w = json.loads((ROOT / "data/hist" / fn).read_text(encoding="utf-8"))
    hdr = w["hdr"]; eday = date.fromisoformat(w["election"])
    firm_col = 1; first_party = 2 if "Publisher" not in hdr else 3
    parties = [h for h in hdr[first_party:] if h not in ("Gov.", "L", "R")]
    pidx = {h: hdr.index(h) for h in parties}
    actual = None; polls = []
    for r in w["rows"]:
        if r[1] == "Election results":
            off = len(r) - len(hdr)               # שורת התוצאות בלי עמודת publisher
            actual = {p: val(r[pidx[p] + off]) for p in parties}
            for p, pct in BELOW.get(w["election"], {}).items():
                if p in actual: actual[p] = round(pct * 1.25, 2)
            continue
        if len(r) < len(hdr) or "exit poll" in r[1].lower(): continue
        try: d = pdate(r[0], eday.year)
        except Exception: continue
        if d >= eday or d < eday - timedelta(days=window_days): continue
        polls.append({"date": d, "firm": r[firm_col].split("/")[0].strip(), **{p: val(r[pidx[p]]) for p in parties}})
    errs = {}
    for p in parties:
        v = [q[p] - actual[p] for q in polls if q[p] is not None and actual.get(p) is not None]
        if v: errs[p] = {"seats": round(mean(v), 2), "n": len(v), "actual": actual[p]}
    fam = {}
    for p, e in errs.items():
        f = FAMILY.get(p)
        if f: fam[f] = round(fam.get(f, 0.0) + e["seats"], 2)
    return {"election": w["election"], "n_polls": len(polls), "window_from": (eday - timedelta(days=window_days)).isoformat(),
            "firms": sorted({q["firm"] for q in polls}), "party_seat_error": errs, "family_seat_error": fam,
            "family_pp": {f: round(v * 0.8, 2) for f, v in fam.items()}}
if __name__ == "__main__":
    out = {fn[5:-5]: analyse(fn) for fn in ["wiki_2019a.json", "wiki_2019b.json", "wiki_2020.json", "wiki_2021.json"]}
    (ROOT / "model" / "calibration_hist.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    fams = ["הליכוד", 'ש"ס', "יהדות התורה", "ימין דתי", "ישראל ביתנו", "הרשימה המשותפת", 'רע"ם', "שמאל", "מרכז"]
    print(f"{'':14s}" + "".join(f"{f[:10]:>12s}" for f in fams))
    for k, r in out.items():
        print(f"{k:6s} n={r['n_polls']:<3d}   " + "".join(f"{r['family_seat_error'].get(f, float('nan')):>+12.1f}" for f in fams))
    print("(טעות ענפית ממוצעת במנדטים, סקר פחות תוצאה, 3 שבועות אחרונים; + = הסקרים הפריזו)")

# ---------------------------------------------------------------------------------------------
# שילוב חמש מערכות (2019א, 2019ב, 2020, 2021, 2022) עם דעיכה מעריכית -> הטיה ענפית + פיזור אמפירי, בנקודות אחוז
# ---------------------------------------------------------------------------------------------
FAM22 = {"הליכוד": "הליכוד", 'ש"ס': 'ש"ס', "יהדות התורה": "יהדות התורה", "ישראל ביתנו": "ישראל ביתנו", 'רע"ם': 'רע"ם',
         'חד"ש-תע"ל': "הרשימה המשותפת", "הציונות הדתית": "ימין דתי", "העבודה": "שמאל", "מרצ": "שמאל",
         "יש עתיד": "מרכז", "המחנה הממלכתי": "מרכז"}
def errors_2022():
    c = json.loads((ROOT / "model" / "calibration_2022.json").read_text(encoding="utf-8"))
    per = c["seat_error"]; fam = {}
    for p, f in FAM22.items():
        v = [d[p] for d in per.values() if p in d]
        if v: fam[f] = round(fam.get(f, 0.0) + mean(v), 2)
    return fam
def combine(out, half_life_years=3.0, ref_year=2026):
    fam_err = {k: r["family_seat_error"] for k, r in out.items()}
    fam_err["2022"] = errors_2022()
    years = {"2019a": 2019.3, "2019b": 2019.7, "2020": 2020.2, "2021": 2021.2, "2022": 2022.8}
    fams = ["הליכוד", 'ש"ס', "יהדות התורה", "ימין דתי", "ישראל ביתנו", "הרשימה המשותפת", 'רע"ם', "שמאל", "מרכז"]
    # הימין הדתי: רק 2021-2022, כשהציונות הדתית רצה כרשימה מבוססת; ב-2019-2020 המשפחה הייתה רשימות קטנות סביב הסף
    # (הימין החדש, זהות, עוצמה) וההפרזה שם היא במידה רבה "אפקט סף" שלא עובר לרשימות של היום
    WINDOW = {"ימין דתי": ("2021", "2022")}
    res = {}
    for f in fams:
        pts = [(0.5 ** ((ref_year - years[k]) / half_life_years), fam_err[k][f] * 0.8) for k in fam_err
               if f in fam_err[k] and k in WINDOW.get(f, tuple(fam_err))]
        W = sum(w for w, _ in pts); m = sum(w * e for w, e in pts) / W
        var = sum(w * (e - m) ** 2 for w, e in pts) / W
        res[f] = {"mean_pp": round(m, 2), "sd_pp": round(var ** 0.5, 2), "n_elections": len(pts),
                  "per_election_pp": {k: round(fam_err[k][f] * 0.8, 2) for k in fam_err if f in fam_err[k]}}
    return {"half_life_years": half_life_years, "weights": {k: round(0.5 ** ((ref_year - y) / half_life_years), 2) for k, y in years.items()}, "families": res}
if __name__ == "__main__":
    comb = combine(out)
    cal = json.loads((ROOT / "model" / "calibration_hist.json").read_text(encoding="utf-8")); cal["combined"] = comb
    (ROOT / "model" / "calibration_hist.json").write_text(json.dumps(cal, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nמשולב (נק' אחוז, דעיכה מעריכית, זמן מחצית", comb["half_life_years"], "שנים; משקלים", comb["weights"], ")")
    print(f"{'משפחה':16s}{'2019א':>8s}{'2019ב':>8s}{'2020':>8s}{'2021':>8s}{'2022':>8s} | {'ממוצע':>7s}{'ס.תקן':>7s}")
    for f, r in comb["families"].items():
        pe = r["per_election_pp"]
        print(f"{f:16s}" + "".join(f"{pe.get(k, float('nan')):>+8.1f}" for k in ["2019a","2019b","2020","2021","2022"]) + f" | {r['mean_pp']:>+7.2f}{r['sd_pp']:>7.2f}")
