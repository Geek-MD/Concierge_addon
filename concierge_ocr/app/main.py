import ipaddress
import logging
import os
import socket
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

app = FastAPI(title="Concierge OCR API", version="0.2.8")
logger = logging.getLogger("concierge_ocr.api")

_OCR_INSTANCE: PaddleOCR | None = None
HOMEASSISTANT_LOCAL_ALIAS = "homeassistant"
LOCAL_ALLOWED_BASE_DIRS = tuple(Path(path) for path in os.getenv("LOCAL_PDF_BASE_PATHS", "/config,/share,/media").split(","))
RESOLVED_LOCAL_BASE_DIRS = tuple(
    path.expanduser().resolve() for path in LOCAL_ALLOWED_BASE_DIRS if path.expanduser().exists()
)

WEB_UI_HTML = """<!doctype html>
<html lang="en">
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
  <p>Enter a URL (<code>http/https</code>) or a local path mounted in Home Assistant (<code>/config</code>, <code>/share</code>, <code>/media</code> or <code>/homeassistant</code> as alias of <code>/config</code>).</p>
  <form id="ocrForm">
    <div class="row">
      <label for="sourceType">Source type</label>
      <select id="sourceType" name="sourceType">
        <option value="url">URL</option>
        <option value="local_path">Local path</option>
      </select>
    </div>
    <div class="row">
      <label for="sourceValue">PDF URL or path</label>
      <input id="sourceValue" name="sourceValue" placeholder="https://.../file.pdf or /config/file.pdf (/homeassistant/... also supported)" required />
      <span class="hint">Only PDF files are supported.</span>
    </div>
    <div class="actions">
      <button type="submit">Analyze PDF</button>
      <button id="downloadBtn" type="button" disabled>Download JSON</button>
    </div>
  </form>

  <label for="result">JSON result</label>
  <textarea id="result" readonly placeholder="The JSON response will appear here..."></textarea>

  <script>
    const form = document.getElementById('ocrForm');
    const sourceType = document.getElementById('sourceType');
    const sourceValue = document.getElementById('sourceValue');
    const result = document.getElementById('result');
    const downloadBtn = document.getElementById('downloadBtn');
    let latestJson = null;

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      result.value = 'Processing...';
      downloadBtn.disabled = true;
      latestJson = null;

      const payload = new FormData();
      payload.append('source_type', sourceType.value);
      payload.append('source_value', sourceValue.value.trim());

      try {
        const endpoint = new URL('ocr/source', window.location.href);
        const response = await fetch(endpoint, { method: 'POST', body: payload });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || 'Unexpected error');
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
      link.download = 'ocr_result.json';
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
    return pdf_bytes.startswith(b"%PDF")


def _is_public_http_url(pdf_url: str) -> bool:
    parsed = urlparse(pdf_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.hostname.lower() == "localhost":
        return False

    try:
        resolved = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        return False

    for entry in resolved:
        raw_ip = entry[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False

    return True


def _validate_local_pdf_path(local_path: str) -> Path:
    requested_path = Path(local_path.strip()).expanduser()

    if (
        requested_path.is_absolute()
        and len(requested_path.parts) > 1
        and requested_path.parts[1] == HOMEASSISTANT_LOCAL_ALIAS
    ):
        requested_path = Path("/config").joinpath(*requested_path.parts[2:])

    if not requested_path.is_absolute():
        raise HTTPException(status_code=400, detail="The local path must be absolute")

    if not RESOLVED_LOCAL_BASE_DIRS:
        raise HTTPException(status_code=500, detail="No allowed local paths are configured")

    for base in RESOLVED_LOCAL_BASE_DIRS:
        try:
            relative_path = requested_path.relative_to(base)
        except ValueError:
            continue

        try:
            resolved_path = (base / relative_path).resolve(strict=True)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Local file not found") from exc

        if not resolved_path.is_relative_to(base):
            raise HTTPException(status_code=403, detail="The local path is not allowed")
        if not resolved_path.is_file():
            raise HTTPException(status_code=400, detail="The local path does not point to a file")
        if resolved_path.suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="The local path must point to a PDF file")
        return resolved_path

    raise HTTPException(status_code=403, detail="The local path is not allowed")


async def _fetch_pdf_from_url(pdf_url: str) -> bytes:
    if not _is_public_http_url(pdf_url):
        raise HTTPException(status_code=400, detail="The URL is not valid or safe to download")

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(pdf_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Could not download the PDF: {exc}") from exc

    pdf_bytes = response.content
    if not pdf_bytes or not _is_pdf_bytes(pdf_bytes):
        raise HTTPException(status_code=400, detail="The URL did not return a valid PDF")

    return pdf_bytes


def _load_local_pdf(local_path: str) -> bytes:
    validated_path = _validate_local_pdf_path(local_path)
    try:
        return validated_path.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Could not read the local PDF: {exc}") from exc


def _process_pdf_bytes(pdf_bytes: bytes) -> dict[str, Any]:
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="No PDF was received")

    if not _is_pdf_bytes(pdf_bytes):
        raise HTTPException(status_code=400, detail="Invalid content: it does not look like a PDF")

    try:
        images = convert_from_bytes(pdf_bytes)
    except Exception as exc:  # pragma: no cover
        logger.exception("PDF processing failed while converting bytes to images")
        raise HTTPException(status_code=400, detail=f"Could not process the PDF: {exc}") from exc

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
    try:
        if file is not None:
            if not file.filename or not file.filename.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="The uploaded file must be a PDF")
            pdf_bytes = await file.read()
        else:
            pdf_bytes = await request.body()

        return _process_pdf_bytes(pdf_bytes)
    except HTTPException as exc:
        logger.warning("Request to /ocr failed: %s", exc.detail)
        raise
    except Exception:
        logger.exception("Unhandled error in /ocr")
        raise


@app.post("/ocr/source")
async def handle_ocr_source_request(
    source_type: str = Form(...),
    source_value: str = Form(...),
) -> dict[str, Any]:
    normalized_source = source_type.strip().lower()
    normalized_value = source_value.strip()

    try:
        if not normalized_value:
            raise HTTPException(status_code=400, detail="You must provide a URL or local path")

        if normalized_source == "url":
            pdf_bytes = await _fetch_pdf_from_url(normalized_value)
        elif normalized_source == "local_path":
            pdf_bytes = _load_local_pdf(normalized_value)
        else:
            raise HTTPException(status_code=400, detail="source_type must be 'url' or 'local_path'")

        return _process_pdf_bytes(pdf_bytes)
    except HTTPException as exc:
        logger.warning("Request to /ocr/source failed: %s (source_type=%s)", exc.detail, normalized_source)
        raise
    except Exception:
        logger.exception("Unhandled error in /ocr/source")
        raise
