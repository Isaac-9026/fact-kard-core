"""
Bloque 7 — caché configurable por variables de entorno.

La caché guarda, entre otros, los contadores del throttling de login. Con la caché local
en memoria (por defecto) cada proceso/worker lleva su propio contador; en producción con
varios workers conviene una caché compartida (Redis).

Variables:
- CACHE_URL (alias REDIS_URL): `redis://[:clave@]host:6379/0`, `rediss://...` (TLS) o
  `unix:///ruta/redis.sock`. Vacía → caché local en memoria (desarrollo, sin Redis).
- CACHE_KEY_PREFIX: prefijo de las claves (por defecto `fact-kard`), útil si el Redis se
  comparte con otras aplicaciones.

Redis NO es obligatorio para ejecutar el proyecto en local: el paquete `redis` solo se
exige cuando CACHE_URL apunta a un servidor Redis (requirements-prod.txt).
"""
from django.core.exceptions import ImproperlyConfigured

BACKEND_LOCAL = 'django.core.cache.backends.locmem.LocMemCache'
BACKEND_REDIS = 'django.core.cache.backends.redis.RedisCache'
ESQUEMAS_REDIS = ('redis://', 'rediss://', 'unix://')


def _redis_disponible() -> bool:
    try:
        import redis  # noqa: F401
    except ImportError:
        return False
    return True


def configurar_caches(url: str | None, *, prefijo: str = 'fact-kard', redis_disponible=_redis_disponible) -> dict:
    url = (url or '').strip()
    if not url:
        return {'default': {'BACKEND': BACKEND_LOCAL, 'LOCATION': 'fact-kard-local'}}
    if not url.startswith(ESQUEMAS_REDIS):
        raise ImproperlyConfigured(
            'CACHE_URL no es una URL de Redis válida (redis://, rediss:// o unix://). '
            'Déjala vacía para usar la caché local en memoria.'
        )
    if not redis_disponible():
        raise ImproperlyConfigured(
            'CACHE_URL apunta a Redis pero el paquete "redis" no está instalado '
            '(pip install -r requirements-prod.txt).'
        )
    return {
        'default': {
            'BACKEND': BACKEND_REDIS,
            'LOCATION': url,
            'KEY_PREFIX': prefijo or 'fact-kard',
        }
    }


def es_cache_local(caches: dict) -> bool:
    return caches.get('default', {}).get('BACKEND') == BACKEND_LOCAL
