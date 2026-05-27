# Changelog

## 0.2.0
- Se agregó una Web UI en `/` para analizar PDFs desde URL o ruta local de Home Assistant.
- Nueva ruta `POST /ocr/source` para procesar PDFs por `source_type` (`url` o `local_path`) y `source_value`.
- La Web UI muestra el JSON OCR en pantalla y permite descargarlo como archivo `.json`.
- Se habilitó `ingress` y panel lateral del addon en Home Assistant.
- Se agregaron mapas de lectura para rutas locales: `/config`, `/share`, `/media`.

## 0.1.0
- Scaffold inicial del addon de Home Assistant `concierge_ocr`.
- API REST con endpoint `POST /ocr` para recibir PDF y devolver OCR en JSON.
- Integración con PaddleOCR y soporte de idioma configurable (`ocr_lang`).
