FROM python:3.12-alpine


COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app


COPY pyproject.toml .
COPY uv.lock* ./


RUN uv sync --frozen --no-dev --system


COPY src/ ./src/
COPY schema.sql ./


EXPOSE 8000

# Run the application
CMD ["python", "-m", "src.main"]