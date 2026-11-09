from datetime import date

from django.db import transaction
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, ValidationError
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from rest_framework.permissions import IsAuthenticated
from config.api import fecha_param
from apps.usuarios.permissions import EsAdminOEsAdminGlobal
from apps.auditoria.services import registrar_auditoria
from apps.empresas.models import Empresa
from apps.usuarios.models import UsuarioEmpresa

from apps.catalogos.models import (
    Moneda,
    TipoCambio,
    TipoComprobante,
    TipoOperacion,
    TipoExistencia,
    UnidadMedida,
    MetodoPago,
    MotivoNota,
)
from apps.catalogos.serializers import (
    MonedaSerializer,
    TipoComprobanteSerializer,
    TipoOperacionSerializer,
    TipoExistenciaSerializer,
    UnidadMedidaSerializer,
    MetodoPagoSerializer,
    MotivoNotaSerializer,
    TipoCambioSerializer,
    TipoCambioResolverSerializer,
)


class MonedaListView(generics.ListAPIView):
    serializer_class = MonedaSerializer
    queryset = Moneda.objects.all().order_by('codigo')


class TipoComprobanteListView(generics.ListAPIView):
    serializer_class = TipoComprobanteSerializer
    queryset = TipoComprobante.objects.filter(activo=True).order_by('codigo_sunat')


class TipoOperacionListView(generics.ListAPIView):
    serializer_class = TipoOperacionSerializer
    queryset = TipoOperacion.objects.filter(activo=True).order_by('codigo_interno')


class TipoExistenciaListView(generics.ListAPIView):
    serializer_class = TipoExistenciaSerializer
    queryset = TipoExistencia.objects.all().order_by('codigo')


class MetodoPagoListView(generics.ListAPIView):
    """Bloque 16: métodos de pago activos (catálogo global)."""
    serializer_class = MetodoPagoSerializer
    queryset = MetodoPago.objects.filter(activo=True).order_by('codigo')
    pagination_class = None


class MotivoNotaListView(generics.ListAPIView):
    """
    Bloque 17A: motivos tributarios de notas. `?catalogo=09` (NC) o `10` (ND); por defecto
    solo activos (`?todos=1` incluye los inactivos).
    """
    serializer_class = MotivoNotaSerializer
    pagination_class = None

    def get_queryset(self):
        qs = MotivoNota.objects.all().order_by('catalogo', 'codigo')
        catalogo = self.request.query_params.get('catalogo')
        if catalogo:
            if catalogo not in ('09', '10'):
                raise ValidationError({'catalogo': 'Use 09 (nota de crédito) o 10 (nota de débito).'})
            qs = qs.filter(catalogo=catalogo)
        if self.request.query_params.get('todos') not in ('1', 'true'):
            qs = qs.filter(activo=True)
        return qs


class AfectacionIgvCatalogoView(APIView):
    """
    B17A-QA-001: Catálogo 07 (tipo de afectación del IGV) desde su fuente canónica
    (documentos/afectacion_igv.py): código, descripción oficial, afectación interna y soporte.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.documentos.afectacion_igv import catalogo_07
        return Response(catalogo_07())


class UnidadMedidaListView(generics.ListAPIView):
    serializer_class = UnidadMedidaSerializer
    queryset = UnidadMedida.objects.all().order_by('codigo')


class TipoCambioListCreateView(generics.ListCreateAPIView):
    serializer_class = TipoCambioSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), EsAdminOEsAdminGlobal()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = TipoCambio.objects.all().order_by('-fecha_publicacion', 'moneda_codigo')
        moneda = self.request.query_params.get('moneda')
        if moneda:
            qs = qs.filter(moneda_codigo=moneda.upper())
        fecha = fecha_param(self.request.query_params, 'fecha')  # Bloque 6: 400 si no es fecha
        if fecha:
            qs = qs.filter(fecha_publicacion=fecha)
        return qs

    def perform_create(self, serializer):
        # BE-001: el TipoCambio y su auditoría se guardan en una sola transacción.
        # Si la auditoría falla, el TipoCambio no queda persistido (rollback).
        with transaction.atomic():
            instance = serializer.save()
            registrar_auditoria(
                empresa_id=self._empresa_id_auditoria(),
                usuario_id=self.request.user.id,
                accion='CREAR',
                entidad='TIPO_CAMBIO',
                registro_id=instance.id,
                valor_anterior=None,
                valor_nuevo={
                    'moneda_codigo': instance.moneda_codigo_id,
                    'fecha_publicacion': str(instance.fecha_publicacion),
                    'compra': str(instance.compra),
                    'venta': str(instance.venta),
                    'fuente': instance.fuente,
                },
                motivo='Registro contable oficial de tipo de cambio SBS',
            )

    def _empresa_id_auditoria(self):
        """
        El tipo de cambio es global. Se asocia la auditoría a la empresa del header
        solo si el usuario tiene una asignación activa en ella; si no, queda sin empresa.
        """
        empresa_id_raw = (
            self.request.headers.get('X-Empresa-Id') or
            self.request.META.get('HTTP_X_EMPRESA_ID')
        )
        try:
            empresa_id = int(empresa_id_raw)
        except (TypeError, ValueError):
            return None
        usuario = self.request.user
        if getattr(usuario, 'es_admin_global', False):
            return empresa_id if Empresa.objects.filter(pk=empresa_id).exists() else None
        asignado = UsuarioEmpresa.objects.filter(
            usuario_id=usuario.id, empresa_id=empresa_id, activo=True,
        ).exists()
        return empresa_id if asignado else None


class TipoCambioResolverView(APIView):
    """
    Resuelve el tipo de cambio aplicable según la regla oficial contable de FACT-KARD:
    - Devuelve el TC publicado en la fecha exacta del documento.
    - Si la fecha corresponde a fin de semana o feriado (sin publicación),
      toma el último TC publicado anterior o igual a la fecha consultada (fecha_publicacion <= fecha).
    """

    @extend_schema(
        summary="Resolver Tipo de Cambio contable oficial",
        description="Devuelve el TC publicado para la fecha o el último publicado previo (fin de semana/feriado).",
        parameters=[
            OpenApiParameter(name='moneda', description='Código de moneda (ej: USD)', required=False, type=str, default='USD'),
            OpenApiParameter(name='fecha', description='Fecha del documento (YYYY-MM-DD)', required=True, type=str),
        ],
        responses={
            200: TipoCambioResolverSerializer,
            400: OpenApiResponse(description="Parámetros inválidos"),
            404: OpenApiResponse(description="No existe tipo de cambio aplicable"),
        }
    )
    def get(self, request):
        moneda_raw = request.query_params.get('moneda', 'USD').strip().upper()
        fecha_raw = request.query_params.get('fecha')

        if not fecha_raw:
            raise ValidationError({'fecha': 'El parámetro fecha es obligatorio (formato YYYY-MM-DD).'})

        try:
            fecha_consultada = date.fromisoformat(fecha_raw)
        except ValueError:
            raise ValidationError({'fecha': 'Formato de fecha inválido. Utilice YYYY-MM-DD.'})

        # Regla contable: buscar el TC con fecha_publicacion <= fecha_consultada más reciente
        tc = (
            TipoCambio.objects.filter(
                moneda_codigo=moneda_raw,
                fecha_publicacion__lte=fecha_consultada,
            )
            .order_by('-fecha_publicacion', '-id')
            .first()
        )

        if not tc:
            raise NotFound(
                f"No existe tipo de cambio registrado para {moneda_raw} al {fecha_consultada.isoformat()} ni en fechas anteriores."
            )

        data = {
            'id': tc.id,
            'moneda_codigo': tc.moneda_codigo_id,
            'fecha_publicacion': tc.fecha_publicacion,
            'fecha_consultada': fecha_consultada,
            'es_fecha_exacta': tc.fecha_publicacion == fecha_consultada,
            'venta': tc.venta,
            'compra': tc.compra,
            'fuente': tc.fuente,
        }
        serializer = TipoCambioResolverSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)
