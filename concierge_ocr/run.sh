#!/usr/bin/with-contenv bashio

OCR_LANG="$(bashio::config 'ocr_lang' 'es')"
export OCR_LANG

bashio::log.info "Starting Concierge OCR API on port 8099 (ocr_lang=${OCR_LANG})"
exec uvicorn app.main:app --host 0.0.0.0 --port 8099
