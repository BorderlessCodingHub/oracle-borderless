# Imagem da aplicação Oracle Borderless (FastAPI + uv).
FROM python:3.13-slim

# uv para gerenciar dependências.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# ffmpeg/ffprobe: extração e fatiamento de áudio das aulas (Mentor).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala dependências primeiro (cache de camadas).
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# Código.
COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
