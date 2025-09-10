# syntax=docker/dockerfile:1
FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Download artifacts during the build (server-side)
ARG CATALOG_URL
ARG PRODUCTS_PCA_URL
ARG PCA_URL
RUN mkdir -p /app/artifacts && \
    curl -L "$CATALOG_URL" -o /app/artifacts/catalog.parquet && \
    curl -L "$PRODUCTS_PCA_URL" -o /app/artifacts/products_pca.parquet && \
    curl -L "$PCA_URL" -o /app/artifacts/pca.pkl && \
    ls -lah /app/artifacts

# Copy code
COPY . .

ENV PORT=8080 \
    ARTIFACTS_DIR=/app/artifacts \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8080", "api:app"]
