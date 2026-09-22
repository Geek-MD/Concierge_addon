# Concierge addon

[![Code Quality](https://github.com/Geek-MD/Concierge_addon/actions/workflows/code-quality.yml/badge.svg)](https://github.com/Geek-MD/Concierge_addon/actions/workflows/code-quality.yml)
[![Release](https://img.shields.io/github/v/release/Geek-MD/Concierge_addon.svg)](https://github.com/Geek-MD/Concierge_addon/releases)
[![Stars](https://img.shields.io/github/stars/Geek-MD/Concierge_addon.svg)](https://github.com/Geek-MD/Concierge_addon/stargazers)

![Supports aarch64 Architecture](https://img.shields.io/badge/aarch64-yes-green.svg)
![Supports amd64 Architecture](https://img.shields.io/badge/amd64-yes-green.svg)
![Supports armv7 Architecture](https://img.shields.io/badge/armv7-yes-green.svg)

Home Assistant add-on that exposes a REST API and a Web UI to analyze PDFs with PaddleOCR and return the result as JSON.

## Compatibility note

The add-on Docker image uses the multi-architecture Home Assistant Debian base image (`ghcr.io/home-assistant/base-debian:bookworm`).
This provides a glibc environment so that `paddlepaddle` and other ML dependencies can be installed from pre-built `manylinux` wheels on all supported architectures (including `aarch64`).
A previous Alpine-based image caused a silent build timeout on aarch64 because `paddlepaddle` has no musl/Alpine wheel and pip fell back to a source compilation that exceeded the HA Supervisor build timeout.

FastAPI endpoints that accept `multipart/form-data` (such as `/ocr` and `/ocr/source`) require `python-multipart`; this dependency is included to avoid startup failures during `uvicorn` boot.
The image also includes `libgl1` and `libglib2.0-0` so OpenCV can import correctly at startup on Debian-based Home Assistant environments.
The runtime dependencies explicitly include `paddlepaddle` to ensure `paddleocr` can initialize without startup import errors.

## Structure

- `repository.yaml`: add-on repository metadata.
- `concierge_ocr/`: add-on definition.
  - `config.yaml`: Home Assistant add-on configuration.
  - `Dockerfile`: add-on image.
  - `run.sh`: API startup script.
  - `requirements.txt`: Python dependencies.
  - `app/main.py`: REST API (`/health`, `/status`, `/templates`, `/ocr`, `/ocr/source`) and Web UI (`/`).
  - `app/web_ui.html`: OCR interface and persistent service-template editor.

## Usage

1. Add this repository as an **Add-on repository** in Home Assistant.
2. Install the **Concierge OCR API** add-on.
3. To generate a token from Home Assistant, set `generate_api_token` to `true`, save the configuration, and start the add-on once.
4. Copy the generated token from the add-on logs, paste it into the `api_token` option, set `generate_api_token` back to `false`, save, and start the add-on again. You can also generate a token externally with `openssl rand -hex 32`.
5. Open the Web UI from the add-on page. If you enable **Show in sidebar**, it will also appear in the side panel.
6. Enter:
   - a PDF URL (`http/https`), or
   - a local Home Assistant path (`/config`, `/share`, `/media`).
   - If your integration returns `/homeassistant/...`, it is also accepted and treated as an alias for `/config/...`.
7. Run the analysis and download the JSON if needed.
8. If an analysis fails, review the add-on logs from Home Assistant; request and PDF processing errors are now logged with diagnostic details.

## Troubleshooting incomplete sensor attributes

The Concierge integration can log a warning similar to:

```text
addon OCR left sensor attributes incomplete for '<file>.pdf'; using internal extractor as fallback
```

This warning does not mean that the add-on request failed. It means that the add-on
returned an OCR result, but the integration could not populate every sensor attribute it
requires from the structured response, so it continued with its built-in PDF extractor.
Check the resulting sensor state and attributes before treating the message as an error.

An isolated warning normally needs no add-on code change. It can be caused by OCR quality,
a new statement layout, or a template section or field that did not match. If it happens
repeatedly for the same document layout:

1. Run the PDF from the add-on Web UI with the same template used by the integration.
2. Inspect `meta.matched_sections` in the JSON response. A section with `matched: false`,
   or a required field with a `null` value, identifies the extraction that needs adjustment.
3. Compare the extracted fields with the final Home Assistant sensor attributes. If the
   internal fallback filled them, the warning records a recovered degradation; if they are
   still absent, report the PDF layout (with private data removed), template ID, add-on
   version, and JSON response.

Do not disable the fallback merely to suppress the warning: it preserves sensor data when
the OCR/template path is incomplete. A code or template fix is warranted when the warning
is reproducible and the diagnostic JSON identifies a consistently unmatched or empty field.

## API REST

### `POST /ocr`

Send a PDF over REST:

```bash
curl -X POST "http://HOME_ASSISTANT_HOST:8099/ocr" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -F "file=@document.pdf"
```

Raw PDF content in the request body is also supported (`Content-Type: application/pdf`).

Optional query params:

- `template_id=<builtin_template_id>`
- `template_json=<json_template_string>`
- `auto_detect_template=true|false`

Behavior:

- If `template_id` or `template_json` is provided, the endpoint returns structured output using that template.
- If no template is provided and `auto_detect_template=true` (default), the add-on compares the OCR result against the built-in templates and returns the best structured match when its average section-anchor score is high enough.
- If no template is provided and `auto_detect_template=false`, the endpoint returns the raw OCR payload.

Example response:

```json
{
  "page_count": 1,
  "pages": [
    {
      "page": 1,
      "lines": [
        {
          "text": "Hello world",
          "confidence": 0.99,
          "box": [[0, 0], [100, 0], [100, 20], [0, 20]]
        }
      ],
      "text": "Hello world"
    }
  ],
  "text": "Hello world"
}
```

### `POST /ocr/source`

Allows processing a PDF from a remote or local source:

- `source_type=url` and `source_value=https://.../file.pdf`
- `source_type=local_path` and `source_value=/config/file.pdf`
- `source_type=local_path` and `source_value=/homeassistant/file.pdf` (alias to `/config/file.pdf`)

Optional form fields:

- `template_id`
- `template_json`
- `auto_detect_template`

The same template-selection behavior used by `/ocr` also applies here: explicit template first, then auto-detection by default, or raw OCR when disabled.

### `GET /templates`

Lists built-in and user-created template IDs available for `template_id`. The Web UI's
**Plantillas de servicios** tab can create a blank template, start from a generic example,
open, import, export, format, save, and delete templates. Built-in templates can be opened
and copied under a new ID, but cannot be overwritten or deleted.

User templates are persisted as JSON in `/data/templates` (or the directory configured by
`TEMPLATE_STORAGE_DIR`) and remain available after add-on restarts. The authenticated CRUD
endpoints are `GET /templates/{template_id}`, `PUT /templates/{template_id}`, and
`DELETE /templates/{template_id}`.

### `GET /status`

Returns add-on runtime status for integrations that need to verify the add-on is alive.

Example response:

```json
{
  "status": "ok",
  "running": true,
  "version": "0.3.2"
}
```

## Web UI template selection

The Web UI now lets you choose between:

- `Auto-detect`: compares the OCR JSON against the built-in templates and returns the best structured match
- `None (raw OCR)`: returns the raw OCR JSON without template formatting
- A specific built-in template ID: forces that template for the response

### Template shape (`template_json`)

Templates now represent real PDF sections explicitly:

- `sections[]`: each logical/visual section in the PDF.
- `sections[].lines[]`: logical lines inside the section.
- `sections[].lines[].boxes[]`: text boxes with semantic `role`.

Supported `role` values:

- `fixed`: canonical label text (supports fuzzy matching and overwrite of OCR text).
- `variable`: value that changes from PDF to PDF and is associated using `locator.strategy`.
- `mixed`: one line containing fixed + variable text using `?` placeholders in template text.
- `ignore`: currently ignored in output.

### Shorthand template (section/line/type)

The API also accepts a shorthand schema where each line uses a simple `type`:

- `fixed`: static text anchor
- `mixed`: static + variable in one line, where `?` marks the variable segment(s)
- `ignore`: line intentionally skipped from extraction

Use `ignore` for non-business lines (for example tracking/reference numbers) that may appear in the section but should not be captured as a field.

Example:

```json
{
  "section": {
    "id": "encabezado_pago",
    "name": "Encabezado",
    "lines": [
      { "text": "¡Paga tu Gasto Común en línea!", "type": "fixed" },
      { "text": "Ingresa a: https://pagos.kastor.cl", "type": "fixed" },
      { "text": "Código cliente: ??????-?????", "type": "mixed", "key": "codigo_cliente" },
      { "text": "44121821052026", "type": "ignore" }
    ]
  }
}
```

This shorthand is internally converted to the canonical `sections -> lines -> boxes` structure.

Minimal example:

```json
{
  "template_id": "gasto_comun_v1",
  "document_type": "gasto_comun",
  "matching": {
    "normalize_accents": true,
    "ignore_case": true,
    "collapse_whitespace": true,
    "default_fuzzy_threshold": 0.82
  },
  "sections": [
    {
      "id": "datos_comunidad",
      "anchors": ["Comunidad", "Dirección", "Fecha de último pago"],
      "lines": [
        {
          "id": "linea_comunidad",
          "boxes": [
            { "role": "fixed", "key": "comunidad_label", "canonical_text": "Comunidad", "overwrite_ocr_text": true },
            { "role": "variable", "key": "comunidad", "locator": { "strategy": "nearest_right_or_below", "max_distance": 2 } }
          ]
        }
      ]
    }
  ]
}
```
