#!/usr/bin/env python3
"""פרויקט 120 - הרכבת index.html מהתבנית + data.json + לוגו."""
import math
from pathlib import Path
HERE = Path(__file__).resolve().parent

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

def main():
    t = (HERE / 'template.html').read_text(encoding='utf-8')
    d = (HERE / 'data.json').read_text(encoding='utf-8').replace('</script>', '<\\/script>')
    b64 = (HERE / 'logo_b64.txt').read_text().strip()
    mark = (HERE / 'la_b64.txt').read_text().strip()
    html = (t.replace('__DATA__', d).replace('__LOGO_SMALL__', logo_svg())
             .replace('__LOGO_BIG__', logo_svg(' style="width:220px;height:auto"')).replace('__LA_LOGO_B64__', b64).replace('__LA_MARK_B64__', mark))
    (HERE / 'index.html').write_text(html, encoding='utf-8')
    (HERE / 'logo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64"><style>circle{fill:#151A26}.k{fill:#03A89E}</style>' + dots_rtl() + '</svg>', encoding='utf-8')
    print('site/index.html built')

if __name__ == '__main__':
    main()
