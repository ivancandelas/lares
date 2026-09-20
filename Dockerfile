# Imagen de Lares. Se publica etiquetada con su versión, no se construye en la
# máquina de destino: actualizar tiene que ser cambiar una etiqueta y levantar,
# no compilar en el servidor de casa y cruzar los dedos.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=lares.settings.prod

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY src/ ./src/
COPY packs/ ./packs/
COPY VERSION ./VERSION
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Qué versión es esta imagen. Se inyecta al construir para que el contenedor
# diga exactamente lo que corre, sin depender de la etiqueta con que se bajó.
ARG LARES_VERSION=desconocida
ENV LARES_VERSION=${LARES_VERSION}
LABEL org.opencontainers.image.title="Lares" \
      org.opencontainers.image.description="Personal Resource Planning, self-hosted" \
      org.opencontainers.image.version="${LARES_VERSION}" \
      org.opencontainers.image.source="https://github.com/ivancandelas/lares"

# No corre como root: si alguien encuentra un agujero en un parser de PDF, que
# lo encuentre siendo nadie.
RUN useradd --system --uid 10001 --home /app lares \
    && mkdir -p /data/media /app/staticfiles \
    && chown -R lares:lares /app /data
USER lares

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/salud || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "lares.wsgi:application", "--chdir", "src", \
     "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", \
     "--access-logfile", "-"]
