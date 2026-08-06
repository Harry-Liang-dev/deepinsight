FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY config ./config
COPY scripts ./scripts
COPY src ./src

RUN python -m pip install .

RUN addgroup --system deepinsight \
    && adduser --system --ingroup deepinsight deepinsight \
    && mkdir -p /app/data \
    && chown -R deepinsight:deepinsight /app

USER deepinsight

CMD ["python", "-m", "uvicorn", "apps.api.production:create_production_application", "--factory", "--host", "0.0.0.0", "--port", "8000"]
