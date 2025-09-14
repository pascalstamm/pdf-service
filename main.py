from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from pdfminer.high_level import extract_text
from datetime import datetime, timedelta
from io import BytesIO
import re
import fitz  # PyMuPDF
from PIL import Image
import pytesseract

app = FastAPI()

# -------------------------------------------------------------------
# Hilfsfunktionen für Datumserkennung
# -------------------------------------------------------------------

MONTHS_DE = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12
}

DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})\.\s*([A-Za-zäÄöÖüÜß]+)\s+(\d{4})\b"), "d_mon_y"),
    (re.compile(r"\b(\d{1,2})\s*([A-Za-zäÄöÖüÜß]{3,})\s+(\d{4})\b"), "d_monabbr_y"),
]

BIRTH_HINTS = re.compile(r"\b(geburtsdatum|geb\.|geb am|geburtstag|dob|birth)\b", re.I)
DOCDATE_HINTS_POS = re.compile(r"\b(rechnungsdatum|ausgestellt|ausfertigung|bescheid\s+vom|schreiben\s+vom|datum|vom|stand)\b", re.I)
NEG_HINTS = re.compile(r"\b(geburtsurkunde|stammbuch)\b", re.I)


def _to_iso(y: int, m: int, d: int) -> str | None:
    try:
        return datetime(y, m, d).strftime("%Y-%m-%d")
    except Exception:
        return None


def normalize_date(raw: str) -> str | None:
    s = raw.strip()
    for rx, kind in DATE_PATTERNS:
        m = rx.search(s)
        if not m:
            continue
        if kind == "iso":
            y, m_, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return _to_iso(y, m_, d)
        if kind == "dmy":
            d, m_, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return _to_iso(y, m_, d)
        if kind == "d_mon_y":
            d, mon, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
            mon = MONTHS_DE.get(mon, MONTHS_DE.get(mon.replace("ä","ae").replace("ö","oe").replace("ü","ue"), 0))
            if mon:
                return _to_iso(y, mon, d)
        if kind == "d_monabbr_y":
            d, mon, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
            for k, v in MONTHS_DE.items():
                if mon.startswith(k[:3]):
                    return _to_iso(y, v, d)
    return None


def choose_document_date(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    now = datetime.utcnow()
    recent_10y = now - timedelta(days=365*10)

    candidates = []
    for idx, ln in enumerate(lines):
        ln_clean = re.sub(r"\s+", " ", ln).strip()
        for rx, _ in DATE_PATTERNS:
            for m in rx.finditer(ln_clean):
                raw = m.group(0)
                iso = normalize_date(raw)
                if not iso:
                    continue
                y = int(iso[:4])

                score = 0
                lo = ln_clean.lower()

                if BIRTH_HINTS.search(lo):
                    score -= 20
                if DOCDATE_HINTS_POS.search(lo):
                    score += 10
                if NEG_HINTS.search(lo):
                    score -= 5

                try:
                    dt = datetime.strptime(iso, "%Y-%m-%d")
                    if dt >= recent_10y:
                        score += 6
                    else:
                        score -= 2
                    if dt > now + timedelta(days=31):
                        score -= 5
                except Exception:
                    pass

                if idx < 40:
                    score += 2
                if y <= 1985:
                    score -= 6

                candidates.append({"iso": iso, "score": score})

    if not candidates:
        return now.strftime("%Y-%m-%d")

    candidates.sort(key=lambda c: (c["score"], c["iso"]), reverse=True)
    return candidates[0]["iso"]

# -------------------------------------------------------------------
# Text-Extraktion (PDF / OCR)
# -------------------------------------------------------------------

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    text = ""
    try:
        text = extract_text(BytesIO(pdf_bytes)) or ""
    except Exception:
        pass

    if text.strip():
        return text

    # Fallback OCR
    ocr_text = []
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in pdf_doc:
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        ocr_text.append(pytesseract.image_to_string(img, lang="deu"))
    return "\n".join(ocr_text)


# -------------------------------------------------------------------
# Analyse: Datum, Betrag, Absender, Typ, Kurzfassung
# -------------------------------------------------------------------

def extract_info(text: str) -> dict:
    result = {
        "datum": choose_document_date(text),
        "betrag": None,
        "absender": None,
        "typ": None,
        "kurzfassung": None
    }

    # Betrag
    m = re.findall(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b", text)
    if m:
        result["betrag"] = m[-1]

    # Absender (erste große Überschrift / Firma oben im Dokument)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        result["absender"] = lines[0][:50]

    # Typ-Erkennung (einfach)
    if "rechnung" in text.lower():
        result["typ"] = "Rechnung"
    elif "bescheid" in text.lower():
        result["typ"] = "Bescheid"
    elif "vertrag" in text.lower():
        result["typ"] = "Vertrag"
    else:
        result["typ"] = "Dokument"

    # Kurzfassung (erste 200 Zeichen)
    result["kurzfassung"] = text[:200].replace("\n", " ")

    return result


# -------------------------------------------------------------------
# FastAPI Endpunkte
# -------------------------------------------------------------------

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    text = extract_text_from_pdf(pdf_bytes)
    info = extract_info(text)
    return JSONResponse(content=info)


@app.get("/")
async def root():
    return {"status": "ok", "message": "PDF Service läuft"}
