# I.R.I.S. v5 — stateless core image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first (better layer caching).
COPY pyproject.toml README.md ./
COPY iris ./iris
RUN pip install --upgrade pip && pip install -e .

# Sandbox dir the filesystem MCP is restricted to.
RUN mkdir -p /app/workspace

EXPOSE 8000

# Built out in STEP 0.4; the app object lives at iris.gateway.api:app.
CMD ["uvicorn", "iris.gateway.api:app", "--host", "0.0.0.0", "--port", "8000"]
