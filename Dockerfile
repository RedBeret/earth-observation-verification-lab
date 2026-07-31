FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app

COPY requirements/runtime.txt ./requirements/runtime.txt
RUN python -m pip install --no-cache-dir --requirement requirements/runtime.txt

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY terractl ./terractl
COPY terrawatch ./terrawatch
COPY services ./services
COPY database ./database

RUN python -m pip install --no-cache-dir --no-deps . \
    && chown -R app:app /app

USER 10001:10001

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
