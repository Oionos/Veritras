# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Hosted deployments must opt in after durable cursor/replay support is ready.
# The isolated Compose stack explicitly enables its disposable local indexer.
ENV INDEXER_ENABLED=false

# Install system dependencies for packages that require compilation (e.g., psycopg2, cryptography)
COPY requirements.txt requirements.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.lock

COPY . .

EXPOSE 8000

CMD ["python", "start_api.py"]
