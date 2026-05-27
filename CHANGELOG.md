# Changelog

## 0.2.2
- Fixed add-on installation failure on Alpine by adding the native build toolchain and required development libraries in the image before installing Python dependencies.

## 0.2.1
- Fixed add-on image build by switching `BUILD_FROM` to a valid multi-architecture Home Assistant base image (`ghcr.io/home-assistant/base-python:3.12-alpine3.22`) instead of the missing `amd64`-specific tag.

## 0.2.0
- Added a Web UI at `/` to analyze PDFs from a URL or a local Home Assistant path.
- Added a new `POST /ocr/source` route to process PDFs using `source_type` (`url` or `local_path`) and `source_value`.
- The Web UI displays the OCR JSON on screen and allows downloading it as a `.json` file.
- Enabled add-on ingress and side panel access in Home Assistant.
- Added read-only mappings for local paths: `/config`, `/share`, `/media`.

## 0.1.0
- Initial scaffold for the `concierge_ocr` Home Assistant add-on.
- REST API with a `POST /ocr` endpoint to receive a PDF and return OCR as JSON.
- PaddleOCR integration with configurable language support (`ocr_lang`).
