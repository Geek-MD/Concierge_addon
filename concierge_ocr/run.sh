#!/usr/bin/with-contenv bashio

OCR_LANG="$(bashio::config 'ocr_lang' 'es')"
export OCR_LANG

bashio::log.info "Iniciando Concierge OCR API en puerto 8099 (ocr_lang=${OCR_LANG})"
exec uvicorn app.main:app --host 0.0.0.0 --port 8099
