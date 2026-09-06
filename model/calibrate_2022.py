#!/usr/bin/env python3
"""פרויקט 120 - כיול מכונים מבחירות 2022: הסקרים האחרונים של כל מכון מול התוצאה האמיתית (1.11.2022)."""
import json, glob, sys
import pandas as pd
ACT_PCT = {'הליכוד':23.41,'יש עתיד':17.79,'הציונות הדתית':10.84,'המחנה הממלכתי':9.08,'ש"ס':8.25,'יהדות התורה':5.88,'ישראל ביתנו':4.48,'רע"ם':4.07,'חד"ש-תע"ל':3.75,'העבודה':3.69,'מרצ':3.16,'בל"ד':2.91,'הבית היהודי':1.19}
ACT_SEATS = {'הליכוד':32,'יש עתיד':24,'הציונות הדתית':14,'המחנה הממלכתי':12,'ש"ס':11,'יהדות התורה':7,'ישראל ביתנו':6,'רע"ם':5,'חד"ש-תע"ל':5,'העבודה':4,'מרצ':0,'בל"ד':0,'הבית היהודי':0}
BLOC_R = ['הליכוד','הציונות הדתית','ש"ס','יהדות התורה']   # 64
def canon(s):
    s=s or ''
    if 'דיירקט' in s or 'פילבר' in s: return 'דיירקט פולס (+נקסט דאטה)'
    if 'קאנטר' in s or 'קנטאר' in s: return 'קנטאר'
    if 'מדגם' in s and 'פרוייקט' not in s: return 'מדגם'
    if 'לזר' in s or 'פאנלס' in s: return 'לזר מחקרים'
    if 'פוקס' in s or 'פרוייקט המדגם' in s: return 'פרויקט המדגם (פוקס)'
    if 'דיאלוג' in s: return 'דיאלוג'
    if 'סמית' in s: return 'מכון סמית'
    return s
rows=[]
for f in sorted(glob.glob('data/k25/extracted/*.json')):
    d=json.load(open(f)); m=[q for q in d['questions'] if q['type']=='main']
    if not m or 'srugim' in d['ref']: continue
    m=m[0]; seats={}; pct={}; haspct=False
    for r in m['results']:
        p=r['party']
        if p=='אחר' and 'עוצמה' in (r.get('party_as_written') or ''): p='הציונות הדתית'
        if p=='בל"ד' and 'חד"ש-תע"ל' not in [x['party'] for x in m['results'] if x['party']!='בל"ד']: pass
        seats[p]=seats.get(p,0)+(r['seats'] or 0)
        if r['pct'] is not None: pct[p]=pct.get(p,0)+r['pct']; haspct=True
    rows.append(dict(name=d['ref'], pollster=canon(d['pollster_as_written']), date=d['fieldwork_end'], n=d['respondents'], seats=seats, pct=pct if haspct else None))
df=pd.DataFrame(rows).sort_values('date')
# חלון: סקרים מ-10.10 ואילך (3 שבועות אחרונים); אם אין - האחרון של המכון
final = df[df.date>='2022-10-10']
covered = set(final.pollster)
fallback = df[~df.pollster.isin(covered)].groupby('pollster').tail(1)
use = pd.concat([final, fallback])
print("סקרים בכיול:"); print(use[['pollster','name','date','n']].to_string(index=False))
out=[]
for ps,g in use.groupby('pollster'):
    last_date = g.date.max()
    for p in ACT_SEATS:
        vals=[r['seats'].get(p,0) for _,r in g.iterrows()]
        out.append((ps, p, sum(vals)/len(vals), ACT_SEATS[p], len(g), last_date))
o=pd.DataFrame(out, columns=['pollster','party','poll','actual','n_polls','last']); o['err']=o.poll-o.actual
piv=o.pivot(index='party',columns='pollster',values='err').loc[list(ACT_SEATS)]
print('\nטעות במנדטים (סקר מינוס תוצאה; + = הסקר הפריז):'); print(piv.round(1).to_string())
summ=o.groupby('pollster').agg(mae=('err',lambda x: x.abs().mean()), n_polls=('n_polls','first'), last=('last','first'))
bloc=o[o.party.isin(BLOC_R)].groupby('pollster').err.sum().rename('bloc_err (64)')
summ=summ.join(bloc); print('\nסיכום:'); print(summ.round(2).sort_values('mae').to_string())
# ייצוא: הטיה לכל מכון בנק' אחוז (מנדט ~ 0.8 נק')
leans={ps: {p: round(float(e)*0.8,2) for p,e in piv[ps].items() if abs(e)>=0.4} for ps in piv.columns}
json.dump({"window":"2022-10-10..2022-10-27 (או הסקר האחרון)", "seat_error": {ps: {p: round(float(v),2) for p,v in piv[ps].items()} for ps in piv.columns},
           "mae": summ.mae.round(2).to_dict(), "bloc_err": bloc.round(1).to_dict(), "leans_pp": leans},
          open('model/calibration_2022.json','w'), ensure_ascii=False, indent=1)
