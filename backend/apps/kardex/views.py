from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers
from rest_framework.response import Response

from config.api import PaginacionOpcional, entero_param
from apps.inventario.models import Producto
from apps.kardex.models import Incidencia, Movimiento, Recalculo, SaldoCppActual, StockAlmacen
from apps.kardex.services import ejecutar_recalculo_producto
from apps.usuarios.authentication import UsuarioTokenAuthentication
from apps.usuarios.permissions import EsAdminEmpresa, TieneEmpresaActiva


class ValorizacionSerializer(serializers.Serializer):
    costo_unitario_pen = serializers.DecimalField(max_digits=20, decimal_places=8)
    valor_movimiento_pen = serializers.DecimalField(max_digits=20, decimal_places=8)
    saldo_cantidad_empresa = serializers.DecimalField(max_digits=20, decimal_places=8)
    saldo_valor_empresa = serializers.DecimalField(max_digits=20, decimal_places=8)
    cpp_empresa = serializers.DecimalField(max_digits=20, decimal_places=8)


class MovimientoSerializer(serializers.ModelSerializer):
    valorizacion = ValorizacionSerializer(read_only=True)
    class Meta:
        model = Movimiento
        fields = ('id', 'producto', 'almacen', 'periodo', 'tipo_operacion', 'fecha_movimiento',
                  'prioridad_dia', 'secuencia', 'naturaleza', 'cantidad_base', 'valor_ajuste_pen',
                  'es_extorno', 'generado_por_motor', 'valorizacion')


class IncidenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Incidencia
        fields = ('id', 'periodo', 'producto', 'movimiento', 'tipo', 'severidad',
                  'bloquea_cierre', 'estado', 'descripcion', 'detalle', 'detectado_en', 'resuelto_en')
        read_only_fields = tuple(field for field in fields if field != 'estado')

    def validate_estado(self, value):
        if value not in ('RESUELTA', 'DESCARTADA'):
            raise serializers.ValidationError('Solo puede resolver o descartar una incidencia.')
        return value

    def update(self, instance, validated_data):
        instance.estado = validated_data['estado']
        instance.resuelto_por = self.context['request'].user
        instance.resuelto_en = timezone.now()
        instance.save(update_fields=['estado', 'resuelto_por', 'resuelto_en'])
        return instance


class RecalculoSerializer(serializers.ModelSerializer):
    detalles = serializers.SerializerMethodField()
    class Meta:
        model = Recalculo
        fields = ('id', 'producto', 'fecha_desde', 'fecha_hasta', 'version', 'estado', 'ejecutado_en', 'detalles')
    def get_detalles(self, obj):
        return list(obj.detalles.values('movimiento_id', 'cpp_anterior', 'cpp_nuevo',
                                        'valor_anterior', 'valor_nuevo', 'saldo_anterior', 'saldo_nuevo'))


class BaseMixin:
    authentication_classes = (UsuarioTokenAuthentication,)
    permission_classes = (TieneEmpresaActiva,)


class MovimientoListView(BaseMixin, generics.ListAPIView):
    serializer_class = MovimientoSerializer
    pagination_class = PaginacionOpcional
    def get_queryset(self):
        qs = Movimiento.objects.filter(empresa_id=self.request.empresa_id).select_related('valorizacion')
        for parametro, campo in (('producto', 'producto_id'), ('almacen', 'almacen_id'), ('periodo', 'periodo_id')):
            valor = entero_param(self.request.query_params, parametro)  # Bloque 6: 400 si no es un id
            if valor is not None: qs = qs.filter(**{campo: valor})
        return qs.order_by('fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')


class SaldosActualesView(BaseMixin, generics.GenericAPIView):
    def get(self, request):
        saldos = list(SaldoCppActual.objects.filter(empresa_id=request.empresa_id).values())
        stocks = list(StockAlmacen.objects.filter(empresa_id=request.empresa_id).values())
        return Response({'saldos_cpp': saldos, 'stocks_almacen': stocks})


class IncidenciaListView(BaseMixin, generics.ListAPIView):
    serializer_class = IncidenciaSerializer
    pagination_class = PaginacionOpcional
    def get_queryset(self):
        return Incidencia.objects.filter(empresa_id=self.request.empresa_id).order_by('-detectado_en', '-id')


class IncidenciaUpdateView(BaseMixin, generics.UpdateAPIView):
    serializer_class = IncidenciaSerializer
    permission_classes = (TieneEmpresaActiva, EsAdminEmpresa)
    http_method_names = ('patch', 'options')
    def get_queryset(self):
        return Incidencia.objects.filter(empresa_id=self.request.empresa_id)


class RecalculoListCreateView(BaseMixin, generics.ListCreateAPIView):
    serializer_class = RecalculoSerializer
    pagination_class = PaginacionOpcional
    def get_queryset(self):
        return Recalculo.objects.filter(empresa_id=self.request.empresa_id).prefetch_related('detalles').order_by('-ejecutado_en', '-id')  # Bloque 7: orden estable al paginar
    def create(self, request, *args, **kwargs):
        EsAdminEmpresa().has_permission(request, self)
        producto = get_object_or_404(Producto.objects.filter(empresa_id=request.empresa_id), pk=request.data.get('producto'))
        recalculo = ejecutar_recalculo_producto(
            empresa_id=request.empresa_id, producto_id=producto.id,
            fecha_desde=request.data.get('fecha_desde'), usuario_id=request.user.id,
        )
        return Response(self.get_serializer(recalculo).data, status=201)
