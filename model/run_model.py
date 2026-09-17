#!/usr/bin/env python3
"""פרויקט 120 - הרצת מודל kronikas על סקרי הוועדה ושמירת ה-draws לשכבת המנדטים."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import sys as _s; _s.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent / 'vendor'))
from kronikas import ElectionForecast, ModelConfig, PollsterPrior, SharedBiasPrior

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "model" / "output"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--election-date", default="2026-10-27")
    ap.add_argument("--today", default=None)
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--tune", type=int, default=1500)
    ap.add_argument("--chains", type=int, default=2)
    ap.add_argument("--trust-high", default="", help="מכונים באמון גבוה, מופרדים בפסיק (sigma_house=0.10)")
    ap.add_argument("--trust-low", default="", help="מכונים באמון נמוך (sigma_house=0.60)")
    ap.add_argument("--sigma-walk-prior", type=float, default=0.05)
    ap.add_argument("--walk-sigma-max", type=float, default=0.0, help="תקרת tanh על התנודתיות (0 = בלי; הוחלפה ב-prior היררכי, ראה --walk-pool-sd)")
    ap.add_argument("--walk-pool-sd", type=float, default=0.5, help="prior היררכי: איגום חלקי של תנודתיות המפלגות סביב רמה ענפית נלמדת (0 = עצמאי לכל מפלגה)")
    ap.add_argument("--noisy", default="", help="מכונים עם רעש גבוה מעבר למדגם (kappa_log_sigma=1.0)")
    ap.add_argument("--leans-json", default=None, help="קובץ JSON: {מכון: {מפלגה: נק' אחוז}} - הטיה ידועה מבחוץ")
    ap.add_argument("--out", default=None)
    ap.add_argument("--input", default=None, help="קובץ סקרים חלופי (ברירת מחדל model/polls_model.csv) - לבדיקות עבר")
    ap.add_argument("--industry-lean-json", default=None, help='קובץ JSON {מפלגה: נק אחוז} - כמה הסקרים (ממוצע הענף) מפריזים במפלגה (+) או מפחיתים (-)')
    ap.add_argument("--industry-lean-key", default=None, help="מפתח בתוך הקובץ (למשל half/full)")
    ap.add_argument("--entry-skip-weeks", type=float, default=1.0,
                    help="רשימה שנכנסה באמצע הסדרה: הסקרים שלפני כניסתה ובשבועות הראשונים אחריה אינם מלמדים עליה (0 = רק הסקרים שלא דיווחו עליה; -1 = בלי מסכה כלל)")
    ap.add_argument("--industry-sd-key", default=None, help="מפתח בקובץ ה-lean עם סטיית תקן לכל מפלגה (למשל hist_sd); בלעדיו: 12% מגודל המפלגה, 0.3-1.5")
    ap.add_argument("--industry-error-pp", type=float, default=1.5,
                    help="טעות ענפית משותפת (סטיית תקן בנקודות אחוז), מתוצאות עבר בישראל")
    a = ap.parse_args(argv)
    global OUT
    if a.out: OUT = Path(a.out)
    OUT.mkdir(exist_ok=True, parents=True)
    lean = {}
    if a.industry_lean_json:
        lean = json.loads(Path(a.industry_lean_json).read_text(encoding="utf-8"))
        _all = lean
        if a.industry_lean_key: lean = lean[a.industry_lean_key]
        print("industry lean (polls overstate +):", lean)
        if a.industry_sd_key:
            sd_file = _all[a.industry_sd_key]; print("industry sd (pp):", sd_file)
    leans = json.loads(Path(a.leans_json).read_text(encoding="utf-8")) if a.leans_json else {}
    sd_file = locals().get("sd_file", {})
    priors = {}
    for name in [x.strip() for x in a.trust_high.split(",") if x.strip()]: priors.setdefault(name, {})["sigma_house"] = 0.10
    for name in [x.strip() for x in a.trust_low.split(",") if x.strip()]: priors.setdefault(name, {})["sigma_house"] = 0.60
    for name in [x.strip() for x in a.noisy.split(",") if x.strip()]: priors.setdefault(name, {})["kappa_log_sigma"] = 1.0
    for name, d in leans.items(): priors.setdefault(name, {})["mu_house"] = d
    pollster_priors = {k: PollsterPrior(**v) for k, v in priors.items()}
    print("pollster priors:", priors)

    def _zero_sum_lean(lean_pp: dict, means: dict) -> dict:
        """ההטיה הענפית חייבת להסתכם לאפס (חלקי הקולות מסתכמים ל-100). kronikas מטיל את השארית על המפלגות
        שלא צוינו - וכשנשארת מפלגה אחת בלבד בלי ערך (יהדות התורה, 14.9.2026) היא ספגה לבדה -2.85 נק' והמודל הוריד אותה
        מ-6% ל-3.7%. כאן השארית מתפזרת על כל המפלגות לפי גודלן (שינוי יחסי אחיד, כמעט חסר השפעה), וכולן מקבלות ערך מפורש."""
        tot = sum(means.values()) or 1.0
        resid = -sum(lean_pp.values())
        return {p: round(lean_pp.get(p, 0.0) + resid * m / tot, 3) for p, m in means.items()}

    import pandas as pd
    _df = pd.read_csv(Path(a.input) if a.input else ROOT / "model" / "polls_model.csv")
    _means = _df.iloc[-12:, 5:].mean().to_dict()   # ממוצע 12 הסקרים האחרונים, לקנה מידה של הטעות
    config = ModelConfig(
        num_tune=a.tune, num_draws=a.draws, num_chains=a.chains, cores=min(a.chains, 4),
        target_accept=0.98, progressbar=False,
        time_step_days=7,
        per_party_walk=True,           # תנודתיות נפרדת לכל מפלגה - אחרת המפלגות הקטנות מנפחות את התנודתיות של כולן
        walk_pool_sd=a.walk_pool_sd,
        walk_sigma_max=a.walk_sigma_max,  # תקרה לתנודתיות שבועית (0.10 = עד ~10% שינוי יחסי בשבוע) - כניסת רשימה חדשה לא מוקרנת קדימה כתנודתיות קבועה   # איגום חלקי: כל מפלגה נמשכת לרמה הענפית; מפלגה שהסקרים רק חלוקים עליה לא "בורחת" (הציונות הדתית 0.19)
        sigma_walk_prior=a.sigma_walk_prior,  # סקאלת prior לתנודתיות (HalfNormal, לשבוע, בסקאלה לוגריתמית)
        pollster_priors=pollster_priors,
        # טעות ענפית: סטיית תקן פרופורציונלית לגודל המפלגה (מפלגה של 5% לא יכולה לטעות ב-2 נקודות כמו מפלגה של 20%)
        shared_bias=SharedBiasPrior(
            mean=_zero_sum_lean({p: v for p, v in lean.items() if p in _means}, _means),
            sd={p: (round(float(sd_file[p]), 2) if p in sd_file else round(min(a.industry_error_pp, max(0.3, 0.12 * m)), 2)) for p, m in _means.items()},
            default_sd=0.3) if a.industry_error_pp > 0 else None,
    )
    polls_csv = Path(a.input) if a.input else ROOT / "model" / "polls_model.csv"
    fc = ElectionForecast(
        polls_csv=str(polls_csv),
        election_date=a.election_date,
        today=a.today or date.today().isoformat(),
        candidate_columns=list(__import__("pandas").read_csv(polls_csv).columns[5:]),
        config=config,
    )
    # --- מסכת כניסה [המלצת ויקטור טיסה]: תא (סקר, מפלגה) שאינו מידע אמיתי אינו נכנס לנראות ---
    #   (א) תא שהושלם (imputed) - הסקר לא דיווח על המפלגה;
    #   (ב) רשימה מאוחרת (לא דווחה ברוב הסקרים בשבועיים הראשונים של הסדרה): כל הסקרים לפני מועד הכניסה
    #       (היום הראשון שבו רוב הסקרים בשבוע שאחריו מדווחים עליה) ועוד N שבועות אחריו.
    #   התא נספג ב"אחר" לאותו סקר בלבד (איחוד רכיבי דיריכלה - מדויק), ראה vendor/kronikas/model.py.
    entries, hidden = {}, []
    if a.entry_skip_weeks >= 0:
        import numpy as _np
        _pd = __import__("pandas")
        _raw = _pd.read_csv(polls_csv)
        _cands = list(_raw.columns[5:])
        _dates = _pd.to_datetime(_raw["date"])
        _src = _raw["pct_source"].astype(str) if "pct_source" in _raw.columns else _pd.Series([""] * len(_raw))
        reported = _np.ones((len(_raw), len(_cands)), dtype=bool)
        for i, srcv in enumerate(_src):
            for tok in srcv.split("|"):
                if tok.startswith("imputed:") and tok[8:] in _cands:
                    reported[i, _cands.index(tok[8:])] = False
        mask = reported.copy()
        t0 = _dates.min()
        for k, c in enumerate(_cands):
            if c == "אחר":
                continue
            first2w = (_dates <= t0 + _pd.Timedelta(days=14)).values
            if first2w.sum() >= 3 and reported[first2w, k].mean() < 0.5:
                entry = None
                for d in sorted(set(_dates)):
                    win = ((_dates >= d) & (_dates < d + _pd.Timedelta(days=7))).values
                    if win.sum() >= 2 and reported[win, k].mean() >= 0.5:
                        entry = d; break
                if entry is not None:
                    entries[c] = entry.date().isoformat()
                    mask[(_dates < entry + _pd.Timedelta(days=7 * a.entry_skip_weeks)).values, k] = False
        if not mask.all():
            order = _np.argsort(_dates.values, kind="stable")
            fc.poll_data.mask = mask[order]
            hidden = [[str(_raw["ref"].iloc[i]), _cands[k]] for i, k in zip(*_np.where(~mask))]
            print(f"entry mask: {int((~mask).sum())} cells hidden; late entrants: {entries}; skip {a.entry_skip_weeks} weeks after entry")
    result = fc.run()
    print(result.summary())
    print(result.diagnostics.summary())

    result.party_forecast_dataframe(day="election_day").to_csv(OUT / "draws_election_day.csv", index=False, encoding="utf-8-sig")
    result.party_forecast_dataframe(day="today").to_csv(OUT / "draws_today.csv", index=False, encoding="utf-8-sig")
    try:
        result.house_effects_dataframe().to_csv(OUT / "house_effects.csv", encoding="utf-8-sig")
    except RuntimeError:
        pass
    payload = result.to_dict(thresholds=[3.25])
    dg = result.diagnostics
    ess, rhat = getattr(dg, "min_ess_bulk", None), getattr(dg, "max_r_hat", None)
    # דירוג: ok = עבר; marginal = מעט מתחת לסף (ESS 250-400 או R-hat עד 1.03) - התוצאות תקינות לכל צורך מעשי; bad = כשל אמיתי
    grade = "ok" if dg.converged else ("marginal" if (ess is None or ess >= 250) and (rhat is None or rhat <= 1.03) else "bad")
    payload["diagnostics"] = {"converged": dg.converged, "grade": grade, "issues": dg.issues,
                              "min_ess_bulk": None if ess is None else round(float(ess)), "max_r_hat": None if rhat is None else round(float(rhat), 3)}
    payload["entry_mask"] = {"entries": entries, "skip_weeks": a.entry_skip_weeks, "hidden": hidden}
    payload["election_date"] = a.election_date
    payload["today"] = a.today or date.today().isoformat()
    (OUT / "forecast.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    result.save(str(OUT / "trace.nc"))
    print("saved to", OUT)
    return 0 if result.diagnostics.converged else 1


if __name__ == "__main__":
    sys.exit(main())
