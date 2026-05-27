# Concierge addon

Home Assistant add-on that exposes a REST API and a Web UI to analyze PDFs with PaddleOCR and return the result as JSON.

## Structure

- `repository.yaml`: add-on repository metadata.
- `concierge_ocr/`: add-on definition.
  - `config.yaml`: Home Assistant add-on configuration.
  - `Dockerfile`: add-on image.
  - `run.sh`: API startup script.
  - `requirements.txt`: Python dependencies.
  - `app/main.py`: REST API (`/health`, `/ocr`, `/ocr/source`) and Web UI (`/`).

## Usage

1. Add this repository as an **Add-on repository** in Home Assistant.
2. Install the **Concierge OCR API** add-on.
3. Start the add-on.
4. Open the Web UI from the add-on page. If you enable **Show in sidebar**, it will also appear in the side panel.
5. Enter:
   - a PDF URL (`http/https`), or
   - a local Home Assistant path (`/config`, `/share`, `/media`).
6. Run the analysis and download the JSON if needed.

## API REST

### `POST /ocr`

Send a PDF over REST:

```bash
curl -X POST "http://HOME_ASSISTANT_HOST:8099/ocr" \
  -F "file=@document.pdf"
```

Raw PDF content in the request body is also supported (`Content-Type: application/pdf`).

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
