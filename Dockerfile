# ResearchLens reasoning service (main repo).
# Python 3.11 slim, uvicorn on $PORT (Render/HF compatible).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

# System deps: Pillow needs libjpeg/zlib at runtime (slim already ships them);
# keep the layer minimal — no build tools retained.
COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --upgrade pip && pip install .

# Non-root runtime user.
RUN useradd -m -u 10001 appuser && mkdir -p /srv/app/evidence && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8001

# $PORT is injected by Render/HF; default 8001 for local docker runs.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001} --workers 1"]
