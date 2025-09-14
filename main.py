from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io

app = FastAPI(title="PDF Text Extractor", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extract_text")
async def extract_text_from_pdf(file: UploadFile = File(...)):
    try:
        # PDF einlesen
        pdf_bytes = await file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        full_text = []

        for page_num in range(len(doc)):
            page = doc[page_num]

            # 1. Text direkt aus der PDF extrahieren
            text = page.get_text("text")
            if text.strip():
                full_text.append(text)
                continue  # OCR nur, wenn kein Text gefunden

            # 2. OCR als Fallback (Bildseite)
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            ocr_text = pytesseract.image_to_string(img, lang="deu+eng")
            full_text.append(ocr_text)

        return JSONResponse(content={
            "status": "ok",
            "text": "\n".join(full_text)
        })

    except Exception as e:
        return JSONResponse(content={
            "status": "error",
            "message": str(e)
        }, status_code=500)
