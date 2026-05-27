ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.12-alpine3.22
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apk add --no-cache poppler-utils

COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
