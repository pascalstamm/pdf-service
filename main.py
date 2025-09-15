from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from pdfminer.high_level import extract_text
from datetime import datetime
from io import BytesIO
import re
import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import openai
import os

app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI-Key aus Environment-Variable laden
openai.api_key = os.getenv("OPENAI_API_KEY")

def extract_info(text: str) -> dict:
    # Datum
    date_norm = choose_document_date(text)

    # Betrag (letzte Summe im Dokument)
    m = re.findall(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b", text)
    betrag = m[-1] if m else None

    # Absender (erste nicht-leere Zeile mit Buchstaben)
    absender = ""
    for line in text.splitlines():
        if re.search(r"[A-Za-z]", line) and len(line.strip()) > 3:
            absender = line.strip()
            break
    if not absender:
        absender = "Unbekannt"

    # Typ (einfache Regeln)
    low = text.lower()
    if "rechnung" in low:
        typ = "Rechnung"
    elif "bescheid" in low:
        typ = "Bescheid"
    elif "vertrag" in low:
        typ = "Vertrag"
    else:
        typ = "Dokument"

    # Kurzfassung (erste 200 Zeichen)
    kurz = text[:200].replace("\n", " ")

    # Dateiname-Vorschlag bauen
    safe_typ = typ.replace(" ", "_").replace("/", "-").replace(":", "-")
    safe_abs = absender.replace(" ", "_").replace("/", "-").replace(":", "-")[:50]
    vorschlag = f"{date_norm}_{safe_typ}_{safe_abs}.pdf"

    return {
        "datum": date_norm,
        "betrag": betrag,
        "absender": absender,
        "typ": typ,
        "kurzfassung": kurz,
        "vorschlag": vorschlag
    }


def extract_text_with_ocr(file_bytes: bytes) -> str:
    """Versuche zuerst pdfminer, wenn nichts kommt → OCR mit PyMuPDF + Tesseract"""
    text = extract_text(BytesIO(file_bytes))
    if text and len(text.strip()) > 30:
        return text

    text = ""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text += pytesseract.image_to_string(img, lang="deu")
    return text

def summarize_text(text: str) -> str:
    """Erstellt mit OpenAI eine Kurzfassung des Dokuments"""
    try:
        prompt = f"Fasse folgendes Dokument in 2-3 Sätzen knapp zusammen:\n\n{text[:2000]}"
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Du bist ein Assistent für Dokumentenauswertung."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Fehler bei OpenAI: {e}"

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    file_bytes = await file.read()
    text = extract_text_with_ocr(file_bytes)
    info = extract_info(text)
    info["kurzfassung"] = summarize_text(text)
    return JSONResponse(content=info)
