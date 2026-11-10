#!/bin/sh
# Arranque del contenedor backend de Fact-Kard Core.
#   1. Espera a PostgreSQL (máx. FK_ESPERA_DB_SEGUNDOS, 60 por defecto).
#   2. Solo al iniciar Gunicorn: collectstatic al volumen compartido con el contenedor web.
#   3. Migraciones automáticas SOLO si FK_MIGRAR_AL_INICIAR=1 (por defecto se ejecutan a mano:
#      docker compose run --rm backend python manage.py migrate).
# Nunca imprime contraseñas ni la configuración.
set -eu

python - <<'PY'
import os, sys, time
import psycopg

limite = time.monotonic() + int(os.environ.get('FK_ESPERA_DB_SEGUNDOS', '60'))
while True:
    try:
        psycopg.connect(host=os.environ.get('DB_HOST', 'db'), port=os.environ.get('DB_PORT', '5432'),
                        dbname=os.environ.get('DB_NAME', 'fact_kard'), user=os.environ.get('DB_USER', 'fact_kard_user'),
                        password=os.environ.get('DB_PASSWORD', ''), connect_timeout=3).close()
        break
    except psycopg.OperationalError:
        if time.monotonic() > limite:
            print('[fk-entrypoint] PostgreSQL no responde; se aborta el arranque.', file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
PY

if [ "${1:-}" = "gunicorn" ]; then
    python manage.py collectstatic --noinput --verbosity 0
    if [ "${FK_MIGRAR_AL_INICIAR:-0}" = "1" ]; then
        python manage.py migrate --noinput
    fi
fi

exec "$@"
