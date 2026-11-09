from datetime import datetime
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response

from apps.usuarios.authentication import UsuarioTokenAuthentication
from apps.usuarios.permissions import TieneEmpresaActiva
from apps.reportes.services import consultar_kardex_valorizado
from apps.reportes.serializers import KardexReporteResponseSerializer
from apps.reportes.excel_exporter import generar_bytes_excel_kardex
from apps.empresas.models import Periodo
from apps.reportes.formato131_excel import generar_excel_formato_131, nombre_archivo_formato_131
from apps.reportes.formato131_service import generar_formato_131
from apps.reportes.piloto_service import comparar_piloto, obtener_valores_factkard
from apps.reportes.serializers import PilotoComparacionSerializer
from config.api import entero_param, fecha_param, paginar_lista


def filtros_kardex(params):
    """Bloque 6: filtros del Kardex validados (400 ante ids o fechas inválidos)."""
    desde, hasta = fecha_param(params, 'fecha_desde'), fecha_param(params, 'fecha_hasta')
    if desde and hasta and desde > hasta:
        from rest_framework.exceptions import ValidationError
        raise ValidationError({'fecha_desde': 'La fecha desde no puede ser posterior a la fecha hasta.'})
    return {
        'producto_id': entero_param(params, 'producto_id', 'producto'),
        'periodo_id': entero_param(params, 'periodo_id', 'periodo'),
        'almacen_id': entero_param(params, 'almacen_id', 'almacen'),
        'tipo_operacion_id': entero_param(params, 'tipo_operacion_id', 'tipo_operacion'),
        'fecha_desde': desde.isoformat() if desde else None,
        'fecha_hasta': hasta.isoformat() if hasta else None,
    }


class KardexReportView(APIView):
    """
    GET /api/reportes/kardex/
    Consulta de Kardex Valorizado bajo el orden cronológico oficial del motor:
    (fecha_movimiento, prioridad_dia, secuencia, id).
    Requiere encabezado 'X-Empresa-Id' y token de sesión.
    """
    authentication_classes = (UsuarioTokenAuthentication,)
    permission_classes = (TieneEmpresaActiva,)

    def get(self, request, *args, **kwargs):
        empresa_id = request.empresa_id

        filtros = filtros_kardex(request.query_params)

        resultado = consultar_kardex_valorizado(
            empresa_id=empresa_id,
            **filtros,
        )

        # Bloque 6: paginación opcional de las filas; el resumen y el saldo inicial se
        # calculan siempre sobre el rango completo.
        resultado['movimientos'], paginacion = paginar_lista(request, resultado['movimientos'], self)
        data = KardexReporteResponseSerializer(resultado).data
        if paginacion is not None:
            data['paginacion'] = paginacion
        return Response(data)


class KardexExcelExportView(APIView):
    """
    GET /api/reportes/kardex/excel/
    Descarga del libro oficial de Kardex Valorizado en formato .xlsx con 4 hojas:
    1. Kardex Valorizado (1:1 con la vista en pantalla)
    2. Movimientos (detalle técnico)
    3. Incidencias (incidencias del período/empresa)
    4. Resumen de Saldos (resumen de stock y CPP por establecimiento)
    """
    authentication_classes = (UsuarioTokenAuthentication,)
    permission_classes = (TieneEmpresaActiva,)

    def get(self, request, *args, **kwargs):
        empresa_id = request.empresa_id

        filtros = filtros_kardex(request.query_params)

        buffer = generar_bytes_excel_kardex(
            empresa_id=empresa_id,
            **filtros,
        )

        nombre_archivo = f"kardex_empresa_{empresa_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
        return response


class Formato131View(APIView):
    authentication_classes = (UsuarioTokenAuthentication,)
    permission_classes = (TieneEmpresaActiva,)

    def get(self, request):
        params = request.query_params
        resultado = generar_formato_131(
            empresa_id=request.empresa_id,
            periodo_id=entero_param(params, 'periodo_id', requerido=True),
            establecimiento_id=entero_param(params, 'establecimiento_id'),
            producto_id=entero_param(params, 'producto_id'),
        )
        return Response(resultado)


class Formato131ExcelView(APIView):
    authentication_classes = (UsuarioTokenAuthentication,)
    permission_classes = (TieneEmpresaActiva,)

    def get(self, request):
        params = request.query_params
        periodo_id = entero_param(params, 'periodo_id', requerido=True)
        buffer = generar_excel_formato_131(
            empresa_id=request.empresa_id,
            periodo_id=periodo_id,
            establecimiento_id=entero_param(params, 'establecimiento_id'),
            producto_id=entero_param(params, 'producto_id'),
        )
        # Bloque 13: nombre descriptivo (período y RUC). El período ya se validó contra la empresa activa.
        periodo = Periodo.objects.select_related('empresa').get(pk=periodo_id, empresa_id=request.empresa_id)
        nombre = nombre_archivo_formato_131(periodo, periodo.empresa.ruc)
        response = HttpResponse(buffer.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{nombre}"'
        response['Content-Length'] = str(buffer.getbuffer().nbytes)
        buffer.close()
        return response


class PilotoComparadorView(APIView):
    authentication_classes = (UsuarioTokenAuthentication,)
    permission_classes = (TieneEmpresaActiva,)

    def get(self, request):
        periodo_id = entero_param(request.query_params, 'periodo_id', requerido=True)
        producto_id = entero_param(request.query_params, 'producto_id', requerido=True)
        return Response(obtener_valores_factkard(
            empresa_id=request.empresa_id,
            periodo_id=periodo_id,
            producto_id=producto_id,
        ))

    def post(self, request):
        serializer = PilotoComparacionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(comparar_piloto(
            empresa_id=request.empresa_id,
            datos=serializer.validated_data,
        ))


class RegistroComercialView(APIView):
    """Bloque 16: registro de ventas / compras del período (reporte interno, no PLE/SIRE)."""
    authentication_classes = (UsuarioTokenAuthentication,)
    permission_classes = (TieneEmpresaActiva,)
    clase = None
    excel = False

    def get(self, request):
        from apps.reportes.registro_comercial import excel_registro, generar_registro, nombre_archivo_registro
        params = request.query_params
        datos = generar_registro(
            empresa_id=request.empresa_id, clase=self.clase,
            periodo_id=entero_param(params, 'periodo_id', 'periodo', requerido=True),
            estado=(params.get('estado') or '').upper() or None, tercero_id=entero_param(params, 'tercero'),
        )
        if not self.excel:
            return Response(datos)
        buffer = excel_registro(datos)
        response = HttpResponse(buffer.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{nombre_archivo_registro(datos)}"'
        return response
