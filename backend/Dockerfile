# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# tesseract for the live OCR path (DeepSeek text provider)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/
WORKDIR /app

# install deps first (better layer caching)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# app source + the policy/eval data
COPY backend/ ./
COPY docs/ /app/docs/

ENV PATH="/app/.venv/bin:$PATH" \
    POLICY_FILE=/app/docs/policy_terms.json \
    TEST_CASES_FILE=/app/docs/test_cases.json

EXPOSE 8000
# Render (and most PaaS) inject $PORT; fall back to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
