from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.documentos.afectacion_igv import AFECTACIONES


class Documento(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='documentos'
    )
    clase = models.CharField(max_length=20)
    periodo = models.ForeignKey(
        'empresas.Periodo',
        on_delete=models.PROTECT,
        db_column='periodo_id',
        related_name='documentos'
    )
    tercero = models.ForeignKey(
        'inventario.Tercero',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='tercero_id',
        related_name='documentos'
    )
    ruc_emisor = models.CharField(max_length=11)
    tipo_comprobante = models.ForeignKey(
        'catalogos.TipoComprobante',
        on_delete=models.PROTECT,
        db_column='tipo_comprobante_id',
        related_name='documentos'
    )

    serie = models.CharField(max_length=30, null=True, blank=True)
    serie_normalizada = models.CharField(max_length=30)
    numero = models.CharField(max_length=50, null=True, blank=True)
    numero_normalizado = models.CharField(max_length=50)

    fecha_emision = models.DateField()

    moneda_codigo = models.ForeignKey(
        'catalogos.Moneda',
        on_delete=models.PROTECT,
        db_column='moneda_codigo',
        related_name='documentos'
    )
    tipo_cambio = models.ForeignKey(
        'catalogos.TipoCambio',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='tipo_cambio_id',
        related_name='documentos'
    )
    fecha_tc = models.DateField(null=True, blank=True)
    monto_tc = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    fuente_tc = models.CharField(max_length=50, null=True, blank=True)

    subtotal = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    igv = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    total = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    documento_origen = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='documento_origen_id',
        related_name='documentos_derivados'
    )

    # Bloque 16: condición de pago y serie con correlativo automático (solo ventas).
    condicion_pago = models.CharField(max_length=10, default='CONTADO', db_default='CONTADO')
    fecha_vencimiento = models.DateField(null=True, blank=True)
    serie_comprobante = models.ForeignKey(
        'documentos.SerieComprobante',
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column='serie_comprobante_id',
        related_name='documentos'
    )
    # Bloque 17A: motivo tributario de la nota (catálogo 09 en NC, 10 en ND). Solo en notas.
    motivo_nota = models.ForeignKey(
        'catalogos.MotivoNota',
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        db_column='motivo_nota_id',
        related_name='documentos'
    )

    origen_captura = models.CharField(max_length=20, default='MANUAL', db_default='MANUAL')
    estado = models.CharField(max_length=20, default='BORRADOR', db_default='BORRADOR')
    estado_revision = models.CharField(max_length=20, default='PENDIENTE', db_default='PENDIENTE')

    revisado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='revisado_por',
        related_name='+'
    )
    revisado_en = models.DateTimeField(null=True, blank=True)
    creado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='creado_por',
        related_name='+'
    )
    confirmado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='confirmado_por',
        related_name='+'
    )
    confirmado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'documento'
        verbose_name = 'Documento Comercial'
        verbose_name_plural = 'Documentos Comerciales'
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'empresa',
                    'ruc_emisor',
                    'tipo_comprobante',
                    'serie_normalizada',
                    'numero_normalizado',
                ],
                name='uq_documento_emisor_comprobante'
            ),
            models.CheckConstraint(
                condition=models.Q(clase__in=['COMPRA', 'VENTA']),
                name='chk_documento_clase'
            ),
            models.CheckConstraint(
                condition=models.Q(origen_captura__in=['MANUAL', 'XML', 'PDF', 'IMAGEN', 'ESCANER']),
                name='chk_documento_origen_captura'
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=['BORRADOR', 'CONFIRMADO', 'ANULADO']),
                name='chk_documento_estado'
            ),
            models.CheckConstraint(
                condition=models.Q(estado_revision__in=['PENDIENTE', 'EN_REVISION', 'REVISADO', 'OBSERVADO']),
                name='chk_documento_estado_revision'
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(condicion_pago='CONTADO', fecha_vencimiento__isnull=True)
                    | models.Q(condicion_pago='CREDITO', fecha_vencimiento__isnull=False)
                ),
                name='chk_documento_condicion_pago'
            ),
        ]
        indexes = [
            models.Index(fields=['empresa', 'fecha_emision'], name='idx_documento_empresa_fecha'),
            models.Index(fields=['periodo'], name='idx_documento_periodo'),
            models.Index(fields=['tercero'], name='idx_documento_tercero'),
            models.Index(fields=['documento_origen'], name='idx_documento_origen'),
            # Bloque 7: listado paginado filtrado por estado (BORRADOR/CONFIRMADO/ANULADO)
            # con el mismo orden de la API (-fecha_emision, -id).
            models.Index(fields=['empresa', 'estado', '-fecha_emision', '-id'], name='ix_documento_emp_estado_fecha'),
        ]

    def __str__(self):
        return f"{self.clase} {self.serie_normalizada}-{self.numero_normalizado} ({self.ruc_emisor})"


class DocumentoDetalle(models.Model):
    documento = models.ForeignKey(
        'documentos.Documento',
        on_delete=models.CASCADE,
        db_column='documento_id',
        related_name='detalles'
    )
    linea = models.IntegerField()

    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='producto_id',
        related_name='documento_detalles'
    )
    producto_unidad = models.ForeignKey(
        'inventario.ProductoUnidad',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='producto_unidad_id',
        related_name='documento_detalles'
    )
    almacen = models.ForeignKey(
        'inventario.Almacen',
        on_delete=models.RESTRICT,
        db_column='almacen_id',
        related_name='documento_detalles'
    )

    tipo_operacion = models.ForeignKey(
        'catalogos.TipoOperacion',
        on_delete=models.RESTRICT,
        db_column='tipo_operacion_id',
        related_name='documento_detalles'
    )
    afecta_kardex_aplicado = models.BooleanField(default=True, db_default=True)
    equivalencia = models.ForeignKey(
        'inventario.ProductoEquivalencia',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='equivalencia_id',
        related_name='documento_detalles'
    )

    descripcion_original = models.CharField(max_length=500, null=True, blank=True)
    cantidad_original = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    factor_conversion = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    cantidad_base = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    precio_unitario = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    igv = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    porcentaje_credito_fiscal_aplicado = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    costo_unitario_pen = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    es_bonificacion = models.BooleanField(default=False, db_default=False)
    # Bloque 3: afectación del IGV de la línea. NULL solo en líneas históricas cuya
    # afectación no se pudo determinar al migrar (IGV 0 sin bonificación).
    afectacion_igv = models.CharField(max_length=12, choices=AFECTACIONES, null=True, blank=True)
    codigo_afectacion_igv = models.CharField(max_length=2, null=True, blank=True)  # Catálogo 07 SUNAT
    detalle_origen = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='detalle_origen_id',
        related_name='detalles_derivados'
    )

    class Meta:
        db_table = 'documento_detalle'
        verbose_name = 'Detalle de Documento'
        verbose_name_plural = 'Detalles de Documento'
        constraints = [
            models.UniqueConstraint(
                fields=['documento', 'linea'],
                name='uq_documento_detalle_linea'
            ),
            models.CheckConstraint(
                condition=models.Q(cantidad_original__isnull=True) | models.Q(cantidad_original__gte=0),
                name='chk_doc_det_cantidad_original'
            ),
            models.CheckConstraint(
                condition=models.Q(factor_conversion__isnull=True) | models.Q(factor_conversion__gt=0),
                name='chk_doc_det_factor_conversion'
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(porcentaje_credito_fiscal_aplicado__isnull=True) |
                    models.Q(
                        porcentaje_credito_fiscal_aplicado__gte=0,
                        porcentaje_credito_fiscal_aplicado__lte=100
                    )
                ),
                name='chk_doc_det_porcentaje_cf'
            ),
        ]
        indexes = [
            models.Index(fields=['producto'], name='idx_doc_det_producto'),
            models.Index(fields=['almacen'], name='idx_doc_det_almacen'),
            models.Index(fields=['detalle_origen'], name='idx_doc_det_origen'),
        ]

    def __str__(self):
        return f"Doc #{self.documento_id} Línea {self.linea} (Prod: {self.producto_id})"


class DocumentoCaptura(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='capturas'
    )
    documento = models.ForeignKey(
        'documentos.Documento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='documento_id',
        related_name='capturas'
    )
    tipo = models.CharField(max_length=20)
    ruta_archivo = models.CharField(max_length=500)
    hash_sha256 = models.CharField(max_length=64, null=True, blank=True)
    estado_proceso = models.CharField(max_length=30, default='PENDIENTE', db_default='PENDIENTE')
    subido_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='subido_por',
        related_name='+'
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'documento_captura'
        verbose_name = 'Documento de Captura'
        verbose_name_plural = 'Documentos de Captura'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tipo__in=['XML', 'PDF', 'IMAGEN', 'ESCANER']),
                name='chk_documento_captura_tipo'
            ),
        ]
        indexes = [
            models.Index(fields=['empresa', 'creado_en'], name='idx_doc_captura_emp_creado'),
            models.Index(fields=['documento'], name='idx_doc_captura_documento'),
        ]

    def __str__(self):
        return f"Captura #{self.id} [{self.tipo}] - {self.estado_proceso}"


class CapturaCampo(models.Model):
    documento_captura = models.ForeignKey(
        'documentos.DocumentoCaptura',
        on_delete=models.CASCADE,
        db_column='documento_captura_id',
        related_name='campos'
    )
    seccion = models.CharField(max_length=20)
    numero_linea = models.IntegerField(null=True, blank=True)
    nombre_campo = models.CharField(max_length=100)
    valor_extraido = models.TextField(null=True, blank=True)
    confianza = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    valor_corregido = models.TextField(null=True, blank=True)
    corregido_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='corregido_por',
        related_name='+'
    )

    class Meta:
        db_table = 'captura_campo'
        verbose_name = 'Campo de Captura'
        verbose_name_plural = 'Campos de Captura'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(seccion__in=['CABECERA', 'DETALLE']),
                name='chk_captura_campo_seccion'
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(confianza__isnull=True) |
                    models.Q(confianza__gte=0, confianza__lte=100)
                ),
                name='chk_captura_campo_confianza'
            ),
        ]
        indexes = [
            models.Index(fields=['documento_captura', 'seccion'], name='idx_cap_campo_doc_sec'),
        ]

    def __str__(self):
        return f"Campo {self.nombre_campo} ({self.seccion}) - Captura #{self.documento_captura_id}"



class SerieComprobante(models.Model):
    """
    Bloque 16: serie de comprobantes de VENTA con correlativo automático. El backend es la
    única fuente del número: `ultimo_correlativo` se incrementa con la fila bloqueada
    (select_for_update) dentro de la transacción que crea el comprobante.
    """
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, db_column='empresa_id',
                                related_name='series_comprobante')
    establecimiento = models.ForeignKey('empresas.Establecimiento', on_delete=models.RESTRICT,
                                        db_column='establecimiento_id', related_name='series_comprobante')
    tipo_comprobante = models.ForeignKey('catalogos.TipoComprobante', on_delete=models.RESTRICT,
                                         db_column='tipo_comprobante_id', related_name='+')
    serie = models.CharField(max_length=4)
    ultimo_correlativo = models.BigIntegerField(default=0, db_default=0)
    activo = models.BooleanField(default=True, db_default=True)
    creado_en = models.DateTimeField(default=timezone.now, db_default=Now())
    actualizado_en = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = 'serie_comprobante'
        verbose_name = 'Serie de Comprobante'
        verbose_name_plural = 'Series de Comprobante'
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'tipo_comprobante', 'serie'], name='uq_serie_comprobante'),
            models.CheckConstraint(condition=models.Q(ultimo_correlativo__gte=0, ultimo_correlativo__lte=99999999),
                                   name='chk_serie_comprobante_correlativo'),
            models.CheckConstraint(condition=models.Q(serie__regex=r'^[A-Z0-9]{4}$'), name='chk_serie_comprobante_formato'),
        ]

    def __str__(self):
        return f"{self.serie} (último {self.ultimo_correlativo})"


class DocumentoCuota(models.Model):
    """Bloque 16: cuota de un comprobante a crédito. suma(cuotas) == total del comprobante."""
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, db_column='empresa_id', related_name='+')
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, db_column='documento_id', related_name='cuotas')
    numero = models.SmallIntegerField()
    fecha_vencimiento = models.DateField()
    monto = models.DecimalField(max_digits=20, decimal_places=8)

    class Meta:
        db_table = 'documento_cuota'
        ordering = ('numero',)
        constraints = [
            models.UniqueConstraint(fields=['documento', 'numero'], name='uq_documento_cuota_numero'),
            models.CheckConstraint(condition=models.Q(numero__gte=1), name='chk_documento_cuota_numero'),
            models.CheckConstraint(condition=models.Q(monto__gt=0), name='chk_documento_cuota_monto'),
        ]


class PagoDocumento(models.Model):
    """
    Bloque 16: pago (compra) o cobro (venta) de un comprobante CONFIRMADO, en su moneda.
    No se borra: se anula con motivo (estado ANULADO) y queda en la auditoría.
    """
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, db_column='empresa_id', related_name='+')
    documento = models.ForeignKey(Documento, on_delete=models.RESTRICT, db_column='documento_id', related_name='pagos')
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=20, decimal_places=8)
    moneda_codigo = models.ForeignKey('catalogos.Moneda', on_delete=models.RESTRICT, db_column='moneda_codigo',
                                      related_name='+')
    metodo_pago = models.ForeignKey('catalogos.MetodoPago', on_delete=models.RESTRICT, db_column='metodo_pago_codigo',
                                    related_name='+')
    referencia = models.CharField(max_length=100, null=True, blank=True)
    estado = models.CharField(max_length=10, default='VIGENTE', db_default='VIGENTE')
    motivo_anulacion = models.TextField(null=True, blank=True)
    registrado_por = models.ForeignKey('usuarios.Usuario', on_delete=models.SET_NULL, null=True, blank=True,
                                       db_column='registrado_por', related_name='+')
    registrado_en = models.DateTimeField(default=timezone.now, db_default=Now())
    anulado_por = models.ForeignKey('usuarios.Usuario', on_delete=models.SET_NULL, null=True, blank=True,
                                    db_column='anulado_por', related_name='+')
    anulado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'pago_documento'
        ordering = ('fecha', 'id')
        indexes = [models.Index(fields=['empresa', 'documento'], name='ix_pago_documento_emp_doc')]
        constraints = [
            models.CheckConstraint(condition=models.Q(monto__gt=0), name='chk_pago_documento_monto'),
            models.CheckConstraint(condition=models.Q(estado__in=['VIGENTE', 'ANULADO']), name='chk_pago_documento_estado'),
        ]
