from decimal import Decimal
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone
from apps.documentos.afectacion_igv import AFECTACIONES


class Almacen(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='almacenes'
    )
    establecimiento = models.ForeignKey(
        'empresas.Establecimiento',
        on_delete=models.CASCADE,
        db_column='establecimiento_id',
        related_name='almacenes'
    )
    codigo = models.CharField(max_length=50)
    nombre = models.CharField(max_length=150)
    activo = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = 'almacen'
        verbose_name = 'Almacén'
        verbose_name_plural = 'Almacenes'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'codigo'],
                name='uq_almacen_empresa_codigo'
            )
        ]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class Tercero(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='terceros'
    )
    tipo_documento = models.CharField(max_length=20)
    numero_documento = models.CharField(max_length=20)
    razon_social = models.CharField(max_length=200)
    nombre_comercial = models.CharField(max_length=200, null=True, blank=True)
    direccion = models.CharField(max_length=300, null=True, blank=True)
    telefono = models.CharField(max_length=50, null=True, blank=True)
    correo = models.EmailField(max_length=254, null=True, blank=True)
    es_cliente = models.BooleanField(default=False, db_default=False)
    es_proveedor = models.BooleanField(default=False, db_default=False)
    estado = models.CharField(max_length=20, default='ACTIVO', db_default='ACTIVO')
    creado_en = models.DateTimeField(default=timezone.now, db_default=Now())
    actualizado_en = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = 'tercero'
        verbose_name = 'Tercero (Cliente/Proveedor)'
        verbose_name_plural = 'Terceros'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'tipo_documento', 'numero_documento'],
                name='uq_tercero_empresa_tipo_num'
            ),
            # Bloque 16: solo códigos del catálogo 06 (sin alias como 'RUC' o 'DNI').
            models.CheckConstraint(
                condition=models.Q(tipo_documento__in=['0', '1', '4', '6', '7', 'A']),
                name='chk_tercero_tipo_documento'
            ),
            models.CheckConstraint(
                condition=models.Q(es_cliente=True) | models.Q(es_proveedor=True),
                name='chk_tercero_cliente_o_proveedor'
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=['ACTIVO', 'INACTIVO']),
                name='chk_tercero_estado'
            )
        ]

    def __str__(self):
        return f"{self.tipo_documento} {self.numero_documento} - {self.razon_social}"


class Producto(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='productos'
    )
    codigo_interno = models.CharField(max_length=50)
    descripcion = models.CharField(max_length=250)
    tipo_existencia_codigo = models.ForeignKey(
        'catalogos.TipoExistencia',
        on_delete=models.RESTRICT,
        db_column='tipo_existencia_codigo',
        related_name='productos'
    )
    estado = models.CharField(max_length=20, default='ACTIVO', db_default='ACTIVO')
    # Bloque 16: datos comerciales. Solo sugieren valores al crear una línea de venta; nunca
    # intervienen en el costo, el CPP ni el Kardex.
    precio_venta_sugerido = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    afectacion_igv_defecto = models.CharField(max_length=12, choices=AFECTACIONES, null=True, blank=True)

    class Meta:
        db_table = 'producto'
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'codigo_interno'],
                name='uq_producto_empresa_codigo'
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=['ACTIVO', 'INACTIVO']),
                name='chk_producto_estado'
            ),
            models.CheckConstraint(
                condition=models.Q(precio_venta_sugerido__isnull=True) | models.Q(precio_venta_sugerido__gte=0),
                name='chk_producto_precio_venta_sugerido'
            ),
        ]

    def __str__(self):
        return f"{self.codigo_interno} - {self.descripcion}"


class ProductoUnidad(models.Model):
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.CASCADE,
        db_column='producto_id',
        related_name='unidades'
    )
    unidad_codigo = models.ForeignKey(
        'catalogos.UnidadMedida',
        on_delete=models.RESTRICT,
        db_column='unidad_codigo',
        related_name='producto_unidades'
    )
    factor_a_base = models.DecimalField(max_digits=20, decimal_places=8)
    es_base = models.BooleanField(default=False, db_default=False)

    class Meta:
        db_table = 'producto_unidad'
        verbose_name = 'Unidad de Producto'
        verbose_name_plural = 'Unidades de Producto'
        constraints = [
            models.UniqueConstraint(
                fields=['producto', 'unidad_codigo'],
                name='uq_producto_unidad'
            ),
            models.CheckConstraint(
                condition=models.Q(factor_a_base__gt=0),
                name='chk_producto_unidad_factor'
            ),
            models.UniqueConstraint(
                fields=['producto'],
                condition=models.Q(es_base=True),
                name='uq_producto_unidad_base'
            )
        ]

    def __str__(self):
        return f"{self.producto.codigo_interno} en {self.unidad_codigo_id} (Factor: {self.factor_a_base}, Base: {self.es_base})"


class ProductoEquivalencia(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='equivalencias'
    )
    tercero = models.ForeignKey(
        'inventario.Tercero',
        on_delete=models.CASCADE,
        db_column='tercero_id',
        related_name='equivalencias'
    )
    codigo_externo = models.CharField(max_length=100, null=True, blank=True)
    descripcion_externa = models.CharField(max_length=300, null=True, blank=True)
    unidad_externa_codigo = models.ForeignKey(
        'catalogos.UnidadMedida',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='unidad_externa_codigo',
        related_name='equivalencias'
    )
    producto_unidad = models.ForeignKey(
        'inventario.ProductoUnidad',
        on_delete=models.CASCADE,
        db_column='producto_unidad_id',
        related_name='equivalencias'
    )
    factor_conversion = models.DecimalField(max_digits=20, decimal_places=8)
    confirmado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='confirmado_por',
        related_name='+'
    )
    confirmado_en = models.DateTimeField(null=True, blank=True)
    activa = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = 'producto_equivalencia'
        verbose_name = 'Equivalencia de Producto'
        verbose_name_plural = 'Equivalencias de Producto'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(factor_conversion__gt=0),
                name='chk_producto_equivalencia_factor'
            )
        ]

    def __str__(self):
        return f"Equivalencia Tercero {self.tercero_id}: {self.codigo_externo} -> {self.producto_unidad_id}"


class SaldoInicial(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='saldos_iniciales'
    )
    periodo = models.ForeignKey(
        'empresas.Periodo',
        on_delete=models.CASCADE,
        db_column='periodo_id',
        related_name='saldos_iniciales'
    )
    almacen = models.ForeignKey(
        'inventario.Almacen',
        on_delete=models.CASCADE,
        db_column='almacen_id',
        related_name='saldos_iniciales'
    )
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.CASCADE,
        db_column='producto_id',
        related_name='saldos_iniciales'
    )
    cantidad = models.DecimalField(max_digits=20, decimal_places=8)
    valor_pen = models.DecimalField(max_digits=20, decimal_places=8)
    cpp_inicial = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    estado = models.CharField(max_length=20, default='BORRADOR', db_default='BORRADOR')
    creado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='creado_por',
        related_name='+'
    )

    class Meta:
        db_table = 'saldo_inicial'
        verbose_name = 'Saldo Inicial'
        verbose_name_plural = 'Saldos Iniciales'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'periodo', 'almacen', 'producto'],
                name='uq_saldo_inicial_empresa_periodo_almacen_producto'
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=['BORRADOR', 'CONFIRMADO']),
                name='chk_saldo_inicial_estado'
            ),
            models.CheckConstraint(
                condition=models.Q(cantidad__gte=0),
                name='chk_saldo_inicial_cantidad'
            )
        ]

    def __str__(self):
        return f"Saldo Inicial {self.producto_id} ({self.almacen_id}) - {self.cantidad}"


class NotaInterna(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='notas_internas'
    )
    almacen = models.ForeignKey(
        'inventario.Almacen',
        on_delete=models.CASCADE,
        db_column='almacen_id',
        related_name='notas_internas'
    )
    periodo = models.ForeignKey(
        'empresas.Periodo',
        on_delete=models.CASCADE,
        db_column='periodo_id',
        related_name='notas_internas'
    )
    tipo_operacion = models.ForeignKey(
        'catalogos.TipoOperacion',
        on_delete=models.RESTRICT,
        db_column='tipo_operacion_id',
        related_name='notas_internas'
    )
    fecha = models.DateField()
    motivo = models.CharField(max_length=500)
    responsable = models.CharField(max_length=200, null=True, blank=True)
    observacion = models.TextField(null=True, blank=True)
    archivo_sustento = models.CharField(max_length=500, null=True, blank=True)
    estado = models.CharField(max_length=20, default='BORRADOR', db_default='BORRADOR')
    creado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='creado_por',
        related_name='+'
    )

    class Meta:
        db_table = 'nota_interna'
        verbose_name = 'Nota Interna'
        verbose_name_plural = 'Notas Internas'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estado__in=['BORRADOR', 'CONFIRMADO', 'ANULADO']),
                name='chk_nota_interna_estado'
            )
        ]

    def __str__(self):
        return f"Nota Interna #{self.id} ({self.tipo_operacion_id}) - {self.estado}"


class NotaInternaDetalle(models.Model):
    nota_interna = models.ForeignKey(
        'inventario.NotaInterna',
        on_delete=models.CASCADE,
        db_column='nota_interna_id',
        related_name='detalles'
    )
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.CASCADE,
        db_column='producto_id',
        related_name='notas_internas_detalles'
    )
    cantidad_base = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.00000000'),
        db_default=Decimal('0.00000000')
    )
    costo_unitario_pen = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    valor_ajuste_pen = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    class Meta:
        db_table = 'nota_interna_detalle'
        verbose_name = 'Detalle de Nota Interna'
        verbose_name_plural = 'Detalles de Nota Interna'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cantidad_base__gte=0),
                name='chk_nota_interna_detalle_cantidad'
            )
        ]

    def __str__(self):
        return f"Detalle Nota {self.nota_interna_id} - Producto {self.producto_id}: {self.cantidad_base}"


class Transferencia(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='transferencias'
    )
    almacen_origen = models.ForeignKey(
        'inventario.Almacen',
        on_delete=models.RESTRICT,
        db_column='almacen_origen_id',
        related_name='transferencias_origen'
    )
    almacen_destino = models.ForeignKey(
        'inventario.Almacen',
        on_delete=models.RESTRICT,
        db_column='almacen_destino_id',
        related_name='transferencias_destino'
    )
    fecha = models.DateField()
    estado = models.CharField(max_length=20, default='BORRADOR', db_default='BORRADOR')
    creado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='creado_por',
        related_name='+'
    )

    class Meta:
        db_table = 'transferencia'
        verbose_name = 'Transferencia entre Almacenes'
        verbose_name_plural = 'Transferencias entre Almacenes'
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(almacen_origen=models.F('almacen_destino')),
                name='chk_transferencia_almacenes_distintos'
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=['BORRADOR', 'CONFIRMADO', 'ANULADO']),
                name='chk_transferencia_estado'
            )
        ]

    def __str__(self):
        return f"Transferencia #{self.id} ({self.almacen_origen_id} -> {self.almacen_destino_id}) - {self.estado}"


class TransferenciaDetalle(models.Model):
    transferencia = models.ForeignKey(
        'inventario.Transferencia',
        on_delete=models.CASCADE,
        db_column='transferencia_id',
        related_name='detalles'
    )
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.RESTRICT,
        db_column='producto_id',
        related_name='transferencias_detalles'
    )
    cantidad_base = models.DecimalField(max_digits=20, decimal_places=8)

    class Meta:
        db_table = 'transferencia_detalle'
        verbose_name = 'Detalle de Transferencia'
        verbose_name_plural = 'Detalles de Transferencia'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cantidad_base__gt=0),
                name='chk_transferencia_detalle_cantidad'
            )
        ]

    def __str__(self):
        return f"Detalle Transferencia #{self.transferencia_id} - Producto {self.producto_id}: {self.cantidad_base}"

