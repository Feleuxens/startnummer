# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM node:24-bookworm-slim AS node

FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    UV_LINK_MODE=copy
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS api-deps
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra api --no-install-project

FROM api-deps AS frontend
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
ENV ASTRO_TELEMETRY_DISABLED=1
COPY startnummer-web/package*.json startnummer-web/
RUN --mount=type=cache,target=/root/.npm cd startnummer-web && npm ci
COPY startnummer/ startnummer/
COPY scripts/export_openapi.py scripts/
COPY startnummer-web/ startnummer-web/
RUN cd startnummer-web && npm run build

FROM api-deps AS worker-cpu-deps
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra api --extra cpu --no-install-project

FROM api-deps AS worker-nvidia-deps
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra api --extra nvidia --no-install-project

FROM api-deps AS worker-intel-deps
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra api --extra intel --no-install-project

FROM base AS runtime
RUN groupadd --gid 10001 startnummer \
    && useradd --uid 10001 --gid startnummer --no-create-home startnummer \
    && mkdir -p /data/photos /data/models /backups \
    && chown -R startnummer:startnummer /data /backups
COPY startnummer/ startnummer/
COPY migrations/ migrations/
COPY alembic.ini ./
COPY --from=frontend /app/startnummer-web/dist/ startnummer-web/dist/
ENV PYTHONPATH=/app HOME=/data/models
USER 10001:10001

FROM runtime AS api
COPY --from=api-deps /app/.venv /app/.venv
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=4 \
    CMD ["python", "-m", "startnummer.app.healthcheck", "api"]
CMD ["python", "-m", "uvicorn", "startnummer.app.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker-cpu
COPY --from=worker-cpu-deps /app/.venv /app/.venv
ENV STARTNUMMER_MODEL_ROOT=/data/models STARTNUMMER_INFERENCE_BACKEND=cpu YOLO_CONFIG_DIR=/data/models
WORKDIR /data/models
RUN python - <<'PY'
import torch
assert torch.version.cuda is None
from startnummer.adapters.detect.yolo import YoloDetector
from startnummer.adapters.ocr.rapid import RapidOcrReader
from startnummer.adapters.face.insight import InsightFaceEngine
PY
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=4 \
    CMD ["python", "-m", "startnummer.app.healthcheck", "worker"]
CMD ["python", "-m", "startnummer.app.worker"]

FROM runtime AS worker-nvidia
COPY --from=worker-nvidia-deps /app/.venv /app/.venv
ENV STARTNUMMER_MODEL_ROOT=/data/models \
    YOLO_CONFIG_DIR=/data/models \
    STARTNUMMER_INFERENCE_BACKEND=cuda
WORKDIR /data/models
RUN python - <<'PY'
from startnummer.app.inference import preload_gpu_runtime
preload_gpu_runtime()
import onnxruntime as ort
assert "CUDAExecutionProvider" in ort.get_available_providers()
from startnummer.adapters.detect.yolo import YoloDetector
from startnummer.adapters.ocr.rapid import RapidOcrReader
from startnummer.adapters.face.insight import InsightFaceEngine
PY
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=4 \
    CMD ["python", "-m", "startnummer.app.healthcheck", "worker"]
CMD ["python", "-m", "startnummer.app.worker"]

FROM runtime AS worker-intel
COPY --from=worker-intel-deps /app/.venv /app/.venv
ENV STARTNUMMER_MODEL_ROOT=/data/models STARTNUMMER_INFERENCE_BACKEND=openvino YOLO_CONFIG_DIR=/data/models
WORKDIR /data/models
RUN python - <<'PY'
from pathlib import Path
from startnummer.adapters.runtime import prepare_runtime
prepare_runtime("openvino", Path("/data/models"))
from startnummer.adapters.detect.yolo import YoloDetector
from startnummer.adapters.ocr.rapid import RapidOcrReader
from startnummer.adapters.face.insight import InsightFaceEngine
PY
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=4 \
    CMD ["python", "-m", "startnummer.app.healthcheck", "worker"]
CMD ["python", "-m", "startnummer.app.worker"]

FROM api AS default
