#!/usr/bin/env python3
"""פרויקט 120 - אריזת כל תוצרי המודל ל-JSON אחד עבור דף האתר (site/data.json)."""
from __future__ import annotations

import json
import sqlite3
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

import arviz as az
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "model"))
from seats import BLOCS, DEFAULT_SURPLUS_PAIRS, allocate_seats  # noqa: E402

OUT = ROOT / "model" / "output"
fc = json.loads((OUT / "forecast.json").read_text(encoding="utf-8"))
seats = json.loads((OUT / "seats_summary.json").read_text(encoding="utf-8"))
parties = fc["candidates"]
election = date.fromisoformat(fc["election_date"])

# --- מגמה לאורך זמן מתוך ה-posterior של pi ---
t = az.from_netcdf(OUT / "trace.nc")
pi = t.posterior["pi"].stack(s=("chain", "draw")).values * 100  # (T, K, S)
T = pi.shape[0]
dates = [(election - timedelta(days=7 * (T - 1 - i))).isoformat() for i in range(T)]
trend = {}
for k, p in enumerate(parties):
    trend[p] = {"mean": np.round(pi[:, k, :].mean(axis=1), 2).tolist(),
                "lo": np.round(np.percentile(pi[:, k, :], 5, axis=1), 2).tolist(),
                "hi": np.round(np.percentile(pi[:, k, :], 95, axis=1), 2).tolist()}

# --- נקודות הסקרים (הקלט למודל, מנורמל ל-100) ---
df = pd.read_csv(ROOT / "model" / "polls_model.csv")
vals = df[parties].div(df[parties].sum(axis=1), axis=0) * 100
polls = [{"date": r.date, "pollster": r.pollster, "n": int(r.sample_size), "ref": str(r.ref),
          **{p: round(float(vals.loc[i, p]), 2) for p in parties}} for i, r in df.iterrows()]

# --- אפקטי סוקרים (נקודות אחוז, ממוצע) ---
he = pd.read_csv(OUT / "house_effects.csv", header=[0, 1], index_col=0)
house = {}
for pollster in he.columns.get_level_values(0).unique():
    house[pollster] = {p: round(float(he[pollster][p].mean()), 2) for p in parties if p in he[pollster].columns}

# --- מטא: מספר סקרים, מכונים, ערוצים ---
conn = sqlite3.connect(ROOT / "db" / "polls.sqlite")
n_polls = conn.execute("SELECT COUNT(*) FROM polls WHERE in_model=1").fetchone()[0]
n_all = conn.execute("SELECT COUNT(*) FROM polls").fetchone()[0]
last_poll = conn.execute("SELECT MAX(fieldwork_end) FROM polls WHERE in_model=1").fetchone()[0]
pollster_counts = dict(conn.execute("""SELECT ps.name, COUNT(*) FROM polls p JOIN pollsters ps ON ps.pollster_id=p.pollster_id
                                        WHERE p.in_model=1 GROUP BY ps.name""").fetchall())

# --- סימולציות גולמיות לכלי "אחוז החסימה": מנדטים לכל מפלגה בכל סימולציה + חלק הקולות של המפלגות שעל הסף ---
sims_df = pd.read_csv(OUT / "seats_sims.csv")
draws_df = pd.read_csv(OUT / "draws_election_day.csv")
risk_parties = [p["party"] for p in seats["parties"] if 0.005 < p["p_threshold"] < 0.995]
sim_parties = list(sims_df.columns)
sims = {"parties": sim_parties, "seats": sims_df.astype(int).values.tolist(),
        "shares": {p: np.round(draws_df[p].values, 2).tolist() for p in risk_parties},
        "risk_parties": risk_parties}

data = {
    "generated": fc["today"], "election_date": fc["election_date"],
    "days_to_election": (election - date.fromisoformat(fc["today"])).days,
    "n_polls_model": n_polls, "n_polls_all": n_all, "last_poll": last_poll,
    "n_sims": seats["n_sims"], "diagnostics": fc["diagnostics"],
    "parties": parties, "party_estimates": fc["election_day_estimates"], "today_estimates": fc["today_estimates"],
    "seats": seats["parties"], "blocs": seats["blocs"], "scenarios": seats["scenarios"],
    "bloc_def": BLOCS, "surplus_pairs": DEFAULT_SURPLUS_PAIRS,
    "trend": {"dates": dates, "series": trend}, "polls": polls, "house": house,
    "pollster_counts": pollster_counts,
    "central_seats": allocate_seats({e["name"]: e["mean"] for e in fc["election_day_estimates"]}),
    "calibration": json.loads((ROOT / "model" / "calibration_2022.json").read_text(encoding="utf-8")) if (ROOT / "model" / "calibration_2022.json").exists() else None,
    "sims": sims,
    "backtest": json.loads((ROOT / "model" / "backtest_2022" / "backtest_2022.json").read_text(encoding="utf-8")) if (ROOT / "model" / "backtest_2022" / "backtest_2022.json").exists() else None,
    "anchor": json.loads((ROOT / "model" / "anchor_trusted.json").read_text(encoding="utf-8")) if (ROOT / "model" / "anchor_trusted.json").exists() else None,
}
assert sum(data["central_seats"].values()) == 120, "central seats must sum to 120"
assert all(sum(data["central_seats"].get(p, 0) for p in ms) >= 0 for ms in BLOCS.values())
(ROOT / "site" / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
print("site/data.json", len(json.dumps(data)) // 1024, "KB")
