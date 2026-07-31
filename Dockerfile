FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY terractl ./terractl
COPY terrawatch ./terrawatch
COPY services ./services
COPY database ./database

RUN python -m pip install --no-cache-dir . \
    && chown -R app:app /app

USER 10001:10001

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
