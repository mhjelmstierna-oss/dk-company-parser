"""
FastAPI webhook för DK Company PDF-parser.

Endpoints:
  GET  /           -> hälsocheck
  POST /parse      -> PDF (multipart) eller {"pdf_base64": "..."} -> JSON med produkter

Körs via: uvicorn server:app --host 0.0.0.0 --port $PORT
"""
import base64
import io
import os
import tempfile
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from parser import parse_dk_company

app = FastAPI(title="DK Company PDF Parser")

# Enkel API-nyckel via miljövariabel (valfritt men rekommenderat)
API_KEY = os.environ.get("API_KEY", "")


def _check_key(request: Request):
    if not API_KEY:
        return  # ingen nyckel konfigurerad, öppen
    header_key = request.headers.get("x-api-key", "")
    if header_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/")
def root():
    return {"service": "dk-company-parser", "status": "ok"}


@app.post("/parse")
async def parse(request: Request, pdf: UploadFile = File(None)):
    _check_key(request)

    pdf_bytes = None

    # Variant 1: multipart/form-data upload
    if pdf is not None:
        pdf_bytes = await pdf.read()
    else:
        # Variant 2: JSON med base64-kodad PDF
        try:
            body = await request.json()
        except Exception:
            body = None
        if body and isinstance(body, dict) and body.get("pdf_base64"):
            try:
                pdf_bytes = base64.b64decode(body["pdf_base64"])
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid base64: {e}")

    if not pdf_bytes:
        raise HTTPException(
            status_code=400,
            detail="Provide PDF as multipart 'pdf' or JSON {'pdf_base64': '...'}",
        )

    # Skriv tillfälligt till disk eftersom pdfplumber behöver filväg eller stream
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        result = parse_dk_company(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse error: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return JSONResponse(content=result)
