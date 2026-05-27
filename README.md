# Concierge_addon

Addon para Home Assistant que expone una API REST para recibir un PDF, ejecutar OCR con PaddleOCR y devolver el resultado en JSON.

## Estructura

- `repository.yaml`: metadatos del repositorio de addons.
- `concierge_ocr/`: definición del addon.
  - `config.yaml`: configuración del addon para Home Assistant.
  - `Dockerfile`: imagen del addon.
  - `run.sh`: arranque de la API.
  - `requirements.txt`: dependencias Python.
  - `app/main.py`: API REST (`/health` y `/ocr`).

## Uso

1. Añade este repositorio como **Add-on repository** en Home Assistant.
2. Instala el addon **Concierge OCR API**.
3. Inicia el addon (puerto `8099`).
4. Envía un PDF por REST:

```bash
curl -X POST "http://HOME_ASSISTANT_HOST:8099/ocr" \
  -F "file=@documento.pdf"
```

También se acepta el PDF en el body crudo (`Content-Type: application/pdf`).

Respuesta ejemplo:

```json
{
  "page_count": 1,
  "pages": [
    {
      "page": 1,
      "lines": [
        {
          "text": "Hola mundo",
          "confidence": 0.99,
          "box": [[0, 0], [100, 0], [100, 20], [0, 20]]
        }
      ],
      "text": "Hola mundo"
    }
  ],
  "text": "Hola mundo"
}
```
