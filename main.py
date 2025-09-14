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

def extract_info(text: str):
    # Datum -> YYYY-MM-DD
    date_norm = None
    for pat, fmt in [
        (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"(\d{2}\.\d{2}\.\d{4})", "%d.%m.%Y"),
        (r"(\d{2}/\d{2}/\d{4})", "%d/%m/%Y"),
    ]:
        m = re.search(pat, text)
        if m:
            raw = m.group(1)
            try:
                date_norm = datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                break
            except Exception:
                pass
    if not date_norm:
        date_norm = datetime.utcnow().strftime("%Y-%m-%d")

    # Betrag (letzte Summe im Dokument)
    amount_match = re.findall(r"(\d+[.,]\d{2}) ?€", text)
    betrag = amount_match[-1] if amount_match else ""

    # Absender (erste Zeile mit Buchstaben)
    absender = ""
    for line in text.splitlines():
        if re.search(r"[A-Za-z]", line) and len(line.strip()) > 3:
            absender = line.strip()
            break

    # Typ (sehr einfache Regel, wird später erweitert)
    typ = "Rechnung" if "Rechnung" in text else "Dokument"

    return {
        "datum": date_norm,
        "betrag": betrag,
        "absender": absender,
        "typ": typ,
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
