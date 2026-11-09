"""
Bloque 8 — logging de producción.

- Por defecto todo va a stdout/stderr: con systemd lo recoge journald (rotación incluida).
- Opcional LOG_FILE: además a un archivo con rotación por tamaño (LOG_FILE_MAX_MB, LOG_FILE_BACKUPS).
- Loggers:
  * django.request  → errores 500 (con traza) y 4xx relevantes.
  * django.security → host no permitido, CSRF, etc.
  * fact_kard.auth  → login correcto/fallido/bloqueado y logout (sin contraseñas ni tokens).
  * fact_kard.*     → health check y otros fallos importantes.
- FiltroDatosSensibles enmascara en TODOS los mensajes: tokens Bearer, tokens firmados de
  FACT-KARD, contraseñas en texto "password=…", claves en URLs (redis://:clave@…), la
  SECRET_KEY y (Bloque 17B) las credenciales SUNAT: clave/usuario SOL y contraseña del
  certificado, tanto por nombre ("clave_sol=…") como por valor. Es una red de seguridad: el
  código no debe registrar esos datos a propósito.
"""
import logging
import re

ENMASCARADO = '[OCULTO]'

PATRONES = [
    # Authorization: Bearer <token> / Token <token>
    (re.compile(r'(?i)\b(bearer|token)\s+[A-Za-z0-9._:\-]{12,}'), r'\1 ' + ENMASCARADO),
    # Token firmado de django.core.signing (payload:timestamp:firma)
    (re.compile(r'\b[A-Za-z0-9_\-]{20,}:[A-Za-z0-9_\-]{4,}:[A-Za-z0-9_\-]{20,}\b'), ENMASCARADO),
    # password=..., "password": "...", contraseña: ...
    (re.compile(r'(?i)("?(?:password|passwd|contrase(?:ñ|n)a|secret_key|db_password)"?\s*[:=]\s*)("[^"]*"|\'[^\']*\'|[^\s,;&}]+)'),
     r'\1' + ENMASCARADO),
    # Bloques PEM (claves privadas o certificados) pegados en un mensaje
    (re.compile(r'-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----', re.S), ENMASCARADO),
    # Credenciales dentro de URLs: esquema://usuario:clave@host
    (re.compile(r'(\b[a-z][a-z0-9+.\-]*://[^:/\s@]*:)[^@\s/]+@'), r'\1' + ENMASCARADO + '@'),
]


def enmascarar(texto: str, secretos=()) -> str:
    for patron, reemplazo in PATRONES:
        texto = patron.sub(reemplazo, texto)
    for secreto in secretos:
        if secreto and len(secreto) >= 8:
            texto = texto.replace(secreto, ENMASCARADO)
    return texto


class FiltroDatosSensibles(logging.Filter):
    def __init__(self, name=''):
        super().__init__(name)
        self._secretos = None

    def _obtener_secretos(self):
        if self._secretos is None:
            try:
                from django.conf import settings
                self._secretos = tuple(s for s in (
                    getattr(settings, 'SECRET_KEY', ''),
                    settings.DATABASES.get('default', {}).get('PASSWORD', ''),
                ) if s)
            except Exception:  # noqa: BLE001 — antes de que Django esté configurado
                return ()
        return self._secretos

    def filter(self, record: logging.LogRecord) -> bool:
        secretos = self._obtener_secretos()
        try:
            mensaje = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        limpio = enmascarar(mensaje, secretos)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = enmascarar(record.exc_text, secretos)
        if limpio != mensaje or record.args:
            record.msg, record.args = limpio, None
        return True


def construir_logging(*, nivel: str = 'INFO', archivo: str = '', max_mb: int = 20, respaldos: int = 10,
                      silencioso: bool = False) -> dict:
    handlers = {
        'consola': {
            'class': 'logging.StreamHandler',
            # En `manage.py test` la consola solo muestra errores críticos (los tests usan assertLogs).
            'level': 'CRITICAL' if silencioso else 'NOTSET',
            'formatter': 'simple',
            'filters': ['sensibles'],
        },
    }
    if archivo:
        handlers['archivo'] = {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': archivo,
            'maxBytes': max(1, max_mb) * 1024 * 1024,
            'backupCount': max(1, respaldos),
            'encoding': 'utf-8',
            'formatter': 'simple',
            'filters': ['sensibles'],
        }
    destinos = list(handlers)
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'filters': {'sensibles': {'()': 'config.registro.FiltroDatosSensibles'}},
        'formatters': {
            'simple': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'},
        },
        'handlers': handlers,
        'root': {'handlers': destinos, 'level': 'WARNING'},
        'loggers': {
            'django': {'handlers': destinos, 'level': 'INFO', 'propagate': False},
            'django.request': {'handlers': destinos, 'level': 'WARNING', 'propagate': False},
            'django.security': {'handlers': destinos, 'level': 'WARNING', 'propagate': False},
            # Las consultas SQL nunca se registran (pueden contener datos de negocio).
            'django.db.backends': {'handlers': destinos, 'level': 'WARNING', 'propagate': False},
            'fact_kard': {'handlers': destinos, 'level': nivel, 'propagate': False},
        },
    }
