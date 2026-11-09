"""
Bloque 8 — configuración de Gunicorn para producción.

Uso (desde backend/, con el entorno virtual activo):
    gunicorn config.wsgi:application -c gunicorn.conf.py

Todo es ajustable en backend/.env (o variables de entorno):
    GUNICORN_BIND     127.0.0.1:8001  (solo local: Nginx es el único que habla con Gunicorn)
    GUNICORN_WORKERS  2 × núcleos + 1, máximo 9
    GUNICORN_TIMEOUT  120 s (Excel del Kardex y Formato 13.1 pueden tardar)
    GUNICORN_LOG_LEVEL info
"""
import multiprocessing

# Lee las mismas fuentes que Django: variables de entorno y luego backend/.env.
from decouple import config as _leer


def _entero(nombre, defecto):
    try:
        return int(_leer(nombre, default=defecto))
    except ValueError:
        return defecto


bind = _leer('GUNICORN_BIND', default='127.0.0.1:8001')
workers = _entero('GUNICORN_WORKERS', min(multiprocessing.cpu_count() * 2 + 1, 9))
worker_class = 'sync'
timeout = _entero('GUNICORN_TIMEOUT', 120)
graceful_timeout = 30
keepalive = 5

# Reinicia cada worker tras N peticiones (evita crecimiento de memoria a largo plazo).
max_requests = _entero('GUNICORN_MAX_REQUESTS', 1000)
max_requests_jitter = 100

# Logs a stdout/stderr → journald (systemd). El access log no incluye cabeceras
# (Authorization nunca aparece) y la URL de la API no lleva tokens.
accesslog = '-'
errorlog = '-'
loglevel = _leer('GUNICORN_LOG_LEVEL', default='info')
access_log_format = '%({x-forwarded-for}i)s "%(r)s" %(s)s %(b)s %(M)sms'

# Solo se confía en X-Forwarded-* que vengan del propio servidor (Nginx).
forwarded_allow_ips = _leer('GUNICORN_FORWARDED_ALLOW_IPS', default='127.0.0.1')

# Sin --preload: cada worker abre su propia conexión a PostgreSQL.
preload_app = False
