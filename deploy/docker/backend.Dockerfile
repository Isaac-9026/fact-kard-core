# syntax=docker/dockerfile:1
# Imagen de PRODUCCIÓN del backend de Fact-Kard Core (Django + Gunicorn).
# Contexto: raíz del repositorio (ver .dockerignore). Se construye con deploy/docker/compose.yaml.
#
# - Python 3.13 (versión con la que pasan las pruebas del proyecto).
# - pg_dump / pg_restore 16 (mismo major que PostgreSQL 16) para `manage.py respaldo`,
#   desde el repositorio oficial de PostgreSQL (PGDG).
# - El código vive en /srv/fact-kard/app/backend; los datos (/srv/fact-kard/datos) quedan FUERA del código.
# - Corre como usuario sin privilegios (factkard, uid 10001). Ningún secreto entra a la imagen.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Lima

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
         https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
         > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 factkard \
    && useradd --system --uid 10001 --gid factkard --home-dir /srv/fact-kard --shell /usr/sbin/nologin factkard

WORKDIR /srv/fact-kard/app/backend

# Dependencias primero (capa en caché mientras requirements no cambie).
COPY backend/requirements.txt backend/requirements-prod.txt ./
RUN pip install -r requirements-prod.txt

COPY backend/ ./
COPY deploy/docker/backend-entrypoint.sh /usr/local/bin/fk-entrypoint
COPY deploy/docker/backend-healthcheck.py /usr/local/bin/fk-healthcheck
COPY deploy/docker/backend-tareas.sh /usr/local/bin/fk-tareas

RUN sed -i 's/\r$//' /usr/local/bin/fk-entrypoint /usr/local/bin/fk-healthcheck /usr/local/bin/fk-tareas \
    && chmod 0755 /usr/local/bin/fk-entrypoint /usr/local/bin/fk-healthcheck /usr/local/bin/fk-tareas \
    && mkdir -p /srv/fact-kard/datos/media /srv/fact-kard/datos/respaldos /srv/fact-kard/static \
    && chown -R factkard:factkard /srv/fact-kard/datos /srv/fact-kard/static \
    && chmod 0700 /srv/fact-kard/datos/respaldos

USER factkard
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 CMD ["python", "/usr/local/bin/fk-healthcheck"]

ENTRYPOINT ["fk-entrypoint"]
CMD ["gunicorn", "config.wsgi:application", "-c", "gunicorn.conf.py"]
