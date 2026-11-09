from django.db import models


class Moneda(models.Model):
    codigo = models.CharField(max_length=3, primary_key=True)
    nombre = models.CharField(max_length=100)

    class Meta:
        db_table = 'moneda'
        verbose_name = 'Moneda'
        verbose_name_plural = 'Monedas'

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class TipoCambio(models.Model):
    moneda_codigo = models.ForeignKey(
        'catalogos.Moneda',
        on_delete=models.RESTRICT,
        db_column='moneda_codigo',
        related_name='tipos_cambio'
    )
    fecha_publicacion = models.DateField()
    venta = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    compra = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    fuente = models.CharField(max_length=50)

    class Meta:
        db_table = 'tipo_cambio'
        verbose_name = 'Tipo de Cambio'
        verbose_name_plural = 'Tipos de Cambio'
        constraints = [
            models.UniqueConstraint(
                fields=['moneda_codigo', 'fecha_publicacion', 'fuente'],
                name='uq_tipo_cambio_moneda_fecha_fuente'
            )
        ]

    def __str__(self):
        return f"{self.moneda_codigo_id} ({self.fecha_publicacion}) - V: {self.venta} / C: {self.compra}"


class TipoComprobante(models.Model):
    codigo_sunat = models.CharField(max_length=10, unique=True)
    descripcion = models.CharField(max_length=150)
    es_nota = models.BooleanField(default=False, db_default=False)
    efecto_nota = models.CharField(max_length=20, default='NINGUNO', db_default='NINGUNO')
    activo = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = 'tipo_comprobante'
        verbose_name = 'Tipo de Comprobante'
        verbose_name_plural = 'Tipos de Comprobante'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(efecto_nota__in=['CREDITO', 'DEBITO', 'NINGUNO']),
                name='chk_tipo_comprobante_efecto_nota'
            )
        ]

    def __str__(self):
        return f"{self.codigo_sunat} - {self.descripcion}"


class TipoOperacion(models.Model):
    codigo_interno = models.CharField(max_length=50, unique=True)
    codigo_sunat = models.CharField(max_length=10, null=True, blank=True)
    descripcion = models.CharField(max_length=150)
    naturaleza = models.CharField(max_length=20)
    es_interna = models.BooleanField(default=False, db_default=False)
    afecta_kardex = models.BooleanField(default=True, db_default=True)
    origen_requerido = models.CharField(max_length=30)
    activo = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = 'tipo_operacion'
        verbose_name = 'Tipo de Operación'
        verbose_name_plural = 'Tipos de Operación'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(naturaleza__in=['ENTRADA', 'SALIDA', 'AJUSTE_VALOR']),
                name='chk_tipo_operacion_naturaleza'
            ),
            models.CheckConstraint(
                condition=models.Q(origen_requerido__in=[
                    'DOCUMENTO', 'NOTA_INTERNA', 'TRANSFERENCIA',
                    'SALDO_INICIAL', 'MOV_ORIGEN', 'MOV_EXTORNADO', 'MOTOR'
                ]),
                name='chk_tipo_operacion_origen_requerido'
            )
        ]

    def __str__(self):
        return f"{self.codigo_interno} ({self.naturaleza}) - {self.descripcion}"


class TipoExistencia(models.Model):
    codigo = models.CharField(max_length=10, primary_key=True)
    descripcion = models.CharField(max_length=150)

    class Meta:
        db_table = 'tipo_existencia'
        verbose_name = 'Tipo de Existencia'
        verbose_name_plural = 'Tipos de Existencia'

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"


class UnidadMedida(models.Model):
    codigo = models.CharField(max_length=10, primary_key=True)
    descripcion = models.CharField(max_length=100)

    class Meta:
        db_table = 'unidad_medida'
        verbose_name = 'Unidad de Medida'
        verbose_name_plural = 'Unidades de Medida'

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"


class MetodoPago(models.Model):
    """
    Bloque 16: catálogo extensible de métodos de pago/cobro (EFECTIVO, TRANSFERENCIA, ...).
    Se agregan filas nuevas sin cambiar código; `activo` oculta un método sin borrarlo.
    """
    codigo = models.CharField(max_length=20, primary_key=True)
    descripcion = models.CharField(max_length=100)
    activo = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = 'metodo_pago'
        verbose_name = 'Método de Pago'
        verbose_name_plural = 'Métodos de Pago'

    def __str__(self):
        return f"{self.codigo} - {self.descripcion}"


class MotivoNota(models.Model):
    """
    Bloque 17A: motivos tributarios de las notas electrónicas (Anexo 8, R.S. 097-2012/SUNAT).
    catalogo '09' = tipo de nota de crédito; '10' = tipo de nota de débito. Catálogo
    controlado: se desactiva, no se borra. No decide el efecto contable (eso lo deciden las líneas).
    """
    CATALOGO_NC, CATALOGO_ND = '09', '10'

    catalogo = models.CharField(max_length=2)
    codigo = models.CharField(max_length=2)
    descripcion = models.CharField(max_length=200)
    activo = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = 'motivo_nota'
        ordering = ('catalogo', 'codigo')
        constraints = [
            models.UniqueConstraint(fields=['catalogo', 'codigo'], name='uq_motivo_nota_catalogo_codigo'),
            models.CheckConstraint(condition=models.Q(catalogo__in=['09', '10']), name='chk_motivo_nota_catalogo'),
        ]

    def __str__(self):
        return f'{self.catalogo}-{self.codigo} {self.descripcion}'
