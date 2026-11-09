"""
Bloque 8 — health check para Nginx, systemd, monitoreo y el smoke test.

GET /api/health/ (sin autenticación):
- 200 {"status": "ok", "database": "ok", "cache": "ok"}
- 503 si PostgreSQL no responde, o si la caché (Redis en producción) falla: el throttling
  del login depende de ella, así que sin caché el login no funcionaría.

Nunca devuelve mensajes de excepción, hosts, versiones ni configuración: el detalle del
fallo va solo al log del servidor (logger `fact_kard.health`).
"""
import logging
import uuid

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger('fact_kard.health')


def _verificar_base_de_datos() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            return cursor.fetchone() == (1,)
    except Exception:  # noqa: BLE001 — cualquier fallo de la BD es "no disponible"
        logger.exception('Health check: PostgreSQL no disponible')
        return False


def _verificar_cache() -> bool:
    clave = f'health:{uuid.uuid4().hex}'
    try:
        cache.set(clave, '1', timeout=10)
        ok = cache.get(clave) == '1'
        cache.delete(clave)
        return ok
    except Exception:  # noqa: BLE001
        logger.exception('Health check: caché no disponible')
        return False


@never_cache
@require_GET
def health(request):
    base_de_datos = _verificar_base_de_datos()
    cache_ok = _verificar_cache()
    sano = base_de_datos and cache_ok
    return JsonResponse(
        {
            'status': 'ok' if sano else 'error',
            'database': 'ok' if base_de_datos else 'error',
            'cache': 'ok' if cache_ok else 'error',
        },
        status=200 if sano else 503,
    )
