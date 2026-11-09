from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from rest_framework import serializers
from django.utils import timezone

from apps.catalogos.models import TipoExistencia, TipoOperacion, UnidadMedida
from apps.empresas.models import Establecimiento, Periodo
from apps.auditoria.services import registrar_auditoria
from apps.inventario.documentos_identidad import validar_documento_identidad
from apps.inventario.homologacion import equivalencia_activa_repetida, limpiar_texto, normalizar_texto
from apps.inventario.models import (
    Almacen,
    NotaInterna,
    NotaInternaDetalle,
    Producto,
    ProductoEquivalencia,
    ProductoUnidad,
    SaldoInicial,
    Tercero,
    Transferencia,
    TransferenciaDetalle,
)


DECIMAL_CERO = Decimal('0.00000000')
DECIMAL_OPERATIVO = Decimal('0.000001')
TIPOS_NOTA_ESTANDAR = {
    'MERMA', 'DESMEDRO', 'CONSUMO_INTERNO', 'RETIRO',
}
TIPOS_NOTA_ADMIN = {
    'AJUSTE_INGRESO', 'AJUSTE_SALIDA', 'AJUSTE_VALOR_MANUAL',
}
TIPOS_NOTA_PERMITIDOS = TIPOS_NOTA_ESTANDAR | TIPOS_NOTA_ADMIN


def _empresa_id(serializer):
    empresa_id = serializer.context.get('empresa_id')
    if empresa_id is None:
        raise serializers.ValidationError('No se pudo determinar la empresa activa.')
    return empresa_id


class AlmacenSerializer(serializers.ModelSerializer):
    establecimiento = serializers.PrimaryKeyRelatedField(
        queryset=Establecimiento.objects.none(),
    )
    establecimiento_codigo = serializers.CharField(
        source='establecimiento.codigo_sunat', read_only=True,
    )
    establecimiento_nombre = serializers.CharField(
        source='establecimiento.nombre', read_only=True,
    )

    class Meta:
        model = Almacen
        fields = (
            'id', 'empresa', 'establecimiento', 'establecimiento_codigo',
            'establecimiento_nombre', 'codigo', 'nombre', 'activo',
        )
        read_only_fields = ('id', 'empresa')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empresa_id = self.context.get('empresa_id')
        if empresa_id is not None:
            self.fields['establecimiento'].queryset = Establecimiento.objects.filter(
                empresa_id=empresa_id,
            )

    def to_internal_value(self, data):
        if 'establecimiento_id' in data and 'establecimiento' not in data:
            data = data.copy()
            data['establecimiento'] = data['establecimiento_id']
        return super().to_internal_value(data)

    def validate(self, attrs):
        empresa_id = _empresa_id(self)
        codigo = attrs.get('codigo', getattr(self.instance, 'codigo', None))
        duplicado = Almacen.objects.filter(empresa_id=empresa_id, codigo=codigo)
        if self.instance is not None:
            duplicado = duplicado.exclude(pk=self.instance.pk)
        if duplicado.exists():
            raise serializers.ValidationError(
                {'codigo': 'Ya existe un almacén con este código en la empresa activa.'}
            )
        return attrs


class TerceroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tercero
        fields = (
            'id', 'empresa', 'tipo_documento', 'numero_documento',
            'razon_social', 'nombre_comercial', 'direccion', 'telefono',
            'correo', 'es_cliente', 'es_proveedor', 'estado', 'creado_en',
            'actualizado_en',
        )
        read_only_fields = ('id', 'empresa', 'creado_en', 'actualizado_en')

    def validate(self, attrs):
        empresa_id = _empresa_id(self)
        # Bloque 16: catálogo 06 + validación de DNI/RUC (dígito verificador). 'RUC'/'DNI' se
        # convierten al código, así '6' y 'RUC' con el mismo número son la misma identidad.
        if 'tipo_documento' in attrs or 'numero_documento' in attrs or self.instance is None:
            tipo, numero, error = validar_documento_identidad(
                attrs.get('tipo_documento', getattr(self.instance, 'tipo_documento', None)),
                attrs.get('numero_documento', getattr(self.instance, 'numero_documento', None)),
            )
            if error:
                campo = 'tipo_documento' if 'Tipo de documento' in error else 'numero_documento'
                raise serializers.ValidationError({campo: error})
            attrs['tipo_documento'], attrs['numero_documento'] = tipo, numero
        es_cliente = attrs.get('es_cliente', getattr(self.instance, 'es_cliente', False))
        es_proveedor = attrs.get('es_proveedor', getattr(self.instance, 'es_proveedor', False))
        if not es_cliente and not es_proveedor:
            raise serializers.ValidationError(
                'El tercero debe ser cliente, proveedor o ambos.'
            )

        tipo_documento = attrs.get(
            'tipo_documento', getattr(self.instance, 'tipo_documento', None)
        )
        numero_documento = attrs.get(
            'numero_documento', getattr(self.instance, 'numero_documento', None)
        )
        duplicado = Tercero.objects.filter(
            empresa_id=empresa_id,
            tipo_documento=tipo_documento,
            numero_documento=numero_documento,
        )
        if self.instance is not None:
            duplicado = duplicado.exclude(pk=self.instance.pk)
        if duplicado.exists():
            raise serializers.ValidationError({
                'numero_documento': (
                    'Ya existe un tercero con este tipo y número de documento '
                    'en la empresa activa.'
                )
            })
        return attrs

    def validate_estado(self, value):
        if value not in ('ACTIVO', 'INACTIVO'):
            raise serializers.ValidationError('El estado debe ser ACTIVO o INACTIVO.')
        return value

    def update(self, instance, validated_data):
        validated_data['actualizado_en'] = timezone.now()
        return super().update(instance, validated_data)


class ProductoSerializer(serializers.ModelSerializer):
    tipo_existencia_codigo = serializers.PrimaryKeyRelatedField(
        queryset=TipoExistencia.objects.all(),
    )
    tipo_existencia_descripcion = serializers.CharField(
        source='tipo_existencia_codigo.descripcion', read_only=True,
    )
    unidad_base_codigo = serializers.PrimaryKeyRelatedField(
        queryset=UnidadMedida.objects.all(),
        write_only=True,
        required=False,
    )
    unidad_base = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = (
            'id', 'empresa', 'codigo_interno', 'descripcion',
            'tipo_existencia_codigo', 'tipo_existencia_descripcion', 'estado',
            'unidad_base_codigo', 'unidad_base',
            # Bloque 16: datos comerciales (solo sugerencias; no afectan costo, CPP ni Kardex).
            'precio_venta_sugerido', 'afectacion_igv_defecto',
        )
        read_only_fields = ('id', 'empresa', 'unidad_base')

    def get_unidad_base(self, obj):
        unidad = next((item for item in obj.unidades.all() if item.es_base), None)
        if unidad is None:
            return None
        return {
            'id': unidad.id,
            'codigo': unidad.unidad_codigo_id,
            'descripcion': unidad.unidad_codigo.descripcion,
            'factor_a_base': format(unidad.factor_a_base, '.8f'),
        }

    def validate(self, attrs):
        empresa_id = _empresa_id(self)
        if self.instance is None and 'unidad_base_codigo' not in attrs:
            raise serializers.ValidationError({
                'unidad_base_codigo': 'Debe seleccionar la unidad base del producto.'
            })
        if self.instance is not None and 'unidad_base_codigo' in attrs:
            raise serializers.ValidationError({
                'unidad_base_codigo': 'La unidad base se administra desde el panel de unidades.'
            })

        codigo = attrs.get('codigo_interno', getattr(self.instance, 'codigo_interno', None))
        duplicado = Producto.objects.filter(empresa_id=empresa_id, codigo_interno=codigo)
        if self.instance is not None:
            duplicado = duplicado.exclude(pk=self.instance.pk)
        if duplicado.exists():
            raise serializers.ValidationError({
                'codigo_interno': 'Ya existe un producto con este código en la empresa activa.'
            })
        return attrs

    def validate_estado(self, value):
        if value not in ('ACTIVO', 'INACTIVO'):
            raise serializers.ValidationError('El estado debe ser ACTIVO o INACTIVO.')
        return value

    def validate_precio_venta_sugerido(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError('El precio de venta sugerido no puede ser negativo.')
        return value.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP) if value is not None else None

    def create(self, validated_data):
        unidad_base = validated_data.pop('unidad_base_codigo')
        producto = Producto.objects.create(
            empresa_id=_empresa_id(self),
            **validated_data,
        )
        ProductoUnidad.objects.create(
            producto=producto,
            unidad_codigo=unidad_base,
            factor_a_base=Decimal('1.00000000'),
            es_base=True,
        )
        return producto


class ProductoUnidadSerializer(serializers.ModelSerializer):
    unidad_codigo = serializers.PrimaryKeyRelatedField(
        queryset=UnidadMedida.objects.all(),
    )
    unidad_descripcion = serializers.CharField(
        source='unidad_codigo.descripcion', read_only=True,
    )
    factor_a_base = serializers.DecimalField(
        max_digits=20,
        decimal_places=8,
        coerce_to_string=True,
    )

    class Meta:
        model = ProductoUnidad
        fields = (
            'id', 'producto', 'unidad_codigo', 'unidad_descripcion',
            'factor_a_base', 'es_base',
        )
        read_only_fields = ('id', 'producto')

    def validate(self, attrs):
        producto = self.context.get('producto')
        if producto is None:
            raise serializers.ValidationError('No se pudo determinar el producto.')

        unidad = attrs.get('unidad_codigo', getattr(self.instance, 'unidad_codigo', None))
        factor = attrs.get('factor_a_base', getattr(self.instance, 'factor_a_base', None))
        es_base = attrs.get('es_base', getattr(self.instance, 'es_base', False))

        duplicado = ProductoUnidad.objects.filter(
            producto=producto,
            unidad_codigo=unidad,
        )
        if self.instance is not None:
            duplicado = duplicado.exclude(pk=self.instance.pk)
        if duplicado.exists():
            raise serializers.ValidationError({
                'unidad_codigo': 'Esta unidad ya está asociada al producto.'
            })

        if factor is not None and factor <= Decimal('0.00000000'):
            raise serializers.ValidationError({
                'factor_a_base': 'El factor debe ser mayor que cero.'
            })
        if es_base and factor != Decimal('1.00000000'):
            raise serializers.ValidationError({
                'factor_a_base': 'La unidad base debe tener factor 1.00000000.'
            })

        otra_base = ProductoUnidad.objects.filter(producto=producto, es_base=True)
        if self.instance is not None:
            otra_base = otra_base.exclude(pk=self.instance.pk)
        if es_base and otra_base.exists():
            raise serializers.ValidationError({
                'es_base': 'El producto ya tiene una unidad base.'
            })
        if self.instance is not None and self.instance.es_base and not es_base:
            raise serializers.ValidationError({
                'es_base': 'No se puede dejar el producto sin unidad base.'
            })
        if self.instance is None and not es_base and not otra_base.exists():
            raise serializers.ValidationError({
                'es_base': 'El producto debe conservar exactamente una unidad base.'
            })
        return attrs

    def create(self, validated_data):
        return ProductoUnidad.objects.create(
            producto=self.context['producto'],
            **validated_data,
        )


class TipoExistenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoExistencia
        fields = ('codigo', 'descripcion')
        read_only_fields = fields


class UnidadMedidaSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnidadMedida
        fields = ('codigo', 'descripcion')
        read_only_fields = fields


class SaldoInicialSerializer(serializers.ModelSerializer):
    periodo = serializers.PrimaryKeyRelatedField(queryset=Periodo.objects.none())
    almacen = serializers.PrimaryKeyRelatedField(queryset=Almacen.objects.none())
    producto = serializers.PrimaryKeyRelatedField(queryset=Producto.objects.none())
    cantidad = serializers.DecimalField(max_digits=20, decimal_places=8)
    valor_pen = serializers.DecimalField(max_digits=20, decimal_places=8)
    cpp_inicial = serializers.DecimalField(
        max_digits=20, decimal_places=8, read_only=True,
    )
    periodo_descripcion = serializers.SerializerMethodField()
    almacen_codigo = serializers.CharField(source='almacen.codigo', read_only=True)
    almacen_nombre = serializers.CharField(source='almacen.nombre', read_only=True)
    producto_codigo = serializers.CharField(source='producto.codigo_interno', read_only=True)
    producto_descripcion = serializers.CharField(source='producto.descripcion', read_only=True)
    unidad_base_codigo = serializers.SerializerMethodField()

    class Meta:
        model = SaldoInicial
        fields = (
            'id', 'empresa', 'periodo', 'periodo_descripcion', 'almacen',
            'almacen_codigo', 'almacen_nombre', 'producto', 'producto_codigo',
            'producto_descripcion', 'unidad_base_codigo', 'cantidad',
            'valor_pen', 'cpp_inicial', 'estado', 'creado_por',
        )
        read_only_fields = ('id', 'empresa', 'cpp_inicial', 'estado', 'creado_por')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empresa_id = self.context.get('empresa_id')
        if empresa_id is not None:
            self.fields['periodo'].queryset = Periodo.objects.filter(empresa_id=empresa_id)
            self.fields['almacen'].queryset = Almacen.objects.filter(empresa_id=empresa_id)
            self.fields['producto'].queryset = Producto.objects.filter(empresa_id=empresa_id)

    def get_periodo_descripcion(self, obj):
        return f'{obj.periodo.anio}-{obj.periodo.mes:02d}'

    def get_unidad_base_codigo(self, obj):
        unidad = next((item for item in obj.producto.unidades.all() if item.es_base), None)
        return unidad.unidad_codigo_id if unidad else None

    def validate(self, attrs):
        empresa_id = _empresa_id(self)
        if self.instance is not None and self.instance.estado == 'CONFIRMADO':
            raise serializers.ValidationError(
                'Un saldo inicial CONFIRMADO no puede modificarse.'
            )
        estado_solicitado = self.initial_data.get('estado')
        if estado_solicitado not in (None, 'BORRADOR'):
            raise serializers.ValidationError({
                'estado': 'En este bloque solo se permite el estado BORRADOR.'
            })

        periodo = attrs.get('periodo', getattr(self.instance, 'periodo', None))
        almacen = attrs.get('almacen', getattr(self.instance, 'almacen', None))
        producto = attrs.get('producto', getattr(self.instance, 'producto', None))
        cantidad = attrs.get('cantidad', getattr(self.instance, 'cantidad', None))

        if periodo and periodo.estado != 'ABIERTO':
            raise serializers.ValidationError({'periodo': 'El período debe estar ABIERTO.'})
        if cantidad is not None and cantidad < DECIMAL_CERO:
            raise serializers.ValidationError({'cantidad': 'La cantidad debe ser mayor o igual a cero.'})

        duplicado = SaldoInicial.objects.filter(
            empresa_id=empresa_id,
            periodo=periodo,
            almacen=almacen,
            producto=producto,
        )
        if self.instance is not None:
            duplicado = duplicado.exclude(pk=self.instance.pk)
        if duplicado.exists():
            raise serializers.ValidationError(
                'Ya existe un saldo inicial para este período, almacén y producto.'
            )
        return attrs

    @staticmethod
    def calcular_cpp(cantidad, valor_pen):
        if cantidad == DECIMAL_CERO:
            return DECIMAL_CERO
        return (valor_pen / cantidad).quantize(DECIMAL_OPERATIVO, rounding=ROUND_HALF_UP)

    def create(self, validated_data):
        validated_data['estado'] = 'BORRADOR'
        validated_data['cpp_inicial'] = self.calcular_cpp(
            validated_data['cantidad'], validated_data['valor_pen'],
        )
        return super().create(validated_data)

    def update(self, instance, validated_data):
        cantidad = validated_data.get('cantidad', instance.cantidad)
        valor_pen = validated_data.get('valor_pen', instance.valor_pen)
        validated_data['cpp_inicial'] = self.calcular_cpp(cantidad, valor_pen)
        validated_data['estado'] = 'BORRADOR'
        return super().update(instance, validated_data)


class NotaInternaDetalleSerializer(serializers.ModelSerializer):
    producto = serializers.PrimaryKeyRelatedField(queryset=Producto.objects.none())
    cantidad_base = serializers.DecimalField(max_digits=20, decimal_places=8)
    costo_unitario_pen = serializers.DecimalField(
        max_digits=20, decimal_places=8, allow_null=True, required=False,
    )
    valor_ajuste_pen = serializers.DecimalField(
        max_digits=20, decimal_places=8, allow_null=True, required=False,
    )
    producto_codigo = serializers.CharField(source='producto.codigo_interno', read_only=True)
    producto_descripcion = serializers.CharField(source='producto.descripcion', read_only=True)
    unidad_base_codigo = serializers.SerializerMethodField()

    class Meta:
        model = NotaInternaDetalle
        fields = (
            'id', 'producto', 'producto_codigo', 'producto_descripcion',
            'unidad_base_codigo', 'cantidad_base', 'costo_unitario_pen',
            'valor_ajuste_pen',
        )
        read_only_fields = ('id',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empresa_id = self.context.get('empresa_id')
        if empresa_id is not None:
            self.fields['producto'].queryset = Producto.objects.filter(empresa_id=empresa_id)

    def get_unidad_base_codigo(self, obj):
        unidad = next((item for item in obj.producto.unidades.all() if item.es_base), None)
        return unidad.unidad_codigo_id if unidad else None

    def validate_cantidad_base(self, value):
        if value < DECIMAL_CERO:
            raise serializers.ValidationError('La cantidad base debe ser mayor o igual a cero.')
        return value


class NotaInternaSerializer(serializers.ModelSerializer):
    almacen = serializers.PrimaryKeyRelatedField(queryset=Almacen.objects.none())
    periodo = serializers.PrimaryKeyRelatedField(queryset=Periodo.objects.none())
    tipo_operacion = serializers.PrimaryKeyRelatedField(queryset=TipoOperacion.objects.none())
    detalles = NotaInternaDetalleSerializer(many=True, required=False)
    periodo_descripcion = serializers.SerializerMethodField()
    almacen_codigo = serializers.CharField(source='almacen.codigo', read_only=True)
    almacen_nombre = serializers.CharField(source='almacen.nombre', read_only=True)
    tipo_operacion_codigo = serializers.CharField(
        source='tipo_operacion.codigo_interno', read_only=True,
    )
    tipo_operacion_descripcion = serializers.CharField(
        source='tipo_operacion.descripcion', read_only=True,
    )
    numero_lineas = serializers.IntegerField(source='detalles.count', read_only=True)

    class Meta:
        model = NotaInterna
        fields = (
            'id', 'empresa', 'almacen', 'almacen_codigo', 'almacen_nombre',
            'periodo', 'periodo_descripcion', 'tipo_operacion',
            'tipo_operacion_codigo', 'tipo_operacion_descripcion', 'fecha',
            'motivo', 'responsable', 'observacion', 'archivo_sustento',
            'estado', 'creado_por', 'numero_lineas', 'detalles',
        )
        read_only_fields = ('id', 'empresa', 'estado', 'creado_por', 'numero_lineas')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empresa_id = self.context.get('empresa_id')
        if empresa_id is not None:
            self.fields['almacen'].queryset = Almacen.objects.filter(empresa_id=empresa_id)
            self.fields['periodo'].queryset = Periodo.objects.filter(empresa_id=empresa_id)
            self.fields['tipo_operacion'].queryset = TipoOperacion.objects.filter(
                codigo_interno__in=TIPOS_NOTA_PERMITIDOS,
                es_interna=True,
                origen_requerido='NOTA_INTERNA',
                activo=True,
            )
            self.fields['detalles'].child.fields['producto'].queryset = (
                Producto.objects.filter(empresa_id=empresa_id)
            )

    def get_periodo_descripcion(self, obj):
        return f'{obj.periodo.anio}-{obj.periodo.mes:02d}'

    def validate(self, attrs):
        if self.instance is not None and self.instance.estado in ('CONFIRMADO', 'ANULADO'):
            raise serializers.ValidationError(
                f'Una nota {self.instance.estado} no puede modificarse.'
            )
        estado_solicitado = self.initial_data.get('estado')
        if estado_solicitado not in (None, 'BORRADOR'):
            raise serializers.ValidationError({
                'estado': 'Las notas solo se crean o editan en estado BORRADOR.'
            })

        periodo = attrs.get('periodo', getattr(self.instance, 'periodo', None))
        fecha = attrs.get('fecha', getattr(self.instance, 'fecha', None))
        detalles = attrs.get('detalles')
        if self.instance is None and not detalles:
            raise serializers.ValidationError({'detalles': 'Debe registrar al menos una línea.'})
        if detalles is not None and len(detalles) == 0:
            raise serializers.ValidationError({'detalles': 'Debe registrar al menos una línea.'})
        if periodo and periodo.estado != 'ABIERTO':
            raise serializers.ValidationError({'periodo': 'El período debe estar ABIERTO.'})
        if periodo and fecha and not (periodo.fecha_inicio <= fecha <= periodo.fecha_fin):
            raise serializers.ValidationError({
                'fecha': 'La fecha debe estar dentro del rango del período.'
            })
        return attrs

    def requiere_admin(self):
        datos_validados = getattr(self, '_validated_data', {})
        tipo_nuevo = datos_validados.get('tipo_operacion')
        tipo_actual = self.instance.tipo_operacion if self.instance is not None else None
        if tipo_nuevo and tipo_nuevo.codigo_interno in TIPOS_NOTA_ADMIN:
            return True
        if tipo_actual and tipo_actual.codigo_interno in TIPOS_NOTA_ADMIN:
            return True

        detalles_nuevos = datos_validados.get('detalles')
        if detalles_nuevos is not None:
            return any(
                detalle.get('costo_unitario_pen') is not None
                or detalle.get('valor_ajuste_pen') is not None
                for detalle in detalles_nuevos
            )
        if self.instance is not None:
            return self.instance.detalles.filter(
                models.Q(costo_unitario_pen__isnull=False)
                | models.Q(valor_ajuste_pen__isnull=False)
            ).exists()
        return False

    def create(self, validated_data):
        detalles = validated_data.pop('detalles')
        validated_data['estado'] = 'BORRADOR'
        nota = NotaInterna.objects.create(**validated_data)
        NotaInternaDetalle.objects.bulk_create([
            NotaInternaDetalle(nota_interna=nota, **detalle)
            for detalle in detalles
        ])
        return nota

    def update(self, instance, validated_data):
        detalles = validated_data.pop('detalles', None)
        validated_data['estado'] = 'BORRADOR'
        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)
        instance.save()
        if detalles is not None:
            instance.detalles.all().delete()
            NotaInternaDetalle.objects.bulk_create([
                NotaInternaDetalle(nota_interna=instance, **detalle)
                for detalle in detalles
            ])
        return instance


class TransferenciaDetalleSerializer(serializers.ModelSerializer):
    producto = serializers.PrimaryKeyRelatedField(queryset=Producto.objects.none())
    producto_codigo = serializers.CharField(source='producto.codigo_interno', read_only=True)
    producto_descripcion = serializers.CharField(source='producto.descripcion', read_only=True)

    class Meta:
        model = TransferenciaDetalle
        fields = ('id', 'producto', 'producto_codigo', 'producto_descripcion', 'cantidad_base')
        read_only_fields = ('id',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empresa_id = self.context.get('empresa_id')
        if empresa_id is not None:
            self.fields['producto'].queryset = Producto.objects.filter(empresa_id=empresa_id)

    def validate_cantidad_base(self, value):
        if value <= DECIMAL_CERO:
            raise serializers.ValidationError('La cantidad debe ser mayor que cero.')
        return value


class TransferenciaSerializer(serializers.ModelSerializer):
    almacen_origen = serializers.PrimaryKeyRelatedField(queryset=Almacen.objects.none())
    almacen_destino = serializers.PrimaryKeyRelatedField(queryset=Almacen.objects.none())
    detalles = TransferenciaDetalleSerializer(many=True)
    almacen_origen_nombre = serializers.CharField(source='almacen_origen.nombre', read_only=True)
    almacen_destino_nombre = serializers.CharField(source='almacen_destino.nombre', read_only=True)
    numero_lineas = serializers.IntegerField(source='detalles.count', read_only=True)

    class Meta:
        model = Transferencia
        fields = (
            'id', 'empresa', 'almacen_origen', 'almacen_origen_nombre',
            'almacen_destino', 'almacen_destino_nombre', 'fecha', 'estado',
            'creado_por', 'numero_lineas', 'detalles',
        )
        read_only_fields = ('id', 'empresa', 'estado', 'creado_por', 'numero_lineas')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empresa_id = self.context.get('empresa_id')
        if empresa_id is not None:
            almacenes = Almacen.objects.filter(empresa_id=empresa_id)
            self.fields['almacen_origen'].queryset = almacenes
            self.fields['almacen_destino'].queryset = almacenes
            self.fields['detalles'].child.fields['producto'].queryset = Producto.objects.filter(
                empresa_id=empresa_id,
            )

    def validate(self, attrs):
        if self.instance is not None and self.instance.estado != 'BORRADOR':
            raise serializers.ValidationError('Una transferencia confirmada o anulada no puede editarse.')
        origen = attrs.get('almacen_origen', getattr(self.instance, 'almacen_origen', None))
        destino = attrs.get('almacen_destino', getattr(self.instance, 'almacen_destino', None))
        fecha = attrs.get('fecha', getattr(self.instance, 'fecha', None))
        detalles = attrs.get('detalles')
        if origen == destino:
            raise serializers.ValidationError({'almacen_destino': 'Debe ser distinto del almacén origen.'})
        if self.instance is None and not detalles:
            raise serializers.ValidationError({'detalles': 'Debe registrar al menos una línea.'})
        if detalles is not None and not detalles:
            raise serializers.ValidationError({'detalles': 'Debe registrar al menos una línea.'})
        empresa_id = _empresa_id(self)
        if fecha and not Periodo.objects.filter(
            empresa_id=empresa_id, estado='ABIERTO',
            fecha_inicio__lte=fecha, fecha_fin__gte=fecha,
        ).exists():
            raise serializers.ValidationError({'fecha': 'Debe existir un período ABIERTO para la fecha.'})
        return attrs

    def create(self, validated_data):
        detalles = validated_data.pop('detalles')
        transferencia = Transferencia.objects.create(estado='BORRADOR', **validated_data)
        TransferenciaDetalle.objects.bulk_create([
            TransferenciaDetalle(transferencia=transferencia, **detalle) for detalle in detalles
        ])
        return transferencia

    def update(self, instance, validated_data):
        detalles = validated_data.pop('detalles', None)
        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)
        instance.save()
        if detalles is not None:
            instance.detalles.all().delete()
            TransferenciaDetalle.objects.bulk_create([
                TransferenciaDetalle(transferencia=instance, **detalle) for detalle in detalles
            ])
        return instance


class ProductoEquivalenciaSerializer(serializers.ModelSerializer):
    tercero_info = serializers.SerializerMethodField(read_only=True)
    producto_info = serializers.SerializerMethodField(read_only=True)
    unidad_externa_nombre = serializers.CharField(source='unidad_externa_codigo.descripcion', read_only=True)
    confirmado_por_username = serializers.CharField(source='confirmado_por.username', read_only=True)
    # QA2-001: al homologar desde una captura, el proveedor es el emisor del comprobante. Si aún
    # no existe (la captura se subió pero no se generó el borrador), se registra al guardar.
    captura = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = ProductoEquivalencia
        fields = (
            'id', 'empresa', 'tercero', 'tercero_info',
            'codigo_externo', 'descripcion_externa',
            'unidad_externa_codigo', 'unidad_externa_nombre',
            'producto_unidad', 'producto_info',
            'factor_conversion', 'confirmado_por', 'confirmado_por_username',
            'confirmado_en', 'activa', 'captura',
        )
        read_only_fields = ('id', 'empresa', 'confirmado_por', 'confirmado_en')
        extra_kwargs = {'tercero': {'required': False, 'allow_null': True}}

    def _proveedor_de_captura(self, captura_id, *, crear):
        from apps.documentos.models import DocumentoCaptura
        from apps.inventario.homologacion import proveedor_de_captura
        captura = DocumentoCaptura.objects.filter(pk=captura_id, empresa_id=self.context.get('empresa_id')).first()
        if captura is None:
            raise serializers.ValidationError({'captura': 'Captura no encontrada para esta empresa.'})
        try:
            return captura, proveedor_de_captura(captura, crear=crear)
        except Exception as exc:  # comprobante que no es de la empresa, sin RUC, etc.
            detalle = getattr(exc, 'detail', None) or getattr(exc, 'message_dict', None) or str(exc)
            raise serializers.ValidationError({'captura': detalle})

    def create(self, validated_data):
        captura_id = validated_data.pop('captura', None)
        if validated_data.get('tercero') is None and captura_id:
            _, validated_data['tercero'] = self._proveedor_de_captura(captura_id, crear=True)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('captura', None)
        return super().update(instance, validated_data)

    def get_tercero_info(self, obj):
        if obj.tercero:
            return {
                'id': obj.tercero.id,
                'numero_documento': obj.tercero.numero_documento,
                'razon_social': obj.tercero.razon_social,
            }
        return None

    def get_producto_info(self, obj):
        if obj.producto_unidad:
            pu = obj.producto_unidad
            prod = pu.producto
            return {
                'producto_id': prod.id,
                'producto_codigo': prod.codigo_interno,
                'producto_descripcion': prod.descripcion,
                'unidad_codigo': pu.unidad_codigo_id,
                'factor_a_base': str(pu.factor_a_base),
                'es_base': pu.es_base,
            }
        return None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empresa_id = self.context.get('empresa_id')
        if empresa_id:
            self.fields['tercero'].queryset = Tercero.objects.filter(empresa_id=empresa_id)
            self.fields['producto_unidad'].queryset = ProductoUnidad.objects.filter(
                producto__empresa_id=empresa_id
            ).select_related('producto', 'unidad_codigo')

    def validate_factor_conversion(self, value):
        if value is None or value <= Decimal('0'):
            raise serializers.ValidationError('El factor de conversión debe ser mayor a 0.')
        return value.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP)

    def validate_codigo_externo(self, valor):
        # QA-002: sin espacios repetidos ni el marcador '—' que mostraba la pantalla sin código.
        return limpiar_texto(valor)

    def validate_descripcion_externa(self, valor):
        return limpiar_texto(valor)

    def validate(self, attrs):
        """
        Bloque 14 / QA-002: una sola equivalencia ACTIVA por proveedor, código externo (o
        descripción si no hay código) y unidad, comparados como los compara la captura
        (sin distinguir mayúsculas ni espacios). Con dos activas la captura tomaba cualquiera.
        """
        attrs = super().validate(attrs)
        actual = self.instance
        captura_id = attrs.get('captura')
        if actual is None and captura_id:
            captura, proveedor = self._proveedor_de_captura(captura_id, crear=False)
            from apps.inventario.homologacion import solo_digitos, valores_captura
            ruc = solo_digitos(valores_captura(captura)[0].get('ruc_emisor'))
            elegido = attrs.get('tercero')
            if elegido is not None and solo_digitos(elegido.numero_documento) != ruc:
                raise serializers.ValidationError({'tercero': (
                    f'El proveedor elegido ({elegido.numero_documento}) no es el emisor del comprobante (RUC {ruc}): '
                    'la equivalencia no se aplicaría a sus XML.'
                )})
            if elegido is None and proveedor is not None:
                attrs['tercero'] = proveedor
        elif actual is None and attrs.get('tercero') is None:
            raise serializers.ValidationError({'tercero': 'Seleccione el proveedor.'})
        activa = attrs.get('activa', actual.activa if actual else True)
        if not activa:
            return attrs
        empresa_id = self.context.get('empresa_id') or (actual.empresa_id if actual else None)
        tercero = attrs.get('tercero', actual.tercero if actual else None)
        codigo = attrs.get('codigo_externo', actual.codigo_externo if actual else None) or ''
        descripcion = attrs.get('descripcion_externa', actual.descripcion_externa if actual else None) or ''
        unidad = attrs.get('unidad_externa_codigo', actual.unidad_externa_codigo if actual else None)
        if not empresa_id or not tercero or not (normalizar_texto(codigo) or normalizar_texto(descripcion)):
            return attrs
        otra = equivalencia_activa_repetida(
            empresa_id=empresa_id, tercero=tercero, codigo=codigo, descripcion=descripcion,
            unidad=getattr(unidad, 'codigo', unidad) or '', excluir_id=actual.pk if actual else None,
        )
        if otra is not None:
            campo, clave = (('codigo_externo', f"el código '{normalizar_texto(codigo)}'") if normalizar_texto(codigo)
                            else ('descripcion_externa', f"la descripción '{normalizar_texto(descripcion)}'"))
            destino = otra.producto_unidad.producto.codigo_interno if otra.producto_unidad_id else '—'
            raise serializers.ValidationError({campo: (
                f'Ya existe una equivalencia activa para este proveedor y {clave} (→ {destino}). '
                'Edítela o desactívela antes de registrar otra.'
            )})
        return attrs
