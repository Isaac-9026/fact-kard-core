"""
Bloque 7 — advertencias de despliegue (`python manage.py check --deploy`).

No bloquean el arranque (las reglas obligatorias están en config/seguridad.py), pero
señalan configuraciones aceptables en desarrollo y débiles en producción.
"""
from django.conf import settings
from django.core.checks import Tags, Warning, register

from config.cache import es_cache_local

TOKEN_RECOMENDADO_MAXIMO = 60 * 60 * 24  # 24 horas


@register(Tags.security, deploy=True)
def revisar_produccion(app_configs=None, **kwargs):
    avisos = []
    if es_cache_local(settings.CACHES):
        avisos.append(Warning(
            'La caché es local en memoria: con varios workers cada uno lleva su propio '
            'contador del throttling de login.',
            hint='Define CACHE_URL=redis://host:6379/0 e instala requirements-prod.txt.',
            id='fact_kard.W001',
        ))
    if settings.TOKEN_MAX_AGE_SECONDS > TOKEN_RECOMENDADO_MAXIMO:
        avisos.append(Warning(
            'TOKEN_MAX_AGE_SECONDS supera 24 horas.',
            hint='En producción se recomienda 8–12 horas (28800–43200).',
            id='fact_kard.W002',
        ))
    if getattr(settings, 'PRODUCCION_SIN_HTTPS', False):
        avisos.append(Warning(
            'PRODUCCION_SIN_HTTPS=True: las cookies y los tokens viajan sin cifrar.',
            hint='Úsalo solo en una red interna de confianza; configura HTTPS en cuanto sea posible.',
            id='fact_kard.W003',
        ))
    return avisos
