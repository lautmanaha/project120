#!/usr/bin/env python3
"""
פרויקט 120 - שכבת המנדטים: מחלק קולות -> 120 מנדטים לפי שיטת בדר-עופר.

חוק הבחירות לכנסת:
  1. אחוז חסימה 3.25% מהקולות הכשרים. רשימה מתחת לסף לא משתתפת בחלוקה.
  2. מודד ראשוני = (קולות הרשימות שעברו) / 120. כל רשימה מקבלת floor(קולות/מודד).
  3. העודפים מחולקים לפי "ממוצע הגדול ביותר" (ד'הונדט): בכל סבב המנדט הולך לרשימה
     שאצלה קולות/(מנדטים+1) הוא הגבוה ביותר.
  4. הסכמי עודפים: שתי רשימות שחתמו נחשבות יחידה אחת בשלבים 2-3, ואז המנדטים המשותפים
     מחולקים ביניהן שוב באותה שיטה.

הפונקציה allocate_seats מקבלת חלקי קולות (באחוזים, לא חייבים להסתכם ל-100 - "אחר" מנורמל
החוצה) ורשימת הסכמי עודפים, ומחזירה מנדטים לכל רשימה.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

THRESHOLD = 3.25
SEATS = 120

# הסכמי עודפים - ברירת מחדל לפי הדפוס ההיסטורי; לעדכן כשייחתמו בפועל
DEFAULT_SURPLUS_PAIRS = [
    ("הליכוד", "הציונות הדתית"),
    ("ש\"ס", "יהדות התורה"),
    ("ישר", "ביחד"),
    ("הדמוקרטים", "ישראל ביתנו"),
]

# גושים - הגדרה פוליטית, לא סטטיסטית. נכון ל-6.9.2026 (זהות בתוך הציונות הדתית, וינטר בגוש נתניהו)
BLOCS = {
    "גוש הימין": ["הליכוד", "ש\"ס", "יהדות התורה", "עוצמה יהודית", "הציונות הדתית", "עמך ישראל"],
    "גוש השמאל": ["ישר", "ביחד", "הדמוקרטים", "ישראל ביתנו", "כחול לבן"],
    "המפלגות הערביות": ["הרשימה המשותפת", "רע\"ם"],
}


def _dhondt(votes: dict[str, float], seats: int) -> dict[str, int]:
    """חלוקת seats מנדטים לפי ממוצע הגדול ביותר (שקול לבדר-עופר עם מודד + עודפים)."""
    alloc = {k: 0 for k in votes}
    if seats <= 0 or not votes:
        return alloc
    total = sum(votes.values())
    # שלב המודד: floor
    for k, v in votes.items():
        alloc[k] = int(v * seats // total)
    remaining = seats - sum(alloc.values())
    for _ in range(remaining):
        best = max(votes, key=lambda k: votes[k] / (alloc[k] + 1))
        alloc[best] += 1
    return alloc


def allocate_seats(shares: dict[str, float], surplus_pairs=DEFAULT_SURPLUS_PAIRS,
                   threshold: float = THRESHOLD, exclude=("אחר",)) -> dict[str, int]:
    valid = {k: v for k, v in shares.items() if k not in exclude and v > 0}
    total = sum(valid.values())
    passed = {k: v for k, v in valid.items() if v / total * 100 >= threshold}
    seats = {k: 0 for k in shares if k not in exclude}
    if not passed:
        return seats
    # יחידות: זוגות עודפים שבהם שני הצדדים עברו, אחרת כל רשימה לבד
    units: dict[str, list[str]] = {}
    used = set()
    for a, b in surplus_pairs:
        if a in passed and b in passed and a not in used and b not in used:
            units[f"{a}+{b}"] = [a, b]
            used.update((a, b))
    for k in passed:
        if k not in used:
            units[k] = [k]
    unit_votes = {u: sum(passed[m] for m in members) for u, members in units.items()}
    unit_seats = _dhondt(unit_votes, SEATS)
    for u, members in units.items():
        if len(members) == 1:
            seats[members[0]] = unit_seats[u]
        else:
            inner = _dhondt({m: passed[m] for m in members}, unit_seats[u])
            seats.update(inner)
    return seats


def simulate(draws: pd.DataFrame, surplus_pairs=DEFAULT_SURPLUS_PAIRS, blocs=BLOCS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """draws: שורה לכל סימולציה, עמודה למפלגה (אחוזים). מחזיר (מנדטים לכל סימולציה, מנדטים לגוש)."""
    parties = [c for c in draws.columns if c != "אחר"]
    out = np.zeros((len(draws), len(parties)), dtype=int)
    for i, row in enumerate(draws.to_dict("records")):
        s = allocate_seats(row, surplus_pairs)
        out[i] = [s[p] for p in parties]
    seat_df = pd.DataFrame(out, columns=parties)
    bloc_df = pd.DataFrame({name: seat_df[[p for p in members if p in seat_df.columns]].sum(axis=1)
                            for name, members in blocs.items()})
    return seat_df, bloc_df


def summarize(seat_df: pd.DataFrame, bloc_df: pd.DataFrame, draws: pd.DataFrame) -> dict:
    parties = []
    for p in seat_df.columns:
        s = seat_df[p]
        parties.append({
            "party": p, "seats_median": int(s.median()), "seats_mean": round(float(s.mean()), 1),
            "seats_p05": int(s.quantile(0.05)), "seats_p95": int(s.quantile(0.95)),
            "share_mean": round(float(draws[p].mean()), 1),
            "p_threshold": round(float((s > 0).mean()), 3),
            "seat_dist": {int(k): round(float(v), 4) for k, v in s.value_counts(normalize=True).sort_index().items()},
        })
    parties.sort(key=lambda d: -d["seats_mean"])
    blocs = []
    for b in bloc_df.columns:
        s = bloc_df[b]
        blocs.append({
            "bloc": b, "members": BLOCS[b], "seats_median": int(s.median()), "seats_mean": round(float(s.mean()), 1),
            "seats_p05": int(s.quantile(0.05)), "seats_p95": int(s.quantile(0.95)),
            "p_majority": round(float((s >= 61).mean()), 3),
            "seat_dist": {int(k): round(float(v), 4) for k, v in s.value_counts(normalize=True).sort_index().items()},
        })
    opp_plus_arab = bloc_df["גוש השמאל"] + bloc_df["המפלגות הערביות"]
    coalition = bloc_df["גוש הימין"]
    scenarios = {
        "p_coalition_majority": round(float((coalition >= 61).mean()), 3),
        "p_opposition_majority": round(float((bloc_df["גוש השמאל"] >= 61).mean()), 3),
        "p_opposition_with_arab_majority": round(float((opp_plus_arab >= 61).mean()), 3),
        "p_deadlock": round(float(((coalition < 61) & (opp_plus_arab < 61)).mean()), 3),
    }
    return {"parties": parties, "blocs": blocs, "scenarios": scenarios, "n_sims": int(len(seat_df))}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    out = Path(__file__).resolve().parent / "output"
    draws = pd.read_csv(out / "draws_election_day.csv")
    seat_df, bloc_df = simulate(draws)
    summary = summarize(seat_df, bloc_df, draws)
    seat_df.to_csv(out / "seats_sims.csv", index=False, encoding="utf-8-sig")
    (out / "seats_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{summary['n_sims']} סימולציות")
    for b in summary["blocs"]:
        print(f"{b['bloc']:<20} חציון {b['seats_median']:>3}  טווח 90%: {b['seats_p05']}-{b['seats_p95']}  P(>=61)={b['p_majority']:.0%}")
    print(summary["scenarios"])
    for p in summary["parties"]:
        print(f"  {p['party']:<16} {p['seats_median']:>3}  ({p['seats_p05']}-{p['seats_p95']})  {p['share_mean']:>5}%  סף: {p['p_threshold']:.0%}")
    sys.exit(0)
