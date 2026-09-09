#!/usr/bin/env python3
"""
פרויקט 120 - בדיקת עבר (backtest) על בחירות הכנסת ה-25 (1.11.2022).

מריץ את אותו מודל בדיוק על סקרי הוועדה מ-2022, בלי שום כיול שנגזר מתוצאות 2022
(זה היה מעגלי), ומשווה לתוצאה האמיתית. שני מועדי חיתוך:
  - "3 שבועות לפני" (סקרים עד 10.10.2022)
  - "ערב הבחירות"   (סקרים עד 27.10.2022 - הסקר האחרון שמותר לפרסם)
רק סקרים מאחרי הגשת הרשימות (15.9.2022) - כמו היום.
"""
import glob, json, csv, subprocess, sys
from pathlib import Path
from statistics import mean
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from seats import allocate_seats, simulate, summarize
import seats as S

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "model" / "backtest_2022"; OUT.mkdir(exist_ok=True)
PARTIES = ['הליכוד','יש עתיד','הציונות הדתית','המחנה הממלכתי','ש"ס','יהדות התורה','ישראל ביתנו','רע"ם','חד"ש-תע"ל','העבודה','מרצ','בל"ד','הבית היהודי','אחר']
ACT_PCT = {'הליכוד':23.41,'יש עתיד':17.79,'הציונות הדתית':10.84,'המחנה הממלכתי':9.08,'ש"ס':8.25,'יהדות התורה':5.88,'ישראל ביתנו':4.48,'רע"ם':4.07,'חד"ש-תע"ל':3.75,'העבודה':3.69,'מרצ':3.16,'בל"ד':2.91,'הבית היהודי':1.19}
ACT_SEATS = {'הליכוד':32,'יש עתיד':24,'הציונות הדתית':14,'המחנה הממלכתי':12,'ש"ס':11,'יהדות התורה':7,'ישראל ביתנו':6,'רע"ם':5,'חד"ש-תע"ל':5,'העבודה':4,'מרצ':0,'בל"ד':0,'הבית היהודי':0}
BLOCS22 = {"גוש נתניהו": ['הליכוד','הציונות הדתית','ש"ס','יהדות התורה'],
           "גוש השינוי": ['יש עתיד','המחנה הממלכתי','ישראל ביתנו','העבודה','מרצ'],
           "המפלגות הערביות": ['רע"ם','חד"ש-תע"ל','בל"ד']}
SURPLUS22 = [('הליכוד','הציונות הדתית'), ('ש"ס','יהדות התורה'), ('יש עתיד','המחנה הממלכתי'), ('העבודה','מרצ')]
LIST_SUBMISSION = "2022-09-15"

def canon(s):
    s = s or ''
    if 'דיירקט' in s or 'פילבר' in s: return 'דיירקט פולס'
    if 'קאנטר' in s or 'קנטאר' in s: return 'קנטאר'
    if 'מדגם' in s and 'פרוייקט' not in s: return 'מדגם'
    if 'לזר' in s or 'פאנלס' in s: return 'לזר מחקרים'
    if 'פוקס' in s or 'פרוייקט המדגם' in s: return 'פרויקט המדגם'
    if 'דיאלוג' in s: return 'דיאלוג'
    if 'סמית' in s: return 'מכון סמית'
    return s[:20]

def build_input(cutoff: str) -> Path:
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data/k25/extracted/*.json"))):
        d = json.load(open(f, encoding="utf-8")); m = [q for q in d['questions'] if q['type'] == 'main']
        if not m or 'srugim' in d['ref']: continue
        if d['fieldwork_end'] < LIST_SUBMISSION or d['fieldwork_end'] > cutoff: continue
        m = m[0]
        pct = {p: None for p in PARTIES}; pct['אחר'] = 0.0
        haspct = any(r['pct'] is not None for r in m['results'])
        for r in m['results']:
            p = r['party']
            if p == 'אחר' and 'עוצמה' in (r.get('party_as_written') or ''): p = 'הציונות הדתית'
            if p not in pct: p = 'אחר'
            v = r['pct'] if haspct else ((r['seats'] or 0) / 120 * 96.0 if r['seats'] else None)
            if v is None: continue
            pct[p] = (pct[p] or 0.0) + v
        if not haspct: pct['אחר'] += 4.0
        pct['אחר'] += m.get('other_pct') or 0.0
        if pct.get('בל"ד') is None and pct.get('חד"ש-תע"ל'):
            # רשימה משותפת (לפני הפיצול) או סקר שלא שאל על בל"ד - נפצל לפי יחס 2022 בסקרים שכן הפרידו
            tot = pct['חד"ש-תע"ל']; pct['חד"ש-תע"ל'], pct['בל"ד'] = round(tot * 0.6, 2), round(tot * 0.4, 2)
        rows.append([d['fieldwork_end'], canon(d['pollster_as_written']), d['respondents'] or 500, d['ref'], 'pct' if haspct else 'seats'] + [pct[p] for p in PARTIES])
    # השלמת חסרים: ממוצע כללי של המפלגה
    for i, p in enumerate(PARTIES):
        vals = [r[5 + i] for r in rows if r[5 + i] is not None]
        for r in rows:
            if r[5 + i] is None: r[5 + i] = mean(vals) if vals else 0.3
            r[5 + i] = round(max(r[5 + i], 0.3), 2)
    rows.sort()
    out = OUT / f"polls_{cutoff}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(['date', 'pollster', 'sample_size', 'ref', 'pct_source'] + PARTIES); w.writerows(rows)
    print(f"{cutoff}: {len(rows)} polls -> {out.name}")
    return out

def run(cutoff: str, chains=4):
    inp = build_input(cutoff)
    od = OUT / f"out_{cutoff}"
    if not (od / "draws_election_day.csv").exists():
        cmd = [sys.executable, str(ROOT / "model/run_model.py"), "--input", str(inp), "--out", str(od), "--election-date", "2022-11-01",
               "--today", cutoff, "--chains", str(chains)]
        print(" ".join(cmd)); subprocess.run(cmd, check=False)
    draws = pd.read_csv(od / "draws_election_day.csv")
    S.BLOCS = BLOCS22
    seat_df, bloc_df = simulate(draws, surplus_pairs=SURPLUS22, blocs=BLOCS22)
    summ = summarize(seat_df, bloc_df, draws) if False else None
    central = allocate_seats({p: draws[p].mean() for p in draws.columns}, surplus_pairs=SURPLUS22)
    res = {"cutoff": cutoff, "n_polls": sum(1 for _ in open(inp, encoding="utf-8")) - 1, "parties": {}, "blocs": {}}
    for p in ACT_SEATS:
        s = seat_df[p]; sh = draws[p]
        res["parties"][p] = {"central": central.get(p, 0), "median": int(s.median()), "p05": int(s.quantile(.05)), "p95": int(s.quantile(.95)),
                             "actual": ACT_SEATS[p], "share_mean": round(float(sh.mean()), 2), "share_actual": ACT_PCT[p],
                             "p_threshold": round(float((s > 0).mean()), 3), "in_90": int(s.quantile(.05)) <= ACT_SEATS[p] <= int(s.quantile(.95))}
    for b, ms in BLOCS22.items():
        s = bloc_df[b]; act = sum(ACT_SEATS[p] for p in ms)
        res["blocs"][b] = {"central": sum(central.get(p, 0) for p in ms), "median": int(s.median()), "p05": int(s.quantile(.05)), "p95": int(s.quantile(.95)),
                           "actual": act, "p_majority": round(float((s >= 61).mean()), 3), "in_90": int(s.quantile(.05)) <= act <= int(s.quantile(.95))}
    res["mae_seats"] = round(mean(abs(v["central"] - v["actual"]) for v in res["parties"].values()), 2)
    res["mae_share"] = round(mean(abs(v["share_mean"] - v["share_actual"]) for v in res["parties"].values()), 2)
    res["coverage_90"] = round(mean(v["in_90"] for v in res["parties"].values()), 2)
    return res

if __name__ == "__main__":
    results = [run(c) for c in ["2022-10-10", "2022-10-27"]]
    (OUT / "backtest_2022.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in results:
        print(f"\n=== חיתוך {r['cutoff']} ({r['n_polls']} סקרים) | MAE מנדטים {r['mae_seats']} | MAE אחוזים {r['mae_share']} | כיסוי 90%: {r['coverage_90']:.0%}")
        print(f"{'מפלגה':<16}{'מרכזי':>6}{'טווח':>10}{'בפועל':>7}{'סף':>6}")
        for p, v in r["parties"].items(): print(f"{p:<16}{v['central']:>6}{str(v['p05'])+'-'+str(v['p95']):>10}{v['actual']:>7}{v['p_threshold']:>6.0%} {'' if v['in_90'] else '<-- מחוץ לטווח'}")
        for b, v in r["blocs"].items(): print(f"{b:<16}{v['central']:>6}{str(v['p05'])+'-'+str(v['p95']):>10}{v['actual']:>7}  P(61+)={v['p_majority']:.0%}")
