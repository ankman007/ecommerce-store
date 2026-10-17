FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


FROM python:3.13-slim

# Fixed IDs so file ownership on volumes is predictable across rebuilds and hosts.
ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libmariadb3 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid "${APP_GID}" app \
    && useradd --system --uid "${APP_UID}" --gid app --home-dir /app --no-create-home \
        --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install /wheels/* && rm -rf /wheels

# Code stays root-owned (read-only for the app user); only media is writable at runtime.
COPY . .

RUN SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput \
    && mkdir -p /app/media \
    && chown app:app /app/media

USER app

EXPOSE 8000

# Any HTTP answer below 500 from gunicorn counts as healthy (see deploy/healthcheck.py).
# Celery containers built from this image disable it in compose.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "deploy/healthcheck.py"]

CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "core.wsgi:application"]
