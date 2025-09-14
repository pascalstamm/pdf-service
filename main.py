from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

app = FastAPI()

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    Nimmt eine PDF entgegen und gibt IMMER ein JSON mit den Schlüsseln
    typ, absender, datum, betrag, kurzfassung zurück.
    Aktuell Dummy-Werte, später können wir OCR + OpenAI einbauen.
    """
    try:
        # Datei einlesen (noch ungenutzt, Platzhalter für spätere Analyse)
        content = await file.read()

        # Hier könnte deine OCR/AI-Analyse stattfinden
        # analysis = do_analysis(content)
        # result.update(analysis)

        # Testwerte zurückgeben (Dummy)
        result = {
            "typ": "Rechnung",
            "absender": "Muster GmbH",
            "datum": "2025-09-14",
            "betrag": "123.45",
            "kurzfassung": "Beispiel: Webhosting Rechnung"
        }

    except Exception as e:
        # Falls etwas schiefgeht → Dummy mit Fehler
        result = {
            "typ": "Unbekannt",
            "absender": "Fehler",
            "datum": "1970-01-01",
            "betrag": "0.00",
            "kurzfassung": f"Analysefehler: {str(e)}"
        }

    return JSONResponse(content=result)
