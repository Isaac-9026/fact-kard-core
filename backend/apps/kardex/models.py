from decimal import Decimal
from django.db import models


class Movimiento(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='movimientos'
    )
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.CASCADE,
        db_column='producto_id',
        related_name='movimientos'
    )
    almacen = models.ForeignKey(
        'inventario.Almacen',
        on_delete=models.CASCADE,
        db_column='almacen_id',
        related_name='movimientos'
    )
    periodo = models.ForeignKey(
        'empresas.Periodo',
        on_delete=models.CASCADE,
        db_column='periodo_id',
        related_name='movimientos'
    )

    # Orígenes opcionales
    documento_detalle = models.ForeignKey(
        'documentos.DocumentoDetalle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='documento_detalle_id',
        related_name='movimientos'
    )
    nota_interna_detalle = models.ForeignKey(
        'inventario.NotaInternaDetalle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='nota_interna_detalle_id',
        related_name='movimientos'
    )
    transferencia_detalle = models.ForeignKey(
        'inventario.TransferenciaDetalle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='transferencia_detalle_id',
        related_name='movimientos'
    )
    transferencia = models.ForeignKey(
        'inventario.Transferencia',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='transferencia_id',
        related_name='movimientos'
    )
    saldo_inicial = models.ForeignKey(
        'inventario.SaldoInicial',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='saldo_inicial_id',
        related_name='movimientos'
    )

    # Autorreferencias opcionales
    movimiento_origen = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='movimiento_origen_id',
        related_name='devoluciones'
    )
    movimiento_extornado = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='movimiento_extornado_id',
        related_name='extornos'
    )

    tipo_operacion = models.ForeignKey(
        'catalogos.TipoOperacion',
        on_delete=models.RESTRICT,
        db_column='tipo_operacion_id',
        related_name='movimientos'
    )

    fecha_movimiento = models.DateField()
    prioridad_dia = models.SmallIntegerField()
    secuencia = models.IntegerField(default=0, db_default=0)

    naturaleza = models.CharField(max_length=20)

    cantidad_base = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.00000000'),
        db_default=Decimal('0.00000000')
    )
    valor_ajuste_pen = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    es_extorno = models.BooleanField(default=False, db_default=False)
    generado_por_motor = models.BooleanField(default=False, db_default=False)

    creado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='creado_por',
        related_name='+'
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'movimiento'
        verbose_name = 'Movimiento de Kardex'
        verbose_name_plural = 'Movimientos de Kardex'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(naturaleza__in=['ENTRADA', 'SALIDA', 'AJUSTE_VALOR']),
                name='chk_movimiento_naturaleza'
            ),
            models.CheckConstraint(
                condition=models.Q(prioridad_dia__range=(1, 4)),
                name='chk_movimiento_prioridad_dia'
            ),
            models.CheckConstraint(
                condition=models.Q(cantidad_base__gte=0),
                name='chk_movimiento_cantidad_base'
            ),
        ]
        indexes = [
            models.Index(
                fields=['empresa', 'producto', 'fecha_movimiento', 'prioridad_dia', 'secuencia', 'id'],
                name='ix_movimiento_orden'
            ),
            models.Index(
                fields=['empresa', 'almacen', 'producto'],
                name='ix_movimiento_almacen'
            ),
            models.Index(
                fields=['periodo'],
                name='ix_movimiento_periodo'
            ),
            # Bloque 7: orden cronológico de TODA la empresa (Kardex sin filtro de producto y
            # /api/kardex/movimientos/ paginado). ix_movimiento_orden empieza por producto.
            models.Index(
                fields=['empresa', 'fecha_movimiento', 'prioridad_dia', 'secuencia', 'id'],
                name='ix_movimiento_empresa_fecha'
            ),
        ]

    def __str__(self):
        return f"Mov #{self.id} ({self.naturaleza}) - {self.producto_id} - Cant: {self.cantidad_base}"


class Recalculo(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='recalculos'
    )
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.CASCADE,
        db_column='producto_id',
        related_name='recalculos'
    )
    fecha_desde = models.DateField()
    fecha_hasta = models.DateField(null=True, blank=True)
    motivo = models.CharField(max_length=500, null=True, blank=True)
    version = models.IntegerField()
    estado = models.CharField(max_length=20, default='EN_PROCESO', db_default='EN_PROCESO')
    ejecutado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='ejecutado_por',
        related_name='+'
    )
    ejecutado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recalculo'
        verbose_name = 'Recálculo de Kardex'
        verbose_name_plural = 'Recálculos de Kardex'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estado__in=['EN_PROCESO', 'OK', 'ERROR']),
                name='chk_recalculo_estado'
            )
        ]
        indexes = [
            models.Index(
                fields=['empresa', 'producto', 'fecha_desde'],
                name='ix_recalculo_empresa_producto'
            )
        ]

    def __str__(self):
        return f"Recálculo #{self.id} ({self.producto_id}) desde {self.fecha_desde} - {self.estado}"


class ValorizacionMovimiento(models.Model):
    movimiento = models.OneToOneField(
        'kardex.Movimiento',
        on_delete=models.CASCADE,
        db_column='movimiento_id',
        related_name='valorizacion'
    )
    costo_unitario_pen = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    valor_movimiento_pen = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    saldo_cantidad_empresa = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    saldo_valor_empresa = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    cpp_empresa = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    version_actual = models.IntegerField(default=1, db_default=1)
    recalculo = models.ForeignKey(
        'kardex.Recalculo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='recalculo_id',
        related_name='valorizaciones'
    )
    calculado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'valorizacion_movimiento'
        verbose_name = 'Valorización de Movimiento'
        verbose_name_plural = 'Valorizaciones de Movimiento'

    def __str__(self):
        return f"Val #{self.id} Mov #{self.movimiento_id} - CPP: {self.cpp_empresa}"


class RecalculoDetalle(models.Model):
    recalculo = models.ForeignKey(
        'kardex.Recalculo',
        on_delete=models.CASCADE,
        db_column='recalculo_id',
        related_name='detalles'
    )
    movimiento = models.ForeignKey(
        'kardex.Movimiento',
        on_delete=models.CASCADE,
        db_column='movimiento_id',
        related_name='recalculo_detalles'
    )

    cpp_anterior = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    cpp_nuevo = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    valor_anterior = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    valor_nuevo = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    saldo_anterior = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    saldo_nuevo = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    class Meta:
        db_table = 'recalculo_detalle'
        verbose_name = 'Detalle de Recálculo'
        verbose_name_plural = 'Detalles de Recálculo'

    def __str__(self):
        return f"Detalle Recálculo #{self.recalculo_id} - Mov #{self.movimiento_id}"


class StockAlmacen(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='stocks_almacen'
    )
    almacen = models.ForeignKey(
        'inventario.Almacen',
        on_delete=models.CASCADE,
        db_column='almacen_id',
        related_name='stocks'
    )
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.CASCADE,
        db_column='producto_id',
        related_name='stocks_almacen'
    )
    cantidad_actual = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.00000000'),
        db_default=Decimal('0.00000000')
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'stock_almacen'
        verbose_name = 'Stock por Almacén'
        verbose_name_plural = 'Stocks por Almacén'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'almacen', 'producto'],
                name='uq_stock_almacen_empresa_almacen_producto'
            )
        ]

    def __str__(self):
        return f"Stock {self.producto_id} @ {self.almacen_id}: {self.cantidad_actual}"


class SaldoCppActual(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='saldos_cpp_actual'
    )
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.CASCADE,
        db_column='producto_id',
        related_name='saldos_cpp_actual'
    )
    cantidad_total = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.00000000'),
        db_default=Decimal('0.00000000')
    )
    valor_total_pen = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.00000000'),
        db_default=Decimal('0.00000000')
    )
    cpp_pen = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    ultimo_movimiento = models.ForeignKey(
        'kardex.Movimiento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='ultimo_movimiento_id',
        related_name='+'
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'saldo_cpp_actual'
        verbose_name = 'Saldo CPP Actual'
        verbose_name_plural = 'Saldos CPP Actuales'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'producto'],
                name='uq_saldo_cpp_actual_empresa_producto'
            )
        ]

    def __str__(self):
        return f"Saldo CPP {self.producto_id}: Cant {self.cantidad_total} | CPP {self.cpp_pen}"


class Incidencia(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='incidencias'
    )
    periodo = models.ForeignKey(
        'empresas.Periodo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='periodo_id',
        related_name='incidencias'
    )
    documento = models.ForeignKey(
        'documentos.Documento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='documento_id',
        related_name='incidencias'
    )
    documento_detalle = models.ForeignKey(
        'documentos.DocumentoDetalle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='documento_detalle_id',
        related_name='incidencias'
    )
    movimiento = models.ForeignKey(
        'kardex.Movimiento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='movimiento_id',
        related_name='incidencias'
    )
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='producto_id',
        related_name='incidencias'
    )

    tipo = models.CharField(max_length=80)
    severidad = models.CharField(max_length=20, default='ERROR', db_default='ERROR')
    bloquea_cierre = models.BooleanField(default=True, db_default=True)
    estado = models.CharField(max_length=20, default='PENDIENTE', db_default='PENDIENTE')

    descripcion = models.TextField()
    detalle = models.JSONField(null=True, blank=True)

    detectado_en = models.DateTimeField(auto_now_add=True)
    resuelto_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='resuelto_por',
        related_name='+'
    )
    resuelto_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'incidencia'
        verbose_name = 'Incidencia de Kardex'
        verbose_name_plural = 'Incidencias de Kardex'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estado__in=['PENDIENTE', 'RESUELTA', 'DESCARTADA']),
                name='chk_incidencia_estado'
            ),
            models.CheckConstraint(
                condition=models.Q(severidad__in=['INFO', 'ADVERTENCIA', 'ERROR', 'CRITICA']),
                name='chk_incidencia_severidad'
            ),
        ]
        indexes = [
            models.Index(
                fields=['empresa', 'estado'],
                name='ix_incidencia_empresa_estado'
            ),
            models.Index(
                fields=['periodo', 'bloquea_cierre', 'estado'],
                name='ix_incidencia_periodo_bloqueo'
            ),
        ]

    def __str__(self):
        return f"Incidencia #{self.id} [{self.severidad}] ({self.tipo}) - {self.estado}"
