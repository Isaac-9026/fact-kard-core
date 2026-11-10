#!/bin/sh
# SOLO DESARROLLO: migra, carga catálogos SUNAT y (con FK_DEMO=1) la empresa/usuario demo.
set -eu

python manage.py migrate --noinput
python manage.py seed_catalogos_sunat
if [ "${FK_DEMO:-0}" = "1" ]; then
    python manage.py init_demo
fi

exec python manage.py runserver 0.0.0.0:8000
