from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from pdfminer.high_level import extract_text
from io import BytesIO
from datetime import datetime
import re

app = FastAPI()

def extract_info(text: str):
    # --- Datum (normalisiert zu YYYY-MM-DD) ---
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

    # --- Betrag (nimmt letzte Summe im Dokument) ---
    amount = "0.00"
    cand = re.findall(r'\b\d{1,3}(?:\.\d{3})*,\d{2}\b|\b\d+\.\d{2}\b|\b\d+,\d{2}\b', text)
    if cand:
        amt = cand[-1]
        if ',' in amt and '.' in amt:
            amt = amt.replace('.', '').replace(',', '.')
        elif ',' in amt:
            amt = amt.replace(',', '.')
        amount = amt

    # --- Absender (erste Zeilen, die wie Firmen aussehen) ---
    sender = "Unbekannt"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    company_re = re.compile(r'\b(GmbH|AG|UG|KG|OHG|GbR|e\.V\.|gGmbH|SE|KGaA|GmbH & Co\.)\b', re.I)
    for ln in lines[:25]:
        if company_re.search(ln):
            sender = ln
            break
    if sender == "Unbekannt" and lines:
        sender = lines[0][:80]
    sender = re.sub(r'[\\/*?"<>|]', '', sender)  # unerlaubte Zeichen entfernen

    # --- Typ ---
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

    # --- Kurzfassung (erste 200 Zeichen kompakt) ---
    short = re.sub(r'\s+', ' ', text.strip())[:200]

    return {
        "typ": typ,
        "absender": sender,
        "datum": date_norm,
        "betrag": amount,
        "kurzfassung": short
    }

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    try:
        data = await file.read()
        text = extract_text(BytesIO(data)) or ""
        result = extract_info(text)
    except Exception as e:
        result = {
            "typ": "Unbekannt",
            "absender": "Fehler",
            "datum": datetime.utcnow().strftime('%Y-%m-%d'),
            "betrag": "0.00",
            "kurzfassung": f"Analysefehler: {e}"
        }
    return JSONResponse(content=result)
