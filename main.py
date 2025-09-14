from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from pdfminer.high_level import extract_text
from datetime import datetime
from io import BytesIO
import re

import fitz  # PyMuPDF
from PIL import Image
import io
import pytesseract

app = FastAPI()

def extract_info(text: str):
    # Datum -> YYYY-MM-DD
    date_norm = None
    for pat, fmt in [
        (r'(\d{4}-\d{2}-\d{2})', '%Y-%m-%d'),
        (r'(\d{2}\.\d{2}\.\d{4})', '%d.%m.%Y'),
        (r'(\d{2}/\d{2}/\d{4})', '%d/%m/%Y'),
    ]:
        m = re.search(pat, text)
        if m:
            raw = m.group(1)
            try:
                date_norm = datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
                break
            except Exception:
                pass
    if not date_norm:
        date_norm = datetime.utcnow().strftime('%Y-%m-%d')

    # Betrag (letzte Summe)
    amount = "0.00"
    cand = re.findall(r'\b\d{1,3}(?:\.\d{3})*,\d{2}\b|\b\d+\.\d{2}\b|\b\d+,\d{2}\b', text)
    if cand:
        amt = cand[-1]
        if ',' in amt and '.' in amt:
            amt = amt.replace('.', '').replace(',', '.')
        elif ',' in amt:
            amt = amt.replace(',', '.')
        amount = amt

    # Absender
    sender = "Unbekannt"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    company_re = re.compile(r'\b(GmbH|AG|UG|KG|OHG|GbR|e\.V\.|gGmbH|SE|KGaA|GmbH & Co\.)\b', re.I)
    for ln in lines[:30]:
        if company_re.search(ln):
            sender = ln
            break
    if sender == "Unbekannt" and lines:
        sender = lines[0][:80]
    sender = re.sub(r'[\\/*?"<>|]', '', sender)

    # Typ
    lower = text.lower()
    typ = "Dokument"
    for key, label in [
        ("rechnung", "Rechnung"),
        ("angebot", "Angebot"),
        ("quittung", "Quittung"),
        ("bescheid", "Bescheid"),
        ("mahnung", "Mahnung"),
        ("vertrag", "Vertrag"),
        ("lieferschein", "Lieferschein"),
    ]:
        if key in lower:
            typ = label
            break

    # Kurzfassung
    short = re.sub(r'\s+', ' ', text.strip())[:200]

    return {
        "typ": typ,
        "absender": sender,
        "datum": date_norm,
        "betrag": amount,
        "kurzfassung": short
    }

def ocr_pdf_bytes(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    parts = []
    for page in doc:
        pix = page.get_pixmap(dpi=300, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
        try:
            txt = pytesseract.image_to_string(img, lang="deu+eng")
        except Exception:
            txt = pytesseract.image_to_string(img)  # Fallback nur ENG
        parts.append(txt)
    return "\n".join(parts)

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        data = await file.read()
        # 1) Versuch: echter Text
        text = extract_text(BytesIO(data)) or ""
        text_norm = re.sub(r'\s+', ' ', text).strip()

        # 2) Fallback OCR, wenn zu wenig Text
        if len(text_norm) < 20:
            text = ocr_pdf_bytes(data)

        result = extract_info(text or "")

    except Exception as e:
        result = {
            "typ": "Unbekannt",
            "absender": "Fehler",
            "datum": datetime.utcnow().strftime('%Y-%m-%d'),
            "betrag": "0.00",
            "kurzfassung": f"Analysefehler: {e}"
        }

    return JSONResponse(content=result)
