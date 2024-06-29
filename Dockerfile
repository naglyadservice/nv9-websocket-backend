FROM python:3.12-slim as builder

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

ENV PYTHONPATH "${PYTHONPATH}:/app"
WORKDIR /app

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    build-essential \
    && curl -sSL https://install.python-poetry.org | POETRY_HOME=/opt/poetry python \
    # Linking poetry for global access
    && ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry \
    # Clean up in a single layer to reduce image size.
    && apt-get purge --auto-remove -y curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock /app/
RUN --mount=type=cache,target=$POETRY_CACHE_DIR poetry install --no-ansi --only main --no-root


FROM python:3.12-slim as app

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}
ADD . /app

CMD ["python3", "-O", "main.py"]
