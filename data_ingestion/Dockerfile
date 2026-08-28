FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY data_ingestion/ ./data_ingestion/
COPY helper_scripts/ ./helper_scripts/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:/app/data_ingestion"
ENV PYTHONUNBUFFERED=1

WORKDIR /app

CMD ["sh", "-c", "python data_ingestion/generate_data.py && \
                 python data_ingestion/generate_logs.py && \
                 python data_ingestion/generate_otel_schema.py && \
                 python data_ingestion/generate_embeddings.py"]
