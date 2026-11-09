from decimal import Decimal
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from apps.documentos.afectacion_igv import AFECTACIONES
from apps.documentos.models import (
    CapturaCampo, Documento, DocumentoCaptura, DocumentoCuota, DocumentoDetalle, PagoDocumento, SerieComprobante,
)
from apps.documentos.services import crear_documento


class DocumentoDetalleSerializer(serializers.ModelSerializer):
    producto_codigo = serializers.ReadOnlyField(source='producto.codigo_interno')
    producto_descripcion = serializers.ReadOnlyField(source='producto.descripcion')
    unidad_codigo = serializers.ReadOnlyField(source='producto_unidad.unidad_codigo_id')
    almacen_codigo = serializers.ReadOnlyField(source='almacen.codigo')
    almacen_nombre = serializers.ReadOnlyField(source='almacen.nombre')
    tipo_operacion_codigo = serializers.ReadOnlyField(source='tipo_operacion.codigo_interno')
    tipo_operacion_descripcion = serializers.ReadOnlyField(source='tipo_operacion.descripcion')
    tipo_operacion_naturaleza = serializers.ReadOnlyField(source='tipo_operacion.naturaleza')
    # QA-001: para elegir la línea de origen de una NC/ND de devolución: cuánto se devolvió ya
    # (notas confirmadas con movimiento físico) y cuánto queda, en cantidad base.
    cantidad_devuelta = serializers.SerializerMethodField()
    cantidad_disponible_devolucion = serializers.SerializerMethodField()

    def _devuelta(self, obj):
        if not hasattr(obj, '_cantidad_devuelta_cache'):
            from apps.documentos.reglas import cantidad_ya_devuelta
            obj._cantidad_devuelta_cache = cantidad_ya_devuelta(obj.id)
        return obj._cantidad_devuelta_cache

    def get_cantidad_devuelta(self, obj):
        return f'{self._devuelta(obj):.8f}'

    def get_cantidad_disponible_devolucion(self, obj):
        disponible = (obj.cantidad_base or Decimal('0')) - self._devuelta(obj)
        return f'{max(disponible, Decimal("0")):.8f}'

    class Meta:
        model = DocumentoDetalle
        fields = [
            'id',
            'linea',
            'producto',
            'producto_codigo',
            'producto_descripcion',
            'producto_unidad',
            'unidad_codigo',
            'almacen',
            'almacen_codigo',
            'almacen_nombre',
            'tipo_operacion',
            'tipo_operacion_codigo',
            'tipo_operacion_descripcion',
            'afecta_kardex_aplicado',
            'equivalencia',
            'descripcion_original',
            'cantidad_original',
            'factor_conversion',
            'cantidad_base',
            'precio_unitario',
            'igv',
            'afectacion_igv',
            'codigo_afectacion_igv',
            'porcentaje_credito_fiscal_aplicado',
            'costo_unitario_pen',
            'es_bonificacion',
            'detalle_origen',
            'tipo_operacion_naturaleza',
            'cantidad_devuelta',
            'cantidad_disponible_devolucion',
        ]
        read_only_fields = [
            'id',
            'afecta_kardex_aplicado',
            'factor_conversion',
            'cantidad_base',
            'porcentaje_credito_fiscal_aplicado',
            'costo_unitario_pen',
        ]


class DocumentoListSerializer(serializers.ModelSerializer):
    tipo_comprobante_codigo = serializers.ReadOnlyField(source='tipo_comprobante.codigo_sunat')
    tipo_comprobante_descripcion = serializers.ReadOnlyField(source='tipo_comprobante.descripcion')
    es_nota = serializers.ReadOnlyField(source='tipo_comprobante.es_nota')
    tercero_razon_social = serializers.ReadOnlyField(source='tercero.razon_social')
    # QA-004: documento del tercero (proveedor en compras, cliente en ventas). `ruc_emisor` es
    # el emisor del comprobante: en una venta es la propia empresa, no el cliente.
    tercero_tipo_documento = serializers.ReadOnlyField(source='tercero.tipo_documento')
    tercero_numero_documento = serializers.ReadOnlyField(source='tercero.numero_documento')
    periodo_orden = serializers.ReadOnlyField(source='periodo.orden')
    revisado_por_username = serializers.ReadOnlyField(source='revisado_por.username')
    detalles_count = serializers.SerializerMethodField()
    emision_electronica_resumen = serializers.SerializerMethodField()

    def get_detalles_count(self, obj):
        # Bloque 6: usa la anotación del listado (sin N+1); fallback para otros usos.
        anotado = getattr(obj, 'num_detalles', None)
        return anotado if anotado is not None else obj.detalles.count()

    def get_emision_electronica_resumen(self, obj):
        try:
            emision = getattr(obj, 'emision_electronica', None)
        except (ObjectDoesNotExist, AttributeError):
            return None
        if not emision:
            return None
        return {'estado': emision.estado, 'ambiente': emision.ambiente,
                'codigo_sunat': emision.codigo_respuesta, 'pdf_disponible': bool(getattr(emision, 'hash_pdf', None))}

    class Meta:
        model = Documento
        fields = [
            'id',
            'empresa_id',
            'clase',
            'periodo',
            'periodo_orden',
            'tercero',
            'tercero_razon_social',
            'tercero_tipo_documento',
            'tercero_numero_documento',
            'ruc_emisor',
            'tipo_comprobante',
            'tipo_comprobante_codigo',
            'tipo_comprobante_descripcion',
            'es_nota',
            'serie',
            'serie_normalizada',
            'numero',
            'numero_normalizado',
            'fecha_emision',
            'moneda_codigo',
            'tipo_cambio',
            'fecha_tc',
            'monto_tc',
            'fuente_tc',
            'subtotal',
            'igv',
            'total',
            'documento_origen',
            'origen_captura',
            'estado',
            'estado_revision',
            'revisado_por_username',
            'revisado_en',
            'confirmado_en',
            'detalles_count',
            'condicion_pago',
            'fecha_vencimiento',
            'serie_comprobante',
            'emision_electronica_resumen',
        ]


class DocumentoDetailSerializer(serializers.ModelSerializer):
    detalles = DocumentoDetalleSerializer(many=True, read_only=True)
    tipo_comprobante_codigo = serializers.ReadOnlyField(source='tipo_comprobante.codigo_sunat')
    tipo_comprobante_descripcion = serializers.ReadOnlyField(source='tipo_comprobante.descripcion')
    es_nota = serializers.ReadOnlyField(source='tipo_comprobante.es_nota')
    tercero_razon_social = serializers.ReadOnlyField(source='tercero.razon_social')
    # QA-004: documento del tercero (proveedor en compras, cliente en ventas). `ruc_emisor` es
    # el emisor del comprobante: en una venta es la propia empresa, no el cliente.
    tercero_tipo_documento = serializers.ReadOnlyField(source='tercero.tipo_documento')
    tercero_numero_documento = serializers.ReadOnlyField(source='tercero.numero_documento')
    periodo_orden = serializers.ReadOnlyField(source='periodo.orden')
    revisado_por_username = serializers.ReadOnlyField(source='revisado_por.username')
    confirmado_por_username = serializers.ReadOnlyField(source='confirmado_por.username')
    creado_por_username = serializers.ReadOnlyField(source='creado_por.username')
    documento_origen_comprobante = serializers.SerializerMethodField()
    # Bloque 16: condición de pago, cuotas, pagos y saldo calculado.
    cuotas = serializers.SerializerMethodField()
    pagos = serializers.SerializerMethodField()
    finanzas = serializers.SerializerMethodField()
    # Bloque 17A: motivo tributario de la nota (catálogo 09/10).
    motivo_nota_codigo = serializers.ReadOnlyField(source='motivo_nota.codigo')
    motivo_nota_descripcion = serializers.ReadOnlyField(source='motivo_nota.descripcion')

    def get_cuotas(self, obj):
        return DocumentoCuotaSerializer(obj.cuotas.all(), many=True).data

    def get_pagos(self, obj):
        return PagoDocumentoSerializer(obj.pagos.select_related('metodo_pago', 'registrado_por', 'anulado_por'), many=True).data

    def get_finanzas(self, obj):
        from apps.documentos.finanzas import resumen_financiero, texto
        datos = resumen_financiero(obj)
        return {k: (texto(v) if isinstance(v, Decimal) else v) for k, v in datos.items()} if datos else None

    class Meta:
        model = Documento
        fields = [
            'id',
            'empresa_id',
            'clase',
            'periodo',
            'periodo_orden',
            'tercero',
            'tercero_razon_social',
            'tercero_tipo_documento',
            'tercero_numero_documento',
            'ruc_emisor',
            'tipo_comprobante',
            'tipo_comprobante_codigo',
            'tipo_comprobante_descripcion',
            'es_nota',
            'serie',
            'serie_normalizada',
            'numero',
            'numero_normalizado',
            'fecha_emision',
            'moneda_codigo',
            'tipo_cambio',
            'fecha_tc',
            'monto_tc',
            'fuente_tc',
            'subtotal',
            'igv',
            'total',
            'documento_origen',
            'documento_origen_comprobante',
            'motivo_nota_codigo',
            'motivo_nota_descripcion',
            'origen_captura',
            'estado',
            'estado_revision',
            'revisado_por',
            'revisado_por_username',
            'revisado_en',
            'creado_por',
            'creado_por_username',
            'confirmado_por',
            'confirmado_por_username',
            'confirmado_en',
            'detalles',
            'condicion_pago',
            'fecha_vencimiento',
            'serie_comprobante',
            'cuotas',
            'pagos',
            'finanzas',
        ]

    def get_documento_origen_comprobante(self, obj):
        if obj.documento_origen:
            return f"{obj.documento_origen.serie_normalizada}-{obj.documento_origen.numero_normalizado}"
        return None


class DocumentoDetalleEntradaSerializer(serializers.Serializer):
    """
    CON-009: línea de detalle tipada. DecimalField de DRF rechaza texto, NaN e
    Infinity con 400. Las reglas que dependen de la naturaleza de la operación o
    de la tasa de IGV se validan en el servicio (crear_documento).
    """
    linea = serializers.IntegerField(required=False, min_value=1)
    producto = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    producto_unidad = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    almacen = serializers.IntegerField(min_value=1)
    tipo_operacion = serializers.IntegerField(min_value=1)
    equivalencia = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    detalle_origen = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    descripcion_original = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=500)
    cantidad_original = serializers.DecimalField(max_digits=20, decimal_places=8, min_value=Decimal('0'))
    factor_conversion = serializers.DecimalField(
        max_digits=20, decimal_places=8, required=False, allow_null=True, min_value=Decimal('0.00000001'),
    )
    precio_unitario = serializers.DecimalField(
        max_digits=20, decimal_places=8, required=False, default=Decimal('0'), min_value=Decimal('0'),
    )
    igv = serializers.DecimalField(
        max_digits=20, decimal_places=8, required=False, default=Decimal('0'), min_value=Decimal('0'),
    )
    es_bonificacion = serializers.BooleanField(required=False, default=False)
    # Bloque 3: afectación del IGV. Si se omite: GRATUITO para bonificaciones, GRAVADO en otro caso.
    afectacion_igv = serializers.ChoiceField(choices=AFECTACIONES, required=False, allow_null=True)
    codigo_afectacion_igv = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=2)


class CuotaEntradaSerializer(serializers.Serializer):
    fecha_vencimiento = serializers.DateField()
    monto = serializers.DecimalField(max_digits=20, decimal_places=8, min_value=Decimal('0.00000001'))


class DocumentoCreateSerializer(serializers.ModelSerializer):
    ruc_emisor = serializers.CharField(max_length=11, required=False, allow_blank=True, allow_null=True)
    # Bloque 16: con `serie_comprobante` (ventas) el número lo asigna el backend; si no, la serie
    # y el número del comprobante son obligatorios (compras y ventas sin serie configurada).
    serie = serializers.CharField(max_length=30, required=False, allow_blank=True)
    numero = serializers.CharField(max_length=50, required=False, allow_blank=True)
    serie_comprobante = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    condicion_pago = serializers.ChoiceField(choices=['CONTADO', 'CREDITO'], required=False, default='CONTADO')
    fecha_vencimiento = serializers.DateField(required=False, allow_null=True)
    cuotas = CuotaEntradaSerializer(many=True, required=False, default=list)
    # Bloque 17A: código del motivo tributario (catálogo 09 en NC, 10 en ND).
    motivo_nota = serializers.CharField(max_length=2, required=False, allow_blank=True, allow_null=True)
    detalles = DocumentoDetalleEntradaSerializer(many=True, write_only=True, allow_empty=False)

    class Meta:
        model = Documento
        fields = [
            'id',
            'clase',
            'periodo',
            'tercero',
            'ruc_emisor',
            'tipo_comprobante',
            'serie',
            'numero',
            'fecha_emision',
            'moneda_codigo',
            'documento_origen',
            'origen_captura',
            'serie_comprobante',
            'condicion_pago',
            'fecha_vencimiento',
            'cuotas',
            'motivo_nota',
            'detalles',
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        if not attrs.get('serie_comprobante'):
            faltan = {c: 'Este campo es requerido.' for c in ('serie', 'numero') if not (attrs.get(c) or '').strip()}
            if faltan:
                raise serializers.ValidationError(faltan)
        attrs['cuotas'] = [dict(c) for c in attrs.get('cuotas') or []]
        periodo = attrs.get('periodo')
        fecha_emision = attrs.get('fecha_emision')
        if periodo and fecha_emision:
            if not (periodo.fecha_inicio <= fecha_emision <= periodo.fecha_fin):
                raise serializers.ValidationError({
                    'fecha_emision': (
                        f"La fecha de emisión ({fecha_emision}) no corresponde al rango del período "
                        f"contable seleccionado ({periodo.fecha_inicio} al {periodo.fecha_fin})."
                    )
                })
        return attrs

    def create(self, validated_data):
        detalles_data = [dict(linea) for linea in validated_data.pop('detalles', [])]
        empresa_id = self.context['request'].empresa_id
        usuario_id = self.context['request'].user.id

        return crear_documento(
            empresa_id=empresa_id,
            usuario_id=usuario_id,
            datos_cabecera=validated_data,
            detalles_datos=detalles_data
        )


class DocumentoRevisarSerializer(serializers.Serializer):
    estado_revision = serializers.ChoiceField(
        choices=['EN_REVISION', 'REVISADO', 'OBSERVADO'],
        required=True
    )
    motivo = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default=""
    )


class DocumentoAnularSerializer(serializers.Serializer):
    motivo = serializers.CharField(
        max_length=500,
        required=True
    )


class CapturaCampoSerializer(serializers.ModelSerializer):
    corregido_por_username = serializers.ReadOnlyField(source='corregido_por.username')

    class Meta:
        model = CapturaCampo
        fields = [
            'id',
            'seccion',
            'numero_linea',
            'nombre_campo',
            'valor_extraido',
            'confianza',
            'valor_corregido',
            'corregido_por',
            'corregido_por_username',
        ]
        read_only_fields = ['id', 'seccion', 'numero_linea', 'nombre_campo', 'valor_extraido', 'confianza', 'corregido_por']


class DocumentoCapturaListSerializer(serializers.ModelSerializer):
    subido_por_username = serializers.ReadOnlyField(source='subido_por.username')
    total_campos = serializers.SerializerMethodField()

    class Meta:
        model = DocumentoCaptura
        fields = [
            'id',
            'tipo',
            'ruta_archivo',
            'hash_sha256',
            'estado_proceso',
            'documento_id',
            'subido_por',
            'subido_por_username',
            'creado_en',
            'total_campos',
        ]
        read_only_fields = fields

    def get_total_campos(self, obj):
        return obj.campos.count()


class DocumentoCapturaDetailSerializer(serializers.ModelSerializer):
    subido_por_username = serializers.ReadOnlyField(source='subido_por.username')
    campos = CapturaCampoSerializer(many=True, read_only=True)
    documento_serie_numero = serializers.SerializerMethodField()
    # QA2-001: estado de homologación de cada línea con la misma regla que el borrador
    # (apps.inventario.homologacion), en cuanto el XML se sube: proveedor, equivalencia aplicada
    # y líneas pendientes.
    homologacion = serializers.SerializerMethodField()

    class Meta:
        model = DocumentoCaptura
        fields = [
            'id',
            'tipo',
            'ruta_archivo',
            'hash_sha256',
            'estado_proceso',
            'documento_id',
            'documento_serie_numero',
            'subido_por',
            'subido_por_username',
            'creado_en',
            'campos',
            'homologacion',
        ]
        read_only_fields = fields

    def get_homologacion(self, obj):
        from apps.inventario.homologacion import homologacion_de_captura
        return homologacion_de_captura(obj)

    def get_documento_serie_numero(self, obj):
        if obj.documento:
            return f"{obj.documento.serie_normalizada}-{obj.documento.numero_normalizado}"
        return None


class DocumentoCapturaSubirSerializer(serializers.Serializer):
    archivo = serializers.FileField(required=True)
    tipo = serializers.ChoiceField(choices=['XML', 'PDF', 'IMAGEN', 'ESCANER'], required=True)
    texto_ocr = serializers.CharField(required=False, allow_blank=True, default='', max_length=200_000)

    def validate(self, attrs):
        # Bloque 6: tamaño, extensión/MIME, firma del contenido y nombre seguro.
        from apps.documentos.uploads import validar_archivo_captura
        attrs['nombre_seguro'] = validar_archivo_captura(attrs['archivo'], attrs['tipo'])
        return attrs


class CapturaCampoCorregirSerializer(serializers.Serializer):
    campo_id = serializers.IntegerField(required=True)
    valor_corregido = serializers.CharField(required=False, allow_blank=True, default='')


class GenerarBorradorSerializer(serializers.Serializer):
    almacen_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class DocumentoCuotaSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoCuota
        fields = ['id', 'numero', 'fecha_vencimiento', 'monto']


class PagoDocumentoSerializer(serializers.ModelSerializer):
    metodo_pago_descripcion = serializers.ReadOnlyField(source='metodo_pago.descripcion')
    registrado_por_username = serializers.ReadOnlyField(source='registrado_por.username')
    anulado_por_username = serializers.ReadOnlyField(source='anulado_por.username')

    class Meta:
        model = PagoDocumento
        fields = ['id', 'documento', 'fecha', 'monto', 'moneda_codigo', 'metodo_pago', 'metodo_pago_descripcion',
                  'referencia', 'estado', 'motivo_anulacion', 'registrado_por_username', 'registrado_en',
                  'anulado_por_username', 'anulado_en']
        read_only_fields = fields


class PagoEntradaSerializer(serializers.Serializer):
    documento = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField()
    monto = serializers.DecimalField(max_digits=20, decimal_places=8, min_value=Decimal('0.00000001'))
    metodo_pago = serializers.CharField(max_length=20)
    referencia = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    moneda_codigo = serializers.CharField(max_length=3, required=False, allow_blank=True, default='')


class MotivoSerializer(serializers.Serializer):
    motivo = serializers.CharField(max_length=500)


class CondicionPagoSerializer(serializers.Serializer):
    condicion_pago = serializers.ChoiceField(choices=['CONTADO', 'CREDITO'])
    fecha_vencimiento = serializers.DateField(required=False, allow_null=True)
    cuotas = CuotaEntradaSerializer(many=True, required=False, default=list)
    motivo = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')


class SerieComprobanteSerializer(serializers.ModelSerializer):
    establecimiento_codigo = serializers.ReadOnlyField(source='establecimiento.codigo_sunat')
    establecimiento_nombre = serializers.ReadOnlyField(source='establecimiento.nombre')
    tipo_comprobante_codigo = serializers.ReadOnlyField(source='tipo_comprobante.codigo_sunat')
    tipo_comprobante_descripcion = serializers.ReadOnlyField(source='tipo_comprobante.descripcion')
    siguiente_numero = serializers.SerializerMethodField()
    en_uso = serializers.SerializerMethodField()

    class Meta:
        model = SerieComprobante
        fields = ['id', 'establecimiento', 'establecimiento_codigo', 'establecimiento_nombre', 'tipo_comprobante',
                  'tipo_comprobante_codigo', 'tipo_comprobante_descripcion', 'serie', 'ultimo_correlativo',
                  'siguiente_numero', 'activo', 'en_uso', 'creado_en', 'actualizado_en']
        read_only_fields = ['id', 'creado_en', 'actualizado_en']

    def get_siguiente_numero(self, obj):
        from apps.documentos.finanzas import formato_correlativo
        return formato_correlativo(obj.ultimo_correlativo + 1)

    def get_en_uso(self, obj):
        return obj.documentos.exists()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empresa_id = self.context.get('empresa_id')
        from apps.empresas.models import Establecimiento
        self.fields['establecimiento'].queryset = Establecimiento.objects.filter(empresa_id=empresa_id)

    def validate(self, attrs):
        from apps.documentos.finanzas import MAX_CORRELATIVO, validar_formato_serie
        actual = self.instance
        tipo = attrs.get('tipo_comprobante', actual.tipo_comprobante if actual else None)
        if actual is not None and actual.documentos.exists():
            # Una serie con comprobantes no cambia de identidad ni retrocede su correlativo.
            for campo in ('serie', 'tipo_comprobante', 'establecimiento', 'ultimo_correlativo'):
                if campo in attrs and attrs[campo] != getattr(actual, campo):
                    raise serializers.ValidationError({campo: 'La serie ya tiene comprobantes: solo puede activarse o desactivarse.'})
        if 'serie' in attrs or actual is None:
            attrs['serie'] = validar_formato_serie(attrs.get('serie', actual.serie if actual else ''), tipo)
        correlativo = attrs.get('ultimo_correlativo', actual.ultimo_correlativo if actual else 0)
        if correlativo < 0 or correlativo > MAX_CORRELATIVO:
            raise serializers.ValidationError({'ultimo_correlativo': f'Debe estar entre 0 y {MAX_CORRELATIVO}.'})
        empresa_id = self.context.get('empresa_id')
        duplicada = SerieComprobante.objects.filter(empresa_id=empresa_id, tipo_comprobante=tipo, serie=attrs['serie'] if 'serie' in attrs else actual.serie)
        if actual is not None:
            duplicada = duplicada.exclude(pk=actual.pk)
        if duplicada.exists():
            raise serializers.ValidationError({'serie': 'Ya existe esa serie para ese tipo de comprobante en la empresa.'})
        return attrs
