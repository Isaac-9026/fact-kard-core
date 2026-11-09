"""
Bloque 17C — servicio central: consultar_ruc(numero_ruc).

1. Valida el RUC con la regla existente (documentos_identidad: 11 dígitos, prefijo y dígito
   verificador). Un RUC inválido NUNCA llega al proveedor.
2. Busca en la caché de Django (local o la ya configurada); solo se cachean respuestas
   exitosas y por un tiempo limitado: la caché no es fuente de verdad. La clave incluye el
   proveedor, la VERSIÓN de sus datos (Bloque 17D: al activar un padrón nuevo las claves cambian
   y no se devuelve el resultado viejo) y el RUC.
3. Consulta al proveedor con timeout; cualquier fallo inesperado se convierte en
   SERVICIO_NO_DISPONIBLE sin exponer trazas.
4. Normaliza (schemas.normalizar) sin inventar datos.
"""
import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.inventario.documentos_identidad import RUC, validar_documento_identidad

from .providers import obtener_proveedor
from .schemas import ErrorConsultaRuc, RucInvalido, RucNoEncontrado, ServicioNoDisponible, normalizar

logger = logging.getLogger('fact_kard.consulta_ruc')
VERSION_CACHE = 'v2'


def validar_ruc(numero):
    """RUC normalizado (11 dígitos) o RucInvalido con el mensaje de la regla existente."""
    _tipo, normalizado, error = validar_documento_identidad(RUC, numero)
    if error:
        raise RucInvalido(error)
    return normalizado


def clave_cache(ruc, proveedor, version=''):
    return f'consulta_ruc:{VERSION_CACHE}:{proveedor}:{version or "-"}:{ruc}'


def consultar_ruc(numero_ruc, *, proveedor=None, usar_cache=True):
    """
    {'datos': {...CAMPOS}, 'advertencias': [...], 'proveedor', 'oficial', 'desde_cache',
     'consultado_en'} o ErrorConsultaRuc (RUC_INVALIDO, RUC_NO_ENCONTRADO, SERVICIO_NO_DISPONIBLE,
     RESPUESTA_INCOMPLETA, PROVEEDOR_RUC_NO_CONFIGURADO, PADRON_RUC_NO_CARGADO). El error lleva
     `.proveedor` con el nombre del proveedor usado.
    """
    ruc = validar_ruc(numero_ruc)
    proveedor = proveedor or obtener_proveedor()
    try:
        return _consultar(ruc, proveedor, usar_cache)
    except ErrorConsultaRuc as exc:
        exc.proveedor = proveedor.nombre  # para la auditoría (sin datos de la respuesta)
        raise


def _consultar(ruc, proveedor, usar_cache):
    try:
        version = proveedor.version_datos()
    except ErrorConsultaRuc:
        raise
    except Exception as exc:  # noqa: BLE001 — p. ej. base de datos caída: sin trazas al usuario
        logger.warning('Consulta RUC: versión no disponible (%s): %s', proveedor.nombre, type(exc).__name__)
        raise ServicioNoDisponible() from None
    clave = clave_cache(ruc, proveedor.nombre, version)
    if usar_cache:
        try:
            guardado = cache.get(clave)
        except Exception:  # noqa: BLE001 — una caché caída no impide consultar
            guardado = None
        if guardado:
            return {**guardado, 'desde_cache': True}

    timeout = float(getattr(settings, 'CONSULTA_RUC_TIMEOUT_SEGUNDOS', 8))
    try:
        crudo = proveedor.consultar(ruc, timeout=timeout)
        actualizado_al = proveedor.actualizado_al()
    except ErrorConsultaRuc:
        raise
    except Exception as exc:  # noqa: BLE001 — timeout, red, respuesta rota: nunca una traza al usuario
        logger.warning('Consulta RUC fallida (%s): %s', proveedor.nombre, type(exc).__name__)
        raise ServicioNoDisponible() from None
    if crudo is None:
        raise RucNoEncontrado()
    datos, advertencias = normalizar(crudo, ruc)
    resultado = {
        'datos': datos.a_dict(), 'advertencias': advertencias, 'proveedor': proveedor.nombre,
        'oficial': bool(proveedor.oficial), 'fuente': proveedor.fuente or None, 'actualizado_al': actualizado_al,
        'version_datos': version or None, 'consultado_en': timezone.now().isoformat(),
    }
    if usar_cache:
        try:
            cache.set(clave, resultado, int(getattr(settings, 'CONSULTA_RUC_CACHE_SEGUNDOS', 43200)))
        except Exception:  # noqa: BLE001
            pass
    return {**resultado, 'desde_cache': False}
