# syntax=docker/dockerfile:1
#
# Pinned base image (verified against the Docker Hub registry API, 2026-09-04):
#   python:3.12-slim -> sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
# Re-verify and bump deliberately; do not float on a mutable tag.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

# ---- builder: resolve and install dependencies into an isolated venv ----------------
FROM ${PYTHON_IMAGE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# ---- runtime: minimal image, non-root, only the venv + app code ---------------------
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 10001 traderstack

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
RUN mkdir -p /app/var/state /app/var/audit && chown -R traderstack:traderstack /app

USER traderstack

# Prometheus metrics endpoint (see --metrics-port, default 9108). Uses stdlib
# urllib rather than curl/wget, which are not installed in this slim image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9108/metrics', timeout=3)" || exit 1

ENTRYPOINT ["traderstack-paper"]
