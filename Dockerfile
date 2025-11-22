FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app


COPY pyproject.toml .
COPY uv.lock* ./

RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY src/ ./src/
COPY schema.sql ./


EXPOSE 8000

# Run the application
CMD ["python", "-m", "src.main"]
