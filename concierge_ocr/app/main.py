import os
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from pdf2image import convert_from_bytes
from paddleocr import PaddleOCR

app = FastAPI(title="Concierge OCR API", version="0.1.0")

_OCR_INSTANCE: PaddleOCR | None = None


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

    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="No se recibió un PDF")

    if not pdf_bytes.startswith(b"%PDF"):
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
