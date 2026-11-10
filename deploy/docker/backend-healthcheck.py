"""
Healthcheck del contenedor backend: GET /api/health/ a Gunicorn (dentro del contenedor).

Usa el primer dominio de ALLOWED_HOSTS como Host (Django rechaza otros) y X-Forwarded-Proto: https
para que SECURE_SSL_REDIRECT no responda 301. Sale con 0 solo si la API, PostgreSQL y Redis están OK.
"""
import json
import os
import sys
import urllib.request

host = (os.environ.get('ALLOWED_HOSTS', 'localhost').split(',')[0].strip()) or 'localhost'
peticion = urllib.request.Request('http://127.0.0.1:8001/api/health/',
                                  headers={'Host': host, 'X-Forwarded-Proto': 'https'})
try:
    with urllib.request.urlopen(peticion, timeout=8) as respuesta:
        datos = json.loads(respuesta.read() or b'{}')
        sys.exit(0 if respuesta.status == 200 and datos.get('status') == 'ok' else 1)
except Exception:  # noqa: BLE001 — cualquier fallo = no sano
    sys.exit(1)
