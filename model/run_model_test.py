#!/usr/bin/env python3
"""פרויקט 120 - הרצת מודל kronikas על סקרי הוועדה ושמירת ה-draws לשכבת המנדטים."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from kronikas import ElectionForecast, ModelConfig, PollsterPrior, SharedBiasPrior

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "model" / "output_noseats"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--election-date", default="2026-10-27")
    ap.add_argument("--today", default=None)
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--tune", type=int, default=1500)
    ap.add_argument("--chains", type=int, default=2)
    ap.add_argument("--industry-error-pp", type=float, default=1.5,
                    help="טעות ענפית משותפת (סטיית תקן בנקודות אחוז), מתוצאות עבר בישראל")
    a = ap.parse_args(argv)
    OUT.mkdir(exist_ok=True, parents=True)

    import pandas as pd
    _df = pd.read_csv(ROOT / "model" / "polls_model_nosets.csv")
    _means = _df.iloc[-12:, 5:].mean().to_dict()   # ממוצע 12 הסקרים האחרונים, לקנה מידה של הטעות
    config = ModelConfig(
        num_tune=a.tune, num_draws=a.draws, num_chains=a.chains, cores=min(a.chains, 4),
        target_accept=0.98, progressbar=False,
        time_step_days=7,
        sigma_walk_prior=0.05,          # "normal" - כנקודה בשבוע
        # פאנלים אינטרנטיים - לאפשר יותר רעש מעבר לגודל המדגם
        pollster_priors={
            "נקסט דאטה": PollsterPrior(kappa_log_sigma=1.0),
            "דיירקט פולס": PollsterPrior(kappa_log_sigma=1.0),
        },
        # טעות ענפית: סטיית תקן פרופורציונלית לגודל המפלגה (מפלגה של 5% לא יכולה לטעות ב-2 נקודות כמו מפלגה של 20%)
        shared_bias=SharedBiasPrior(
            sd={p: round(min(a.industry_error_pp, max(0.3, 0.12 * m)), 2) for p, m in _means.items()},
            default_sd=0.3) if a.industry_error_pp > 0 else None,
    )
    fc = ElectionForecast(
        polls_csv=str(ROOT / "model" / "polls_model_nosets.csv"),
        election_date=a.election_date,
        today=a.today or date.today().isoformat(),
        candidate_columns=list(__import__("pandas").read_csv(ROOT / "model" / "polls_model_nosets.csv").columns[5:]),
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
