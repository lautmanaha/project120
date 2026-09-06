#!/usr/bin/env python3
"""
פרויקט 120 - חילוץ אוטומטי של תוצאות סקר מקובץ PDF באמצעות Claude (ראייה ממוחשבת).

לכל PDF חדש ב-data/pdfs שאין לו עדיין data/extracted/cec_<ref>.json:
  1. מרנדר את כל העמודים ל-PNG (data/pages).
  2. שולח את התמונות + מפרט החילוץ (data/EXTRACTION_SPEC.md) ל-Claude.
  3. שומר את ה-JSON שחזר, אחרי אימות בסיסי (מבנה, שמות מפלגות, סכום מנדטים).

דורש: pip install anthropic pypdfium2   וגם משתנה סביבה ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "data" / "EXTRACTION_SPEC.md"
PDF_DIR = ROOT / "data" / "pdfs"
PAGES_DIR = ROOT / "data" / "pages"
OUT_DIR = ROOT / "data" / "extracted"
MODEL = os.environ.get("P120_CLAUDE_MODEL", "claude-sonnet-4-5")

CANON = {"ישר", "הליכוד", "ביחד", "הדמוקרטים", "ישראל ביתנו", "יהדות התורה", "עוצמה יהודית", "ש\"ס",
         "הרשימה המשותפת", "רע\"ם", "עמך ישראל", "הציונות הדתית", "זהות", "בית ציוני", "הציבור החרדי",
         "הכלכלית החדשה", "כחול לבן", "האחדות", "מפלגת הקהל", "מקום לכולנו", "ברית אחים", "נעם", "עוז",
         "חופש כלכלי", "אחר"}


def render_pages(pdf_path: Path, ref: str) -> list[Path]:
    import pypdfium2 as pdfium
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    out = []
    for i in range(len(pdf)):
        p = PAGES_DIR / f"cec_{ref}_p{i + 1}.png"
        if not p.exists():
            pdf[i].render(scale=1.6).to_pil().save(p)
        out.append(p)
    return out


def _png_b64(path: Path, max_side: int = 1600) -> str:
    from PIL import Image
    im = Image.open(path)
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def validate(d: dict, ref: str) -> list[str]:
    errs = []
    if str(d.get("ref")) != ref:
        errs.append(f"ref mismatch {d.get('ref')} != {ref}")
    for q in d.get("questions", []):
        for r in q.get("results", []):
            if r.get("party") not in CANON:
                errs.append(f"party not canonical: {r.get('party')}")
        seats = [r.get("seats") for r in q.get("results", []) if r.get("seats") is not None]
        if seats and sum(seats) != 120:
            errs.append(f"q{q.get('qid')} seats sum {sum(seats)} != 120")
    return errs


def extract_one(ref: str, pdf_path: Path, meta_hint: dict | None = None, retries: int = 2) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    spec = SPEC.read_text(encoding="utf-8")
    pages = render_pages(pdf_path, ref)
    content: list[dict] = [{"type": "text", "text":
        f"Extract poll cec_{ref} according to the spec below. The CEC registry says: "
        f"{json.dumps(meta_hint or {}, ensure_ascii=False)}. Use it only to fill pollster/commissioner "
        f"if the PDF itself does not name them.\n\n=== SPEC ===\n{spec}\n\n"
        f"Return ONLY the JSON object, no prose, no code fences."}]
    for i, p in enumerate(pages):
        content.append({"type": "text", "text": f"--- page {i + 1} of {len(pages)} ---"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": _png_b64(p)}})
    last_err = ""
    for attempt in range(retries + 1):
        msgs = [{"role": "user", "content": content}]
        if last_err:
            msgs[0]["content"] = content + [{"type": "text", "text":
                f"Your previous answer failed validation: {last_err}. Fix it and return the full JSON again."}]
        resp = client.messages.create(model=MODEL, max_tokens=8000, temperature=0, messages=msgs)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        try:
            d = json.loads(text)
        except json.JSONDecodeError as e:
            last_err = f"invalid JSON: {e}"
            continue
        errs = validate(d, ref)
        if not errs:
            return d
        last_err = "; ".join(errs)
        d["extraction_notes"] = (d.get("extraction_notes") or "") + f" [VALIDATION: {last_err}]"
        candidate = d
    # החזרת הניסיון האחרון עם דגל, כדי שאדם יבדוק
    candidate["needs_review"] = True
    return candidate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "db" / "polls.sqlite"))
    ap.add_argument("--only", nargs="*", help="refs ספציפיים")
    ap.add_argument("--force", action="store_true", help="לחלץ מחדש גם אם קיים JSON")
    args = ap.parse_args(argv)

    import sqlite3
    conn = sqlite3.connect(args.db)
    meta = {r[0]: {"survey_editor": r[1], "survey_publisher": r[2], "survey_date": r[3]}
            for r in conn.execute("SELECT reference_number, survey_editor, survey_publisher, survey_date FROM polls_meta")}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    todo = []
    for pdf in sorted(PDF_DIR.glob("cec_*.pdf")):
        ref = pdf.stem.split("_", 1)[1]
        if args.only and ref not in args.only:
            continue
        if (OUT_DIR / f"cec_{ref}.json").exists() and not args.force:
            continue
        todo.append((ref, pdf))
    if not todo:
        print("אין PDF חדשים לחילוץ.")
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("חסר ANTHROPIC_API_KEY - לא ניתן לחלץ אוטומטית. הקבצים ממתינים:", [r for r, _ in todo], file=sys.stderr)
        return 3
    flagged = []
    for ref, pdf in todo:
        print(f"מחלץ {ref} ...", end=" ", flush=True)
        d = extract_one(ref, pdf, meta.get(ref))
        (OUT_DIR / f"cec_{ref}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        if d.get("needs_review"):
            flagged.append(ref)
            print("נשמר - דורש בדיקה ידנית")
        else:
            print("נשמר")
    if flagged:
        print("דורשים בדיקה ידנית:", flagged, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
