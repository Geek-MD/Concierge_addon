import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
import httpx
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pdf2image import convert_from_bytes
from paddleocr import PaddleOCR

app = FastAPI(title="Concierge OCR API", version="0.2.0")

_OCR_INSTANCE: PaddleOCR | None = None
LOCAL_PDF_BASE_PATHS = tuple(Path(path) for path in os.getenv("LOCAL_PDF_BASE_PATHS", "/config,/share,/media").split(","))

WEB_UI_HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Concierge OCR Web UI</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 1rem; max-width: 900px; }
    h1 { margin-top: 0; }
    form { display: grid; gap: .75rem; margin-bottom: 1rem; }
    select, input, button, textarea { font: inherit; padding: .5rem; }
    textarea { min-height: 240px; width: 100%; }
    .row { display: grid; gap: .5rem; }
    .hint { color: #666; font-size: .9rem; }
    .actions { display: flex; gap: .5rem; flex-wrap: wrap; }
  </style>
</head>
<body>
  <h1>Concierge OCR Web UI</h1>
  <p>Indica una URL (<code>http/https</code>) o una ruta local montada en Home Assistant (<code>/config</code>, <code>/share</code>, <code>/media</code>).</p>
  <form id="ocrForm">
    <div class="row">
      <label for="sourceType">Tipo de origen</label>
      <select id="sourceType" name="sourceType">
        <option value="url">URL</option>
        <option value="local_path">Ruta local</option>
      </select>
    </div>
    <div class="row">
      <label for="sourceValue">URL o ruta del PDF</label>
      <input id="sourceValue" name="sourceValue" placeholder="https://.../archivo.pdf o /config/archivo.pdf" required />
      <span class="hint">Solo se aceptan archivos PDF.</span>
    </div>
    <div class="actions">
      <button type="submit">Analizar PDF</button>
      <button id="downloadBtn" type="button" disabled>Descargar JSON</button>
    </div>
  </form>

  <label for="result">Resultado JSON</label>
  <textarea id="result" readonly placeholder="Aquí aparecerá la respuesta JSON..."></textarea>

  <script>
    const form = document.getElementById('ocrForm');
    const sourceType = document.getElementById('sourceType');
    const sourceValue = document.getElementById('sourceValue');
    const result = document.getElementById('result');
    const downloadBtn = document.getElementById('downloadBtn');
    let latestJson = null;

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      result.value = 'Procesando...';
      downloadBtn.disabled = true;
      latestJson = null;

      const payload = new FormData();
      payload.append('source_type', sourceType.value);
      payload.append('source_value', sourceValue.value.trim());

      try {
        const response = await fetch('/ocr/source', { method: 'POST', body: payload });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || 'Error inesperado');
        }
        latestJson = data;
        result.value = JSON.stringify(data, null, 2);
        downloadBtn.disabled = false;
      } catch (error) {
        result.value = `Error: ${error.message}`;
      }
    });

    downloadBtn.addEventListener('click', () => {
      if (!latestJson) return;
      const blob = new Blob([JSON.stringify(latestJson, null, 2)], { type: 'application/json' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'ocr_resultado.json';
      link.click();
      URL.revokeObjectURL(link.href);
    });
  </script>
</body>
</html>
"""


def get_ocr() -> PaddleOCR:
    """Create and cache the PaddleOCR instance used by all requests."""
    global _OCR_INSTANCE
    if _OCR_INSTANCE is None:
        _OCR_INSTANCE = PaddleOCR(use_angle_cls=True, lang=os.getenv("OCR_LANG", "es"))
    return _OCR_INSTANCE


def _extract_page_lines(ocr_result: Any) -> list[dict[str, Any]]:
    """Transform PaddleOCR output into a normalized list of OCR line objects."""
    lines: list[dict[str, Any]] = []
    for block in ocr_result or []:
        for item in block or []:
            box = item[0]
            text = item[1][0]
            confidence = float(item[1][1])
            lines.append(
                {
                    "text": text,
                    "confidence": confidence,
                    "box": box,
                }
            )
    return lines


def _is_pdf_bytes(pdf_bytes: bytes) -> bool:
    return pdf_bytes.lstrip().startswith(b"%PDF")


def _validate_local_pdf_path(local_path: str) -> Path:
    requested_path = Path(local_path).expanduser()

    if not requested_path.is_absolute():
        raise HTTPException(status_code=400, detail="La ruta local debe ser absoluta")

    try:
        resolved_path = requested_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No se encontró el archivo local") from exc

    if not resolved_path.is_file():
        raise HTTPException(status_code=400, detail="La ruta local no apunta a un archivo")

    if resolved_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="La ruta local debe ser un archivo PDF")

    allowed_bases: list[Path] = []
    for base in LOCAL_PDF_BASE_PATHS:
        expanded_base = base.expanduser()
        if expanded_base.exists():
            allowed_bases.append(expanded_base.resolve())

    if allowed_bases and not any(
        resolved_path == base or base in resolved_path.parents for base in allowed_bases
    ):
        raise HTTPException(status_code=403, detail="La ruta local no está permitida")

    return resolved_path


async def _fetch_pdf_from_url(pdf_url: str) -> bytes:
    parsed = urlparse(pdf_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="La URL debe usar http o https")

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(pdf_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo descargar el PDF: {exc}") from exc

    pdf_bytes = response.content
    if not pdf_bytes or not _is_pdf_bytes(pdf_bytes):
        raise HTTPException(status_code=400, detail="La URL no devolvió un PDF válido")

    return pdf_bytes


def _load_local_pdf(local_path: str) -> bytes:
    validated_path = _validate_local_pdf_path(local_path)
    try:
        return validated_path.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el PDF local: {exc}") from exc


def _process_pdf_bytes(pdf_bytes: bytes) -> dict[str, Any]:
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="No se recibió un PDF")

    if not _is_pdf_bytes(pdf_bytes):
        raise HTTPException(status_code=400, detail="Contenido inválido: no parece PDF")

    try:
        images = convert_from_bytes(pdf_bytes)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"No se pudo procesar el PDF: {exc}") from exc

    ocr = get_ocr()
    pages: list[dict[str, Any]] = []

    for index, image in enumerate(images, start=1):
        bgr_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        result = ocr.ocr(bgr_image, cls=True)
        lines = _extract_page_lines(result)
        pages.append(
            {
                "page": index,
                "lines": lines,
                "text": "\n".join(line["text"] for line in lines),
            }
        )

    return {
        "page_count": len(pages),
        "pages": pages,
        "text": "\n\n".join(page["text"] for page in pages if page["text"]),
    }


@app.get("/", response_class=HTMLResponse)
def web_ui() -> HTMLResponse:
    return HTMLResponse(content=WEB_UI_HTML)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ocr")
async def handle_ocr_request(request: Request, file: UploadFile | None = File(default=None)) -> dict[str, Any]:
    if file is not None:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo debe ser PDF")
        pdf_bytes = await file.read()
    else:
        pdf_bytes = await request.body()

    return _process_pdf_bytes(pdf_bytes)


@app.post("/ocr/source")
async def handle_ocr_source_request(
    source_type: str = Form(...),
    source_value: str = Form(...),
) -> dict[str, Any]:
    normalized_source = source_type.strip().lower()
    normalized_value = source_value.strip()

    if not normalized_value:
        raise HTTPException(status_code=400, detail="Debe indicar una URL o ruta local")

    if normalized_source == "url":
        pdf_bytes = await _fetch_pdf_from_url(normalized_value)
    elif normalized_source == "local_path":
        pdf_bytes = _load_local_pdf(normalized_value)
    else:
        raise HTTPException(status_code=400, detail="source_type debe ser 'url' o 'local_path'")

    return _process_pdf_bytes(pdf_bytes)
