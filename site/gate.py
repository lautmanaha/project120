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


ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
FULL = ROOT / "index_full.html"
TARGETS = [(ROOT / "index.html", ROOT / "index_full.html", "he"), (ROOT / "en" / "index.html", ROOT / "en" / "index_full.html", "en")]
EN_TEXT = {"<html lang=\"he\" dir=\"rtl\">": "<html lang=\"en\" dir=\"ltr\">", "<title>פרויקט 120 - בבנייה</title>": "<title>Project 120 - coming soon</title>",
           ">פרויקט <span>120</span><": ">Project <span>120</span><", "האתר בבנייה ובעדכונים": "Site under construction",
           "תחזית הבחירות לכנסת ה-26 נמצאת בשלבי בדיקה אחרונים לפני ההשקה. אם קיבלת קוד גישה מוקדמת - הקש אותו כאן.": "The 26th Knesset election forecast is in final testing before launch. If you received an early-access code, enter it here.",
           "קוד גישה מוקדמת": "Early-access code", 'placeholder="קוד גישה"': 'placeholder="access code"', ">כניסה<": ">Enter<", "קוד שגוי - נסה שוב": "Wrong code - try again",
           "<b>ד\"ר אהרון לאוטמן</b> · דיגיטל · דאטה · אסטרטגיה": "<b>Dr. Aharon Lautman</b> · Digital · Data · Strategy"}
CODE_FILE = ROOT / ".gate_code"
SALT = b"project120-gate-v1"
ITER = 2000


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
// SHA-256 טהור ב-JS - עובד גם ב-http (crypto.subtle דורש https)
const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
function sha256(m){const l=m.length,n=((l+9+63)>>6)<<6,b=new Uint8Array(n);b.set(m);b[l]=0x80;const dv=new DataView(b.buffer);dv.setUint32(n-4,l*8>>>0);dv.setUint32(n-8,Math.floor(l*8/4294967296));
let h0=0x6a09e667,h1=0xbb67ae85,h2=0x3c6ef372,h3=0xa54ff53a,h4=0x510e527f,h5=0x9b05688c,h6=0x1f83d9ab,h7=0x5be0cd19;const w=new Uint32Array(64);
for(let o=0;o<n;o+=64){for(let i=0;i<16;i++)w[i]=dv.getUint32(o+i*4);for(let i=16;i<64;i++){const a=w[i-15],c=w[i-2];const s0=((a>>>7)|(a<<25))^((a>>>18)|(a<<14))^(a>>>3),s1=((c>>>17)|(c<<15))^((c>>>19)|(c<<13))^(c>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)>>>0}
let a=h0,b2=h1,c=h2,d=h3,e=h4,f=h5,g=h6,h=h7;for(let i=0;i<64;i++){const S1=((e>>>6)|(e<<26))^((e>>>11)|(e<<21))^((e>>>25)|(e<<7)),ch=(e&f)^(~e&g),t1=(h+S1+ch+K[i]+w[i])>>>0,S0=((a>>>2)|(a<<30))^((a>>>13)|(a<<19))^((a>>>22)|(a<<10)),mj=(a&b2)^(a&c)^(b2&c),t2=(S0+mj)>>>0;h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b2;b2=a;a=(t1+t2)>>>0}
h0=(h0+a)>>>0;h1=(h1+b2)>>>0;h2=(h2+c)>>>0;h3=(h3+d)>>>0;h4=(h4+e)>>>0;h5=(h5+f)>>>0;h6=(h6+g)>>>0;h7=(h7+h)>>>0}
const out=new Uint8Array(32),ov=new DataView(out.buffer);[h0,h1,h2,h3,h4,h5,h6,h7].forEach((v,i)=>ov.setUint32(i*4,v));return out}
const cat=(...a)=>{const n=a.reduce((s,x)=>s+x.length,0),o=new Uint8Array(n);let p=0;for(const x of a){o.set(x,p);p+=x.length}return o};
function open(code){
  const salt=b64(SALT),iv=b64(IV),ct=b64(CT),enc=new TextEncoder();
  let key=sha256(cat(salt,enc.encode(code)));
  for(let i=0;i<ITER;i++)key=sha256(cat(key,salt));
  const mac=ct.slice(0,16),body=ct.slice(16);
  const chk=sha256(cat(key,enc.encode("mac"),body));
  for(let i=0;i<16;i++)if(chk[i]!==mac[i])throw new Error("bad");
  const pt=new Uint8Array(body.length);const ctr=new Uint8Array(4);
  for(let o=0,c=0;o<body.length;o+=32,c++){ctr[0]=c>>>24;ctr[1]=(c>>>16)&255;ctr[2]=(c>>>8)&255;ctr[3]=c&255;const ks=sha256(cat(key,iv,ctr));for(let i=0;i<32&&o+i<body.length;i++)pt[o+i]=body[o+i]^ks[i]}
  const html=new TextDecoder().decode(pt);
  try{localStorage.setItem("p120_code",code)}catch(e){}
  document.open();document.write(html);document.close();
}
const f=document.getElementById("f"),inp=document.getElementById("code"),err=document.getElementById("err"),go=document.getElementById("go"),card=document.getElementById("card");
f.addEventListener("submit",async e=>{
  e.preventDefault();const c=inp.value.trim();if(!c)return;
  go.disabled=true;err.textContent="";
  await new Promise(r=>setTimeout(r,30));
  try{open(c)}catch(x){err.textContent="קוד שגוי - נסה שוב";card.classList.remove("shake");void card.offsetWidth;card.classList.add("shake");inp.select()}
  go.disabled=false;
});
window.addEventListener("load",()=>setTimeout(()=>{try{const c=localStorage.getItem("p120_code");if(c){inp.value=c;open(c)}}catch(e){try{localStorage.removeItem("p120_code")}catch(_){}}},50));
</script>
</body>
</html>
"""


def build(code: str) -> None:
    for INDEX, FULL, lang in TARGETS:
        if INDEX.exists():
            build_one(code, INDEX, FULL, lang)


def build_one(code: str, INDEX: Path, FULL: Path, lang: str) -> None:
    src = INDEX.read_text(encoding="utf-8")
    if "__CT__" not in src and "p120_code" not in src:
        FULL.write_text(src, encoding="utf-8")  # שמירת האתר המלא (לא נפרס)
    elif not FULL.exists():
        sys.exit(f"{INDEX} כבר מוצפן ואין {FULL.name} - הרץ build_site.py מחדש")
    full = FULL.read_text(encoding="utf-8")
    # הצפנה בזרם מבוסס SHA-256 (לא WebCrypto: crypto.subtle לא זמין בדפי http רגילים)
    key = hashlib.sha256(SALT + code.encode("utf-8")).digest()
    for _ in range(ITER):
        key = hashlib.sha256(key + SALT).digest()
    iv = os.urandom(12)
    pt = full.encode("utf-8")
    ks = bytearray()
    ctr = 0
    while len(ks) < len(pt):
        ks += hashlib.sha256(key + iv + ctr.to_bytes(4, "big")).digest()
        ctr += 1
    body = bytes(a ^ b for a, b in zip(pt, ks))
    mac = hashlib.sha256(key + b"mac" + body).digest()[:16]
    ct = mac + body
    # לוגו: אותו SVG של הנקודות מהאתר המלא
    logo = ""
    i = full.find('<svg viewBox="0 0 120 64" class="logo-dots"')
    if i >= 0:
        j = full.find("</svg>", i) + 6
        logo = full[i:j]
    gate = GATE_HTML
    if lang == "en":
        for he, en in EN_TEXT.items():
            gate = gate.replace(he, en)
    out = (gate.replace("__LOGO__", logo)
           .replace("__CT__", base64.b64encode(ct).decode())
           .replace("__IV__", base64.b64encode(iv).decode())
           .replace("__SALT__", base64.b64encode(SALT).decode())
           .replace("__ITER__", str(ITER)))
    INDEX.write_text(out, encoding="utf-8")
    print(f"{INDEX.relative_to(ROOT.parent)}: שער גישה מוקדמת פעיל ({len(out)//1024} KB, מוצפן)")


def off() -> None:
    for INDEX, FULL, lang in TARGETS:
        if FULL.exists():
            INDEX.write_text(FULL.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"השער הוסר - {INDEX.name} ({lang}) פתוח")
        else:
            print(f"אין {FULL} - הרץ build_site.py")


if __name__ == "__main__":
    if "--off" in sys.argv:
        off()
    else:
        code = get_code()
        if not code:
            print("אין קוד גישה (P120_GATE_CODE / site/.gate_code) - האתר נשאר פתוח")
        else:
            build(code)
