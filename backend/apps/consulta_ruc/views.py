"""Bloque 17C — GET /api/consulta-ruc/<ruc>/ (solo consulta; no guarda nada)."""
from django.conf import settings
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.auditoria.services import registrar_auditoria
from apps.usuarios.permissions import EsAdminEmpresa, TieneEmpresaActiva

from .providers import ProveedorNoConfigurado, obtener_proveedor
from .schemas import ErrorConsultaRuc, RucInvalido
from .service import consultar_ruc


class ConsultaRucThrottle(SimpleRateThrottle):
    """Límite por usuario (settings.CONSULTA_RUC_THROTTLE_RATE, p. ej. '30/min')."""
    scope = 'consulta_ruc'

    def get_rate(self):
        return getattr(settings, 'CONSULTA_RUC_THROTTLE_RATE', '30/min')

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': getattr(request.user, 'pk', None) or self.get_ident(request)}


class ConsultaRucView(APIView):
    """
    Consulta los datos fiscales de un RUC para autocompletar Empresa / Datos fiscales / Tercero.
    Solo ADMIN de la empresa activa (son quienes pueden guardar esos datos). Devuelve únicamente
    datos públicos del contribuyente consultado; nada de otras empresas ni secretos.
    """
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]
    throttle_classes = [ConsultaRucThrottle]

    def get(self, request, ruc):
        try:
            resultado = consultar_ruc(ruc)
        except RucInvalido as exc:  # no llega al proveedor ni se audita (no es una consulta)
            return Response({'codigo': exc.codigo, 'mensaje': exc.mensaje}, status=exc.http_status)
        except ErrorConsultaRuc as exc:
            self._auditar(request, ruc, exc.codigo, None, getattr(exc, 'proveedor', None))
            return Response({'codigo': exc.codigo, 'mensaje': exc.mensaje}, status=exc.http_status)
        self._auditar(request, resultado['datos']['ruc'], 'EXITO', resultado, resultado['proveedor'])
        return Response(resultado)

    @staticmethod
    def _auditar(request, ruc, resultado, datos, proveedor):
        # Solo lo útil para auditar: RUC, resultado, proveedor, versión de datos y si vino de caché.
        # Nunca la respuesta completa.
        registrar_auditoria(
            empresa_id=request.empresa_id, usuario_id=request.user.pk, accion='CONSULTA_RUC', entidad='consulta_ruc',
            valor_nuevo={
                'ruc': ''.join(c for c in str(ruc) if c.isdigit())[:11], 'resultado': resultado,
                'proveedor': proveedor,
                'version_datos': datos.get('version_datos') if datos else None,
                'desde_cache': datos['desde_cache'] if datos else None,
            },
        )


class ConsultaRucEstadoView(APIView):
    """
    Bloque 17D — GET /api/configuracion/consulta-ruc/estado/: proveedor configurado y, si es el
    padrón, sus metadatos (versión, fecha, registros). Solo metadatos, nunca filas. Solo ADMIN.
    """
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]

    def get(self, request):
        proveedor = obtener_proveedor()
        try:
            estado = proveedor.estado()
        except Exception:  # noqa: BLE001 — sin trazas: se informa como no disponible
            estado = {'disponible': False}
        configurado = (getattr(settings, 'CONSULTA_RUC_PROVEEDOR', '') or '').strip().lower() or None
        return Response({
            'proveedor': proveedor.nombre if not isinstance(proveedor, ProveedorNoConfigurado) else None,
            'configurado': configurado is not None and not isinstance(proveedor, ProveedorNoConfigurado),
            'oficial': bool(proveedor.oficial),
            'fuente': proveedor.fuente or None,
            'disponible': bool(estado.get('disponible')),
            'registros': estado.get('registros'),
            'version': estado.get('version'),
            'fecha_padron': estado.get('fecha_padron'),
            'fecha_importacion': estado.get('fecha_importacion'),
        })
