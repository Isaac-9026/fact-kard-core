from decimal import Decimal
from rest_framework import serializers

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


class MonedaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Moneda
        fields = ('codigo', 'nombre')


class TipoComprobanteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoComprobante
        fields = ('id', 'codigo_sunat', 'descripcion', 'es_nota', 'efecto_nota', 'activo')


class TipoOperacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoOperacion
        fields = (
            'id', 'codigo_interno', 'codigo_sunat', 'descripcion',
            'naturaleza', 'es_interna', 'afecta_kardex', 'origen_requerido', 'activo'
        )


class TipoExistenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoExistencia
        fields = ('codigo', 'descripcion')


class MotivoNotaSerializer(serializers.ModelSerializer):
    """Bloque 17A: motivo tributario de NC (catálogo 09) / ND (catálogo 10)."""
    class Meta:
        model = MotivoNota
        fields = ('id', 'catalogo', 'codigo', 'descripcion', 'activo')


class MetodoPagoSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetodoPago
        fields = ('codigo', 'descripcion', 'activo')


class UnidadMedidaSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnidadMedida
        fields = ('codigo', 'descripcion')


class TipoCambioSerializer(serializers.ModelSerializer):
    moneda_codigo = serializers.PrimaryKeyRelatedField(
        queryset=Moneda.objects.all()
    )
    venta = serializers.DecimalField(max_digits=20, decimal_places=8, coerce_to_string=True)
    compra = serializers.DecimalField(max_digits=20, decimal_places=8, coerce_to_string=True)

    class Meta:
        model = TipoCambio
        fields = ('id', 'moneda_codigo', 'fecha_publicacion', 'venta', 'compra', 'fuente')

    def validate_venta(self, value):
        if value is not None and value <= Decimal('0.00000000'):
            raise serializers.ValidationError("El tipo de cambio venta debe ser mayor a cero.")
        return value

    def validate_compra(self, value):
        if value is not None and value <= Decimal('0.00000000'):
            raise serializers.ValidationError("El tipo de cambio compra debe ser mayor a cero.")
        return value


class TipoCambioResolverSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    moneda_codigo = serializers.CharField()
    fecha_publicacion = serializers.DateField()
    fecha_consultada = serializers.DateField()
    es_fecha_exacta = serializers.BooleanField()
    venta = serializers.DecimalField(max_digits=20, decimal_places=8, coerce_to_string=True)
    compra = serializers.DecimalField(max_digits=20, decimal_places=8, coerce_to_string=True)
    fuente = serializers.CharField()
