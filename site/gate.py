#!/usr/bin/env python3
"""
פרויקט 120 - שער גישה מוקדמת.

עוטף את site/index.html (האתר המלא) בדף "האתר בבנייה" שמבקש קוד גישה.
האתר המלא מוצפן (AES-GCM, מפתח נגזר מהקוד ב-PBKDF2) בתוך הדף, ומפוענח בדפדפן
רק אחרי הקשת הקוד הנכון - כך שהתוכן לא נקרא מ"הצג מקור".

הקוד נלקח ממשתנה הסביבה P120_GATE_CODE או מהקובץ site/.gate_code (לא ב-git).
אם אין קוד - הסקריפט לא עושה כלום (האתר נשאר פתוח).

שימוש:  python3 site/gate.py            (אחרי build_site.py)
        python3 site/gate.py --off      (מסיר את השער: משחזר index.html מ-index_full.html)
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
FULL = ROOT / "index_full.html"
CODE_FILE = ROOT / ".gate_code"
SALT = b"project120-gate-v1"
ITER = 150_000


def get_code() -> str | None:
    c = os.environ.get("P120_GATE_CODE", "").strip()
    if not c and CODE_FILE.exists():
        c = CODE_FILE.read_text(encoding="utf-8").strip()
    return c or None


GATE_HTML = r"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>פרויקט 120 - בבנייה</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Suez+One&family=Alef:wght@400;700&family=Assistant:wght@300;400;600;700&display=swap">
<style>
:root{--bg:#0B0F1A;--surface:#151B2B;--ink:#F1F3F8;--ink-2:#AEB5C6;--ink-3:#6F778C;--line:#242C40;--brand:#03A89E;--brand-soft:rgba(3,168,158,.14);--bad:#E25A5A;color-scheme:dark}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:radial-gradient(900px 500px at 50% -10%,var(--brand-soft),transparent 60%),var(--bg);color:var(--ink);font-family:"Assistant","Arial Hebrew",Arial,sans-serif;display:grid;place-items:center;padding:24px}
.card{width:min(440px,100%);background:var(--surface);border:1px solid var(--line);border-radius:22px;padding:36px 32px 28px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.45)}
.logo svg{height:64px;width:auto;display:block;margin:0 auto 6px}
.logo-dots circle{fill:var(--ink)} .logo-dots circle.k{fill:var(--brand)}
.wm{font-family:"Suez One",serif;font-size:34px;line-height:1;margin-bottom:22px}
.wm span{color:var(--brand)}
h1{font-family:"Alef",Arial,sans-serif;font-size:22px;margin:0 0 8px}
p{color:var(--ink-2);font-size:15.5px;line-height:1.6;margin:0 0 22px;font-weight:300}
label{display:block;font-size:13px;color:var(--ink-3);margin-bottom:8px;font-weight:600;letter-spacing:.04em}
form{display:flex;gap:8px}
input{flex:1;font:inherit;font-size:20px;letter-spacing:.2em;text-align:center;direction:ltr;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:12px;padding:12px 14px;outline:none;transition:border-color .15s,box-shadow .15s}
input:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}
button{font:inherit;font-weight:700;font-size:15px;background:var(--brand);color:#04110F;border:0;border-radius:12px;padding:12px 18px;cursor:pointer;transition:transform .15s,filter .15s}
button:hover{filter:brightness(1.08);transform:translateY(-1px)}
button:disabled{opacity:.6;cursor:wait}
.err{color:var(--bad);font-size:13.5px;min-height:20px;margin-top:12px}
.shake{animation:sh .35s}
@keyframes sh{0%,100%{transform:none}20%,60%{transform:translateX(-6px)}40%,80%{transform:translateX(6px)}}
.foot{margin-top:26px;padding-top:18px;border-top:1px solid var(--line);font-size:12.5px;color:var(--ink-3)}
.foot b{color:var(--ink-2)}
</style>
</head>
<body>
<div class="card" id="card">
  <div class="logo">__LOGO__</div>
  <div class="wm">פרויקט <span>120</span></div>
  <h1>האתר בבנייה ובעדכונים</h1>
  <p>תחזית הבחירות לכנסת ה-26 נמצאת בשלבי בדיקה אחרונים לפני ההשקה. אם קיבלת קוד גישה מוקדמת - הקש אותו כאן.</p>
  <form id="f" autocomplete="off">
    <label for="code" style="display:none">קוד גישה מוקדמת</label>
    <input id="code" inputmode="numeric" placeholder="קוד גישה" aria-label="קוד גישה מוקדמת" autofocus>
    <button id="go" type="submit">כניסה</button>
  </form>
  <div class="err" id="err"></div>
  <div class="foot"><b>ד"ר אהרון לאוטמן</b> · דיגיטל · דאטה · אסטרטגיה</div>
</div>
<script>
const CT="__CT__", IV="__IV__", SALT="__SALT__", ITER=__ITER__;
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function key(code){
  const km=await crypto.subtle.importKey("raw",new TextEncoder().encode(code),"PBKDF2",false,["deriveKey"]);
  return crypto.subtle.deriveKey({name:"PBKDF2",salt:b64(SALT),iterations:ITER,hash:"SHA-256"},km,{name:"AES-GCM",length:256},false,["decrypt"]);
}
async function open(code){
  const k=await key(code);
  const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:b64(IV)},k,b64(CT));
  const html=new TextDecoder().decode(pt);
  try{localStorage.setItem("p120_code",code)}catch(e){}
  document.open();document.write(html);document.close();
}
const f=document.getElementById("f"),inp=document.getElementById("code"),err=document.getElementById("err"),go=document.getElementById("go"),card=document.getElementById("card");
f.addEventListener("submit",async e=>{
  e.preventDefault();const c=inp.value.trim();if(!c)return;
  go.disabled=true;err.textContent="";
  try{await open(c)}catch(x){err.textContent="קוד שגוי - נסה שוב";card.classList.remove("shake");void card.offsetWidth;card.classList.add("shake");inp.select()}
  go.disabled=false;
});
(async()=>{try{const c=localStorage.getItem("p120_code");if(c){inp.value=c;await open(c)}}catch(e){try{localStorage.removeItem("p120_code")}catch(_){}}})();
</script>
</body>
</html>
"""


def build(code: str) -> None:
    src = INDEX.read_text(encoding="utf-8")
    if "__CT__" not in src and "p120_code" not in src:
        FULL.write_text(src, encoding="utf-8")  # שמירת האתר המלא (לא נפרס)
    elif not FULL.exists():
        sys.exit("index.html כבר מוצפן ואין index_full.html - הרץ build_site.py מחדש")
    full = FULL.read_text(encoding="utf-8")
    key = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), SALT, ITER, dklen=32)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, full.encode("utf-8"), None)
    # לוגו: אותו SVG של הנקודות מהאתר המלא
    logo = ""
    i = full.find('<svg viewBox="0 0 120 64" class="logo-dots"')
    if i >= 0:
        j = full.find("</svg>", i) + 6
        logo = full[i:j]
    out = (GATE_HTML.replace("__LOGO__", logo)
           .replace("__CT__", base64.b64encode(ct).decode())
           .replace("__IV__", base64.b64encode(iv).decode())
           .replace("__SALT__", base64.b64encode(SALT).decode())
           .replace("__ITER__", str(ITER)))
    INDEX.write_text(out, encoding="utf-8")
    print(f"site/index.html: שער גישה מוקדמת פעיל ({len(out)//1024} KB, מוצפן)")


def off() -> None:
    if FULL.exists():
        INDEX.write_text(FULL.read_text(encoding="utf-8"), encoding="utf-8")
        print("השער הוסר - index.html פתוח")
    else:
        print("אין index_full.html - הרץ build_site.py")


if __name__ == "__main__":
    if "--off" in sys.argv:
        off()
    else:
        code = get_code()
        if not code:
            print("אין קוד גישה (P120_GATE_CODE / site/.gate_code) - האתר נשאר פתוח")
        else:
            build(code)
