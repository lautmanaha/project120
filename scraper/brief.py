#!/usr/bin/env python3
"""
פרויקט 120 - בריף אחרי כל ריצה: טקסט (פרטי + טיוטה לפרסום) וכרטיס גרפי 1080x1080, נשלחים לטלגרם.

  python scraper/brief.py            # מייצר brief/ (private.txt, public.txt, card.png) בלי לשלוח
  python scraper/brief.py --send     # גם שולח לצ'אט הפרטי (TELEGRAM_BOT_TOKEN בסביבה; מזהה הצ'אט נשמר ב-db/telegram.json)

"מה חדש" = סקרים ש-first_seen שלהם היום. "מה השתנה" = מול הגרסה הקודמת של seats_summary.json ב-git (HEAD), ואם אין - מול
הרשומה הקודמת ביומן (history.jsonl).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "brief"
SITE = "https://project120.co.il"

PARTY_COLOR = {"הליכוד": "#2255A4", "ש\"ס": "#3D6FBF", "יהדות התורה": "#1B3F80", "עוצמה יהודית": "#6B8FD1", "הציונות הדתית": "#4A62A8",
               "עמך ישראל": "#8FA9DC", "ישר": "#18A07A", "ביחד": "#4DBA95", "הדמוקרטים": "#137A5C", "ישראל ביתנו": "#83D1B3",
               "כחול לבן": "#B3E4D1", "הרשימה המשותפת": "#C8353A", "רע\"ם": "#E88686", "אחר": "#6A7184"}
BLOC_COLOR = {"גוש הימין": "#2255A4", "גוש השמאל": "#18A07A", "המפלגות הערביות": "#C8353A"}


def fmt_date(s: str) -> str:
    y, m, d = s.split("-")
    return f"{int(d)}.{int(m)}.{y}"


def sign(v: float, nd: int = 0) -> str:
    v = round(v, nd)
    if v == 0:
        return "ללא שינוי"
    return (f"+{v:.{nd}f}" if v > 0 else f"{v:.{nd}f}").replace(".0", "") if nd == 0 else (f"+{v:.{nd}f}" if v > 0 else f"{v:.{nd}f}")


def load_prev_seats() -> dict | None:
    try:
        txt = subprocess.run(["git", "show", "HEAD:model/output/seats_summary.json"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return json.loads(txt)
    except Exception:
        return None


def new_polls(conn: sqlite3.Connection, today: str) -> list[dict]:
    rows = conn.execute("""SELECT m.reference_number, ps.name, m.survey_publisher, p.fieldwork_start, p.fieldwork_end, p.respondents, p.in_model, p.exclude_reason
                           FROM polls_meta m LEFT JOIN polls p ON p.reference_number=m.reference_number
                           LEFT JOIN pollsters ps ON ps.pollster_id=p.pollster_id
                           WHERE substr(m.first_seen,1,10)=? ORDER BY m.reference_number""", (today,)).fetchall()
    out = []
    for ref, pollster, pub, fs, fe, n, in_model, reason in rows:
        blocs = {}
        for party, seats in conn.execute("""SELECT r.party, r.seats FROM poll_results r JOIN poll_questions q ON q.question_id=r.question_id
                                            WHERE r.reference_number=? AND q.type='main' AND r.seats IS NOT NULL""", (ref,)):
            for b, members in BLOC_DEF.items():
                if party in members:
                    blocs[b] = blocs.get(b, 0) + int(seats)
        out.append({"ref": ref, "pollster": pollster or "", "publisher": pub or "", "date": fe or fs or "", "n": n, "in_model": in_model,
                    "reason": reason, "blocs": blocs})
    return out


BLOC_DEF: dict = {}


def build_texts(d: dict, prev: dict | None, polls: list[dict]) -> tuple[str, str, dict]:
    today = d["generated"]
    right = next(b for b in d["blocs"] if b["bloc"] == "גוש הימין")
    left = next(b for b in d["blocs"] if b["bloc"] == "גוש השמאל")
    arab = next(b for b in d["blocs"] if b["bloc"] == "המפלגות הערביות")
    cs = d["central_seats"]
    rc, lc, ac = (sum(cs.get(p, 0) for p in d["bloc_def"][b]) for b in ("גוש הימין", "גוש השמאל", "המפלגות הערביות"))
    p_maj = round(right["p_majority"] * 100)
    # שינוי מול הריצה הקודמת
    chg = {}
    if prev:
        pr = next((b for b in prev["blocs"] if b["bloc"] == "גוש הימין"), None)
        if pr:
            chg = {"right_mean": right["seats_mean"] - pr["seats_mean"], "p_maj": round((right["p_majority"] - pr["p_majority"]) * 100),
                   "parties": {p["party"]: p["seats_mean"] - next((q["seats_mean"] for q in prev["parties"] if q["party"] == p["party"]), p["seats_mean"]) for p in d["seats"]}}
    movers = sorted(chg.get("parties", {}).items(), key=lambda kv: -abs(kv[1]))[:3] if chg else []
    movers = [(p, v) for p, v in movers if abs(v) >= 0.3]
    risk = [p for p in d["seats"] if 0.02 < p["p_threshold"] < 0.98]
    wk = d.get("delta")
    n_new = len(polls)
    in_model = [p for p in polls if p["in_model"]]
    held = [p for p in polls if not p["in_model"]]

    # --- בריף פרטי ---
    L = [f"📊 פרויקט 120 - עדכון {fmt_date(today)}", ""]
    L.append(f"גוש הימין {rc} ({right['seats_p05']}-{right['seats_p95']}) · סיכוי לרוב {p_maj}%")
    L.append(f"גוש השמאל {lc} ({left['seats_p05']}-{left['seats_p95']}) · המפלגות הערביות {ac} ({arab['seats_p05']}-{arab['seats_p95']})")
    if chg:
        L.append(f"מול הריצה הקודמת: גוש הימין {sign(chg['right_mean'], 1)} מנדטים, סיכוי לרוב {sign(chg['p_maj'])} נק'")
    if wk:
        wb = wk["blocs"]["גוש הימין"]
        L.append(f"מול {fmt_date(wk['since'])}: גוש הימין {sign(wb['seats'], 1)}, סיכוי לרוב {sign(round(wb['p_majority'] * 100))} נק'")
    L.append("")
    if polls:
        L.append(f"🆕 {n_new} סקרים חדשים:")
        for p in polls:
            b = p["blocs"]
            bl = f" · ימין {b.get('גוש הימין', '?')} / שמאל {b.get('גוש השמאל', '?')} / ערביות {b.get('המפלגות הערביות', '?')}" if b else ""
            st = "" if p["in_model"] else f" ⚠️ לא במודל: {p['reason']}"
            L.append(f"• {p['ref']} {p['pollster']}" + (f" ({p['publisher']})" if p["publisher"] else "") + (f", {fmt_date(p['date'])}" if p["date"] else "") + (f", n={p['n']}" if p["n"] else "") + bl + st)
    else:
        L.append("אין סקרים חדשים בריצה זו (ריצה יומית מלאה).")
    L.append("")
    if movers:
        L.append("↕️ זזו הכי הרבה (מנדטים, ממוצע): " + ", ".join(f"{p} {sign(v, 1)}" for p, v in movers))
    if risk:
        L.append("⚖️ על הסף: " + ", ".join(f"{p['party']} {round(p['p_threshold'] * 100)}% לעבור" for p in risk))
    dg = d["diagnostics"]
    g = dg.get("grade") or ("ok" if dg.get("converged") else "marginal")
    L.append({"ok": "✅ בדיקת תקינות: עברה", "marginal": "🟡 בדיקת תקינות: עברה עם הערה", "bad": "🔴 בדיקת תקינות: כשל - התוצאות זמניות"}[g]
             + (f" (ESS {dg.get('min_ess_bulk')}, R-hat {dg.get('max_r_hat')})" if dg.get("min_ess_bulk") else ""))
    L.append(f"{d['n_polls_model']} סקרים במודל מתוך {d['n_polls_all']} · {d['days_to_election']} ימים לבחירות")
    L.append(SITE)
    private = "\n".join(L)

    # --- טיוטה לפרסום ---
    P = [f"פרויקט 120 · עדכון תחזית {fmt_date(today)}", ""]
    P.append(f"גוש הימין: {rc} מנדטים (טווח {right['seats_p05']}-{right['seats_p95']}), סיכוי לרוב {p_maj}%.")
    P.append(f"גוש השמאל {lc}, המפלגות הערביות {ac}.")
    if in_model:
        names = sorted({p["pollster"] for p in in_model if p["pollster"]})
        P.append(f"נכנסו {len(in_model)} סקרים חדשים ({', '.join(names)}).")
    if wk:
        wb = wk["blocs"]["גוש הימין"]
        s = sign(wb["seats"], 1)
        P.append(f"מאז {fmt_date(wk['since'])}: גוש הימין {s} מנדטים" + ("." if s == "ללא שינוי" else f", הסיכוי לרוב {sign(round(wb['p_majority'] * 100))} נקודות."))
    if movers:
        P.append("הבולטים: " + ", ".join(f"{p} {sign(v, 1)}" for p, v in movers) + ".")
    if risk:
        P.append("על אחוז החסימה: " + ", ".join(f"{p['party']} ({round(p['p_threshold'] * 100)}% לעבור)" for p in risk) + ".")
    P.append(f"מבוסס על {d['n_polls_model']} סקרים שפורסמו רשמית באתר ועדת הבחירות. הפירוט המלא: {SITE}")
    public = "\n".join(P)

    card = {"today": fmt_date(today), "days": d["days_to_election"], "right": rc, "left": lc, "arab": ac,
            "right_rng": f"{right['seats_p05']}-{right['seats_p95']}", "left_rng": f"{left['seats_p05']}-{left['seats_p95']}", "arab_rng": f"{arab['seats_p05']}-{arab['seats_p95']}",
            "p_maj": p_maj, "n_polls": d["n_polls_model"], "n_new": len(in_model),
            "change": (f"מאז {fmt_date(wk['since'])}: גוש הימין {sign(wk['blocs']['גוש הימין']['seats'], 1)} · סיכוי לרוב {sign(round(wk['blocs']['גוש הימין']['p_majority'] * 100))} נק'" if wk else ""),
            "seats": [(p, cs.get(p, 0)) for b in ("גוש הימין", "המפלגות הערביות", "גוש השמאל") for p in d["bloc_def"][b] if cs.get(p, 0) > 0],
            "risk": ", ".join(f"{p['party']} {round(p['p_threshold'] * 100)}%" for p in risk)}
    return private, public, card


def hemicycle_svg(seats: list[tuple[str, int]]) -> str:
    """120 נקודות על 4 קשתות, מימין (ימין) לשמאל, כמו באתר."""
    import math
    order = [p for p, n in seats for _ in range(n)]
    rows = [(150, 26), (190, 30), (230, 32), (270, 32)]
    pts = []
    k = 0
    for r, n in rows:
        for i in range(n):
            a = math.pi * i / (n - 1)
            pts.append((400 + r * math.cos(a), 330 - r * math.sin(a), k)); k += 1
    # מיון לפי זווית (מימין לשמאל) כדי שהגושים יהיו רציפים
    pts.sort(key=lambda t: math.atan2(330 - t[1], t[0] - 400))
    out = []
    for i, (x, y, _) in enumerate(pts):
        col = PARTY_COLOR.get(order[i], "#6A7184") if i < len(order) else "#2A3145"
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13" fill="{col}"/>')
    out.append('<line x1="400" y1="40" x2="400" y2="120" stroke="#03A89E" stroke-width="3" stroke-dasharray="6 6"/>')
    out.append('<text x="400" y="30" text-anchor="middle" font-size="22" fill="#03A89E" font-weight="700">61</text>')
    return '<svg viewBox="0 0 800 350" width="800" height="350">' + "".join(out) + "</svg>"


CARD_HTML = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Suez+One&family=Assistant:wght@300;400;600;700&display=swap">
<style>
body{margin:0;width:1080px;height:1080px;background:radial-gradient(900px 500px at 50% -10%,rgba(3,168,158,.18),transparent 60%),#0B0F1A;color:#F1F3F8;font-family:Assistant,Arial,sans-serif;position:relative;overflow:hidden}
.top{display:flex;justify-content:space-between;align-items:center;padding:44px 60px 0}
.brand{font-family:'Suez One',serif;font-size:44px} .brand span{color:#03A89E}
.date{font-size:22px;color:#AEB5C6;font-weight:600;letter-spacing:.04em}
.hemi{margin:26px auto 0;width:800px;position:relative}
.big{position:absolute;left:50%;top:230px;transform:translateX(-50%);text-align:center;font-family:'Suez One',serif;font-size:74px;line-height:1}
.big small{display:block;font-family:Assistant;font-size:20px;color:#AEB5C6;font-weight:400}
.kpis{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;padding:0 60px;margin-top:10px}
.k{background:#151B2B;border:1px solid #242C40;border-radius:20px;padding:20px 22px 18px;border-inline-start:6px solid var(--c)}
.k .n{font-family:'Suez One',serif;font-size:64px;line-height:1;color:var(--c)}
.k .l{font-size:24px;font-weight:700;margin-top:6px} .k .r{font-size:19px;color:#AEB5C6}
.pm{margin:22px 60px 0;background:rgba(3,168,158,.12);border:1px solid #03A89E;border-radius:20px;padding:18px 26px;display:flex;justify-content:space-between;align-items:center}
.pm b{font-family:'Suez One',serif;font-size:54px;color:#03A89E;line-height:1} .pm span{font-size:26px;font-weight:600}
.chg{margin:18px 60px 0;font-size:24px;color:#AEB5C6;line-height:1.5}
.chg b{color:#F1F3F8}
.foot{position:absolute;bottom:34px;left:60px;right:60px;display:flex;justify-content:space-between;font-size:20px;color:#6F778C;border-top:1px solid #242C40;padding-top:16px}
.foot b{color:#AEB5C6;font-weight:600}
</style></head><body>
<div class="top"><div class="brand">פרויקט <span>120</span></div><div class="date">תחזית · __TODAY__ · __DAYS__ ימים לבחירות</div></div>
<div class="hemi">__HEMI__<div class="big">120<small>מושבים</small></div></div>
<div class="kpis">
 <div class="k" style="--c:#5B8AD6"><div class="n">__RIGHT__</div><div class="l">גוש הימין</div><div class="r">טווח __RIGHT_RNG__</div></div>
 <div class="k" style="--c:#2FA982"><div class="n">__LEFT__</div><div class="l">גוש השמאל</div><div class="r">טווח __LEFT_RNG__</div></div>
 <div class="k" style="--c:#E25A5A"><div class="n">__ARAB__</div><div class="l">המפלגות הערביות</div><div class="r">טווח __ARAB_RNG__</div></div>
</div>
<div class="pm"><span>הסיכוי שלגוש הימין יהיה רוב (61+)</span><b>__PMAJ__%</b></div>
<div class="chg">__CHANGE____RISK__</div>
<div class="foot"><div><b>__NPOLLS__ סקרים</b> שפורסמו רשמית באתר ועדת הבחירות · מודל בייסיאני</div><div>project120.co.il · ד"ר אהרון לאוטמן</div></div>
</body></html>"""


def render_card(card: dict, path: Path) -> None:
    html = (CARD_HTML.replace("__TODAY__", card["today"]).replace("__DAYS__", str(card["days"])).replace("__HEMI__", hemicycle_svg(card["seats"]))
            .replace("__RIGHT__", str(card["right"])).replace("__LEFT__", str(card["left"])).replace("__ARAB__", str(card["arab"]))
            .replace("__RIGHT_RNG__", card["right_rng"]).replace("__LEFT_RNG__", card["left_rng"]).replace("__ARAB_RNG__", card["arab_rng"])
            .replace("__PMAJ__", str(card["p_maj"])).replace("__NPOLLS__", str(card["n_polls"]))
            .replace("__CHANGE__", (card["change"] + "<br>") if card["change"] else "")
            .replace("__RISK__", (f"על אחוז החסימה: <b>{card['risk']}</b>" if card["risk"] else "")))
    (path.parent / "card.html").write_text(html, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
        pg.set_content(html, wait_until="networkidle")
        pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(500)
        pg.screenshot(path=str(path), full_page=False)
        b.close()


def telegram(token: str, method: str, **kw):
    import requests
    files = kw.pop("files", None)
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=kw, files=files, timeout=60)
    return r.json()


def chat_id(token: str) -> str | None:
    f = ROOT / "db" / "telegram.json"
    if os.environ.get("TELEGRAM_CHAT_ID"):
        return os.environ["TELEGRAM_CHAT_ID"]
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8")).get("chat_id")
    up = telegram(token, "getUpdates")
    if not up.get("ok"):
        print("Telegram:", up.get("error_code"), up.get("description"), "- הטוקן ב-secret TELEGRAM_BOT_TOKEN שגוי?")
        return None
    print(f"getUpdates: {len(up.get('result', []))} עדכונים")
    for u in reversed(up.get("result", [])):
        m = u.get("message") or u.get("channel_post")
        if m and m.get("chat", {}).get("type") == "private":
            cid = str(m["chat"]["id"])
            f.write_text(json.dumps({"chat_id": cid, "name": m["chat"].get("first_name", "")}, ensure_ascii=False), encoding="utf-8")
            return cid
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--no-card", action="store_true")
    a = ap.parse_args(argv)
    OUT.mkdir(exist_ok=True)
    d = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
    global BLOC_DEF
    BLOC_DEF = d["bloc_def"]
    conn = sqlite3.connect(ROOT / "db" / "polls.sqlite")
    polls = new_polls(conn, dt.date.today().isoformat())
    private, public, card = build_texts(d, load_prev_seats(), polls)
    (OUT / "private.txt").write_text(private, encoding="utf-8")
    (OUT / "public.txt").write_text(public, encoding="utf-8")
    print(private); print("\n--- טיוטה לפרסום ---\n" + public)
    card_path = OUT / "card.png"
    if not a.no_card:
        try:
            render_card(card, card_path)
            print("card:", card_path)
        except Exception as ex:
            print("card failed:", ex); card_path = None
    if a.send:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            print("אין TELEGRAM_BOT_TOKEN - לא נשלח"); return 0
        cid = chat_id(token)
        if not cid:
            print("לא נמצא צ'אט: שלח הודעה לבוט ואז הרץ שוב"); return 0
        telegram(token, "sendMessage", chat_id=cid, text=private, disable_web_page_preview="true")
        if card_path and card_path.exists():
            with open(card_path, "rb") as fh:
                telegram(token, "sendPhoto", chat_id=cid, caption="📣 טיוטה לפרסום (להעביר לערוץ):\n\n" + public[:900], files={"photo": ("card.png", fh, "image/png")})
        else:
            telegram(token, "sendMessage", chat_id=cid, text="📣 טיוטה לפרסום:\n\n" + public)
        print("נשלח לטלגרם", cid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
