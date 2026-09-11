#!/usr/bin/env python3
"""פרויקט 120 - הרכבת index.html (עברית) ו-en/index.html (אנגלית) מהתבנית + data.json + לוגו.

האנגלית נבנית מאותה תבנית: כל קטע טקסט עברי מוחלף לפי site/i18n_en.json (מפתח = הקטע כפי שהוא בתבנית),
ושמות המפלגות/המכונים/הגושים מוחלפים גם בתוך data.json (איות פונטי), כך שהמפתחות ב-JS וב-JSON נשארים עקביים.
"""
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEB = r'[֐-׿]'

# שמות (מפלגות, גושים, מכונים) - איות פונטי. מוחלפים בתוך data.json בלבד, מהארוך לקצר.
NAMES_EN = {
    "הרשימה המשותפת": "HaReshima HaMeshutefet", "המחנה הממלכתי": "HaMachane HaMamlachti", "הציונות הדתית": "HaTzionut HaDatit",
    "המפלגות הערביות": "Arab parties", "ישראל ביתנו": "Yisrael Beitenu", "יהדות התורה": "Yahadut HaTorah", "עוצמה יהודית": "Otzma Yehudit",
    "הבית היהודי": "HaBayit HaYehudi", "הדמוקרטים": "HaDemokratim", "עמך ישראל": "Amcha Yisrael", "גוש נתניהו": "Netanyahu bloc",
    "גוש השינוי": "Change bloc", "גוש הימין": "Right bloc", "גוש השמאל": "Left bloc", "חד\"ש-תע\"ל": "Hadash-Ta'al",
    "כחול לבן": "Kachol Lavan", "יש עתיד": "Yesh Atid", "הליכוד": "Likud", "העבודה": "HaAvoda", "ביחד": "Beyachad",
    "זהות": "Zehut", "בל\"ד": "Balad", "רע\"ם": "Ra'am", "ש\"ס": "Shas", "מרצ": "Meretz", "ישר": "Yashar", "אחר": "Other",
    # מכונים
    "פרויקט המדגם (רוזנר)": "HaMidgam Project (Rosner)", "פרויקט המדגם (פוקס)": "HaMidgam Project (Fuchs)", "פרויקט המדגם": "HaMidgam Project",
    "דיירקט פולס (+נקסט דאטה)": "Direct Polls (+Next Data)", "דיירקט פולס": "Direct Polls", "נקסט דאטה": "Next Data",
    "לזר מחקרים": "Lazar Research", "מאגר מוחות": "Maagar Mochot", "מכון סמית": "Smith Institute", "קנטאר": "Kantar",
    "(או הסקר האחרון)": "(or the pollster\u2019s last poll)", "טאטיקה": "Tatika", "דיאלוג": "Dialog", "אפקאר מחקרים וידע": "Afkar Research", "אפקאר": "Afkar", "מדגם": "Midgam", "מכון DRI": "DRI Institute",
}


def dots_rtl(r_list=(22, 34, 46), counts=(30, 40, 50), cx=60, cy=60, rad=1.35, mark61=True):
    out = []; k = 0
    for r, n in zip(r_list, counts):
        for i in range(n):
            a = math.pi * (i / (n - 1))
            x = cx + r * math.cos(a); y = cy - r * math.sin(a); k += 1
            cls = ' class="k"' if (mark61 and k == 61) else ''
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad*1.9 if cls else rad}"{cls}/>')
    return ''.join(out)


def logo_svg(extra_style=''):
    return f'<svg viewBox="0 0 120 64" class="logo-dots"{extra_style} role="img" aria-label="פרויקט 120">{dots_rtl()}</svg>'


def translate_template(t: str, table: dict) -> tuple[str, list]:
    """מחליף כל קטע עברי (לפי אותה חלוקה ששימשה לחילוץ i18n_segments.json) בתרגום. מחזיר גם קטעים שלא נמצאו."""
    missing = []
    def sub(m):
        run = m.group(0)
        h = re.search(HEB + r'.*' + HEB, run)
        if not h:
            return run
        seg = h.group(0)
        key = seg.strip()
        if key in table:
            return run[:h.start()] + table[key].replace("'", "\u2019") + run[h.end():]
        missing.append(key)
        return run
    out = re.sub(r"[^<>'`\n]+", sub, t)
    return out, missing


def translate_data(d: str) -> str:
    for he, en in sorted(NAMES_EN.items(), key=lambda kv: -len(kv[0])):
        lit = json.dumps(he, ensure_ascii=False)[1:-1]
        d = re.sub('(?<!' + HEB + ')' + re.escape(lit) + '(?!' + HEB + ')', en.replace("'", "\u2019"), d)
    return d


ANALYTICS = ('<!-- Cloudflare Web Analytics --><script type="module" src="https://static.cloudflareinsights.com/beacon.min.js" '
             'data-cf-beacon=\'{"token": "c0577a42bf76400f822d4b8382150152"}\'></script><!-- End Cloudflare Web Analytics -->')


def wrap(body: str, lang: str) -> str:
    direction = 'rtl' if lang == 'he' else 'ltr'
    return (f'<!doctype html>\n<html lang="{lang}" dir="{direction}">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">\n<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+CiAgPHJlY3Qgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0IiByeD0iMTQiIGZpbGw9IiMxNTFBMjYiLz4KICA8ZyBmaWxsPSIjRjFGM0Y4Ij4KICAgIDxjaXJjbGUgY3g9IjExIiBjeT0iNDIiIHI9IjQuMiIvPjxjaXJjbGUgY3g9IjE1LjUiIGN5PSIyOS41IiByPSI0LjIiLz48Y2lyY2xlIGN4PSIyNCIgY3k9IjIwIiByPSI0LjIiLz4KICAgIDxjaXJjbGUgY3g9IjQ0IiBjeT0iMjAiIHI9IjQuMiIvPjxjaXJjbGUgY3g9IjUyLjUiIGN5PSIyOS41IiByPSI0LjIiLz48Y2lyY2xlIGN4PSI1NyIgY3k9IjQyIiByPSI0LjIiLz4KICA8L2c+CiAgPGNpcmNsZSBjeD0iMzQiIGN5PSIxNiIgcj0iNS4yIiBmaWxsPSIjMDNBODlFIi8+CiAgPHRleHQgeD0iMzQiIHk9IjUyIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LWZhbWlseT0iQXJpYWwsIEhlbHZldGljYSwgc2Fucy1zZXJpZiIgZm9udC13ZWlnaHQ9IjcwMCIgZm9udC1zaXplPSIxOSIgZmlsbD0iI0YxRjNGOCI+MTIwPC90ZXh0Pgo8L3N2Zz4K">\n{ANALYTICS}\n'
            f'<meta name="description" content="{"פרויקט 120 - תחזית הבחירות לכנסת ה-26 מכל הסקרים שפורסמו רשמית באתר ועדת הבחירות" if lang=="he" else "Project 120 - a statistical forecast of the 26th Knesset election, built from every poll filed with the Central Elections Committee"}">\n'
            + body + '\n</html>\n')


def build(lang: str) -> str:
    t = (HERE / 'template.html').read_text(encoding='utf-8')
    d = (HERE / 'data.json').read_text(encoding='utf-8').replace('</script>', '<\\/script>')
    b64 = (HERE / 'logo_b64.txt').read_text().strip()
    mark = (HERE / 'la_b64.txt').read_text().strip()
    if lang == 'en':
        table = json.loads((HERE / 'i18n_en.json').read_text(encoding='utf-8'))
        t, missing = translate_template(t, table)
        if missing:
            print('  [en] קטעים ללא תרגום:', sorted(set(missing))[:20])
        t = t.replace("pct\u2019 pts", "pts").replace("pct' pts", "pts").replace("pts' ", "pts ").replace("pts')", "pts)").replace("forecasts at -<a", "forecasts at <a")
        t = t.replace('html{direction:rtl;', 'html{direction:ltr;').replace('direction:rtl;font-weight:600', 'direction:ltr;font-weight:600')
        t = t.replace('__LANG_HREF__', '../').replace('__LANG_LABEL__', 'עברית').replace('__LANG_TITLE__', 'לגרסה העברית')
        d = translate_data(d)
    else:
        t = t.replace('__LANG_HREF__', 'en/').replace('__LANG_LABEL__', 'English').replace('__LANG_TITLE__', 'English version')
    html = (t.replace('__DATA__', d).replace('__LOGO_SMALL__', logo_svg())
             .replace('__LOGO_BIG__', logo_svg(' style="width:220px;height:auto"')).replace('__LA_LOGO_B64__', b64).replace('__LA_MARK_B64__', mark))
    return wrap(html, lang)


def main():
    (HERE / 'index.html').write_text(build('he'), encoding='utf-8')
    (HERE / 'en').mkdir(exist_ok=True)
    (HERE / 'en' / 'index.html').write_text(build('en'), encoding='utf-8')
    (HERE / 'logo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64"><style>circle{fill:#151A26}.k{fill:#03A89E}</style>' + dots_rtl() + '</svg>', encoding='utf-8')
    print('site/index.html + site/en/index.html built')


if __name__ == '__main__':
    main()
