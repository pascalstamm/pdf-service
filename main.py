from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from pdfminer.high_level import extract_text
import fitz  # PyMuPDF
import pytesseract
from io import BytesIO
from PIL import Image
import tempfile
import os

app = FastAPI(title="PDF Text Extractor", version="1.0.0")

# Optional: Falls Tesseract nicht im PATH ist, hier aktivieren & anpassen.
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


@app.get("/health")
def health():
    return {"status": "ok"}


def _is_probably_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(5)
        return head == b"%PDF-"
    except Exception:
        return False


@app.post("/extract_text")
async def extract_text_from_pdf(file: UploadFile = File(...)):
    """
    Nimmt eine PDF-Datei entgegen und liefert extrahierten Text zurück.
    Ablauf:
      1) pdfminer (digitale PDFs mit Textebene)
      2) Fallback: OCR (Scans) mit Tesseract über gerenderte 300 DPI Bilder
    """
    tmp_path = None
    try:
        # Datei zwischenspeichern
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        # Sanity-Check: ist es wirklich eine PDF?
        if not _is_probably_pdf(tmp_path):
            os.remove(tmp_path)
            return JSONResponse(
                content={"status": "error", "message": "Upload ist keine gültige PDF-Datei."},
                status_code=400,
            )

        # 1) Direktextraktion (digitale PDFs)
        try:
            direct_text = extract_text(tmp_path)
        except Exception as e:
            direct_text = ""
            direct_err = str(e)
        else:
            direct_err = None

        if direct_text and direct_text.strip():
            os.remove(tmp_path)
            return {"status": "ok", "method": "pdfminer", "text": direct_text}

        # 2) Fallback: OCR (Scans)
        try:
            doc = fitz.open(tmp_path)
            ocr_chunks = []
            # 300 DPI Render für bessere OCR
            zoom = 300 / 72.0  # 72 DPI Basis
            mat = fitz.Matrix(zoom, zoom)

            for page in doc:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_bytes = pix.tobytes("png")
                img = Image.open(BytesIO(img_bytes))
                txt = pytesseract.image_to_string(img, lang="deu+eng")
                ocr_chunks.append(txt)
            doc.close()

            os.remove(tmp_path)
            return {"status": "ok", "method": "ocr", "text": "\n".join(ocr_chunks)}
        except Exception as e:
            # Wenn OCR scheitert, gib eine klare Meldung aus (z.B. Tesseract nicht installiert)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            msg = "OCR fehlgeschlagen: " + str(e)
            if direct_err:
                msg += f" | pdfminer: {direct_err}"
            return JSONResponse(content={"status": "error", "message": msg}, status_code=500)

    except Exception as e:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        return JSONResponse(
            content={"status": "error", "message": f"Allgemeiner Fehler: {str(e)}"},
            status_code=500,
        )
