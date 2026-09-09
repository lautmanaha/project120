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
    ap.add_argument("--walk-sigma-max", type=float, default=0.10)
    ap.add_argument("--walk-pool-sd", type=float, default=0.0, help="איגום חלקי של תנודתיות המפלגות (0 = עצמאי לכל מפלגה)")
    ap.add_argument("--noisy", default="", help="מכונים עם רעש גבוה מעבר למדגם (kappa_log_sigma=1.0)")
    ap.add_argument("--leans-json", default=None, help="קובץ JSON: {מכון: {מפלגה: נק' אחוז}} - הטיה ידועה מבחוץ")
    ap.add_argument("--out", default=None)
    ap.add_argument("--input", default=None, help="קובץ סקרים חלופי (ברירת מחדל model/polls_model.csv) - לבדיקות עבר")
    ap.add_argument("--industry-lean-json", default=None, help='קובץ JSON {מפלגה: נק אחוז} - כמה הסקרים (ממוצע הענף) מפריזים במפלגה (+) או מפחיתים (-)')
    ap.add_argument("--industry-lean-key", default=None, help="מפתח בתוך הקובץ (למשל half/full)")
    ap.add_argument("--industry-error-pp", type=float, default=1.5,
                    help="טעות ענפית משותפת (סטיית תקן בנקודות אחוז), מתוצאות עבר בישראל")
    a = ap.parse_args(argv)
    global OUT
    if a.out: OUT = Path(a.out)
    OUT.mkdir(exist_ok=True, parents=True)
    lean = {}
    if a.industry_lean_json:
        lean = json.loads(Path(a.industry_lean_json).read_text(encoding="utf-8"))
        if a.industry_lean_key: lean = lean[a.industry_lean_key]
        print("industry lean (polls overstate +):", lean)
    leans = json.loads(Path(a.leans_json).read_text(encoding="utf-8")) if a.leans_json else {}
    priors = {}
    for name in [x.strip() for x in a.trust_high.split(",") if x.strip()]: priors.setdefault(name, {})["sigma_house"] = 0.10
    for name in [x.strip() for x in a.trust_low.split(",") if x.strip()]: priors.setdefault(name, {})["sigma_house"] = 0.60
    for name in [x.strip() for x in a.noisy.split(",") if x.strip()]: priors.setdefault(name, {})["kappa_log_sigma"] = 1.0
    for name, d in leans.items(): priors.setdefault(name, {})["mu_house"] = d
    pollster_priors = {k: PollsterPrior(**v) for k, v in priors.items()}
    print("pollster priors:", priors)

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
            mean={p: v for p, v in lean.items() if p in _means},
            sd={p: round(min(a.industry_error_pp, max(0.3, 0.12 * m)), 2) for p, m in _means.items()},
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
    payload["diagnostics"] = {"converged": result.diagnostics.converged, "issues": result.diagnostics.issues}
    payload["election_date"] = a.election_date
    payload["today"] = a.today or date.today().isoformat()
    (OUT / "forecast.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    result.save(str(OUT / "trace.nc"))
    print("saved to", OUT)
    return 0 if result.diagnostics.converged else 1


if __name__ == "__main__":
    sys.exit(main())
