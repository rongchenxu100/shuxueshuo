# P2 API / Worker / publisher runtime. Build context is the repository root.
FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl nodejs \
 && rm -rf /var/lib/apt/lists/*

# Client only; daemon is the host via /var/run/docker.sock (OCR sidecar).
ARG TARGETARCH
ARG DOCKER_STATIC_VERSION=27.3.1
RUN arch="$(case "${TARGETARCH}" in amd64) echo x86_64;; arm64) echo aarch64;; *) echo "${TARGETARCH}";; esac)" \
 && curl -fsSL "https://download.docker.com/linux/static/stable/${arch}/docker-${DOCKER_STATIC_VERSION}.tgz" \
    | tar -xz -C /usr/local/bin --strip-components=1 docker/docker \
 && docker --version \
 && node --version

RUN python3 -m venv /opt/product
COPY deploy/product/requirements.lock /tmp/requirements.lock
RUN /opt/product/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock

COPY server /app/server
COPY tools /app/tools
COPY internal /app/internal
COPY site/assets /app/site/assets
COPY deploy/product/bin/ocr-python /app/bin/ocr-python
RUN chmod 755 /app/bin/ocr-python \
 && test -f /app/server/uv.lock \
 && test -f /app/tools/build-lesson-page.mjs \
 && test -f /app/internal/templates/interactive-problem-page.template.html

WORKDIR /app/server
ENV PATH="/opt/product/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/server \
    PRODUCT_IN_CONTAINER=1 \
    REVIEW_BACKEND=product \
    REVIEW_OCR_PYTHON=/app/bin/ocr-python

CMD ["uvicorn", "shuxueshuo_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
