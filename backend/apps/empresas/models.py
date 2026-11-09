import uuid
from decimal import Decimal
from django.db import models


def ruta_logo_empresa(instance, filename):
    return f'empresas/{instance.id}/logos/{uuid.uuid4().hex}.webp'
from django.db.models.functions import Now
from django.utils import timezone


class Empresa(models.Model):
    ruc = models.CharField(max_length=11, unique=True)
    razon_social = models.CharField(max_length=200)
    nombre_comercial = models.CharField(max_length=200, null=True, blank=True)
    direccion = models.CharField(max_length=300, null=True, blank=True)  # domicilio fiscal
    # Bloque 17A: ubicación del domicilio fiscal del emisor electrónico.
    ubigeo = models.CharField(max_length=6, null=True, blank=True)
    departamento = models.CharField(max_length=100, null=True, blank=True)
    provincia = models.CharField(max_length=100, null=True, blank=True)
    distrito = models.CharField(max_length=100, null=True, blank=True)
    codigo_pais = models.CharField(max_length=2, default='PE', db_default='PE')
    moneda_base_codigo = models.ForeignKey(
        'catalogos.Moneda',
        on_delete=models.RESTRICT,
        db_column='moneda_base_codigo',
        related_name='empresas'
    )
    estado = models.CharField(max_length=20, default='ACTIVA', db_default='ACTIVA')
    creado_en = models.DateTimeField(default=timezone.now, db_default=Now())
    logo = models.ImageField(upload_to=ruta_logo_empresa, max_length=255, null=True, blank=True)
    color_tema = models.CharField(max_length=7, null=True, blank=True)

    class Meta:
        db_table = 'empresa'
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estado__in=['ACTIVA', 'INACTIVA']),
                name='chk_empresa_estado'
            ),
            models.CheckConstraint(
                condition=models.Q(ubigeo__isnull=True) | models.Q(ubigeo__regex=r'^[0-9]{6}$'),
                name='chk_empresa_ubigeo'
            ),
            models.CheckConstraint(condition=models.Q(codigo_pais__regex=r'^[A-Z]{2}$'), name='chk_empresa_codigo_pais'),
            models.CheckConstraint(
                condition=models.Q(color_tema__isnull=True) | models.Q(color_tema__regex=r'^#[0-9A-Fa-f]{6}$'),
                name='chk_empresa_color_tema',
            ),
        ]

    def __str__(self):
        return f"{self.ruc} - {self.razon_social}"


class Establecimiento(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='establecimientos'
    )
    codigo_sunat = models.CharField(max_length=20)
    nombre = models.CharField(max_length=150)
    activo = models.BooleanField(default=True, db_default=True)
    # Bloque 17A: dirección del establecimiento (el principal es ConfigEmpresa.establecimiento_principal).
    direccion = models.CharField(max_length=300, null=True, blank=True)
    ubigeo = models.CharField(max_length=6, null=True, blank=True)

    class Meta:
        db_table = 'establecimiento'
        verbose_name = 'Establecimiento'
        verbose_name_plural = 'Establecimientos'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'codigo_sunat'],
                name='uq_establecimiento_empresa_codigo'
            ),
            models.CheckConstraint(
                condition=models.Q(ubigeo__isnull=True) | models.Q(ubigeo__regex=r'^[0-9]{6}$'),
                name='chk_establecimiento_ubigeo'
            ),
        ]

    def __str__(self):
        return f"{self.codigo_sunat} - {self.nombre}"


# Bloque 4: tasa del IGV (16 % IGV + 2 % IPM) por defecto. Única definición en el código;
# la tasa aplicable se lee de ConfigEmpresa.tasa_igv_pct (ver documentos.afectacion_igv).
TASA_IGV_POR_DEFECTO_PCT = Decimal('18.00')


class ConfigEmpresa(models.Model):
    empresa = models.OneToOneField(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='configuracion'
    )
    tolerancia_residuo_pen = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=Decimal('0.05'),
        db_default=Decimal('0.05')
    )
    decimales_calculo = models.SmallIntegerField(default=6, db_default=6)
    regla_redondeo = models.CharField(max_length=30, default='ROUND_HALF_UP', db_default='ROUND_HALF_UP')
    metodo_valuacion = models.CharField(max_length=20, default='CPP', db_default='CPP')
    tasa_igv_pct = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=TASA_IGV_POR_DEFECTO_PCT, db_default=TASA_IGV_POR_DEFECTO_PCT,
    )
    establecimiento_principal = models.ForeignKey(
        'empresas.Establecimiento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='establecimiento_principal_id',
        related_name='+'
    )

    class Meta:
        db_table = 'config_empresa'
        verbose_name = 'Configuración de Empresa'
        verbose_name_plural = 'Configuraciones de Empresa'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(decimales_calculo__range=(2, 8)),
                name='chk_config_empresa_decimales'
            ),
            models.CheckConstraint(
                condition=models.Q(tasa_igv_pct__gt=0, tasa_igv_pct__lte=100),
                name='chk_config_empresa_tasa_igv'
            )
        ]

    def __str__(self):
        return f"Configuración de {self.empresa.razon_social}"


class TasaIgvVigencia(models.Model):
    """
    Bloque 5: tasa del IGV vigente desde una fecha. La tasa de una operación es la del
    registro con mayor `vigente_desde` <= su fecha (ver documentos.afectacion_igv.tasa_igv).
    """
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='tasas_igv'
    )
    vigente_desde = models.DateField()
    tasa_pct = models.DecimalField(max_digits=5, decimal_places=2)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tasa_igv_vigencia'
        ordering = ('vigente_desde',)
        constraints = [
            models.UniqueConstraint(fields=('empresa', 'vigente_desde'), name='uq_tasa_igv_empresa_desde'),
            models.CheckConstraint(
                condition=models.Q(tasa_pct__gt=0, tasa_pct__lte=100),
                name='chk_tasa_igv_vigencia_rango'
            ),
        ]


class Periodo(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='periodos'
    )
    anio = models.SmallIntegerField()
    mes = models.SmallIntegerField()
    orden = models.IntegerField()
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    estado = models.CharField(max_length=20, default='ABIERTO', db_default='ABIERTO')
    motivo_desactualizado = models.CharField(max_length=500, null=True, blank=True)
    cerrado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='cerrado_por',
        related_name='+'
    )
    cerrado_en = models.DateTimeField(null=True, blank=True)
    reabierto_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='reabierto_por',
        related_name='+'
    )
    reabierto_en = models.DateTimeField(null=True, blank=True)
    motivo_reapertura = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = 'periodo'
        verbose_name = 'Período'
        verbose_name_plural = 'Períodos'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'anio', 'mes'],
                name='uq_periodo_empresa_anio_mes'
            ),
            models.CheckConstraint(
                condition=models.Q(mes__range=(1, 12)),
                name='chk_periodo_mes'
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=['ABIERTO', 'CERRADO', 'DESACTUALIZADO']),
                name='chk_periodo_estado'
            ),
            models.CheckConstraint(
                condition=models.Q(fecha_fin__gte=models.F('fecha_inicio')),
                name='chk_periodo_fechas'
            )
        ]

    def __str__(self):
        return f"{self.empresa.razon_social} - {self.anio}/{self.mes:02d} ({self.estado})"


class ConfigIgvPeriodo(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.CASCADE,
        db_column='empresa_id',
        related_name='configs_igv'
    )
    periodo = models.ForeignKey(
        'empresas.Periodo',
        on_delete=models.CASCADE,
        db_column='periodo_id',
        related_name='configs_igv'
    )
    metodo = models.CharField(max_length=20)
    porcentaje_recuperable = models.DecimalField(max_digits=7, decimal_places=4)
    creado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='creado_por',
        related_name='+'
    )
    creado_en = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = 'config_igv_periodo'
        verbose_name = 'Configuración IGV de Período'
        verbose_name_plural = 'Configuraciones IGV de Período'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'periodo'],
                name='uq_config_igv_periodo_empresa_periodo'
            ),
            models.CheckConstraint(
                condition=models.Q(metodo__in=['TOTAL', 'NULO', 'PRORRATA']),
                name='chk_config_igv_periodo_metodo'
            ),
            models.CheckConstraint(
                condition=models.Q(porcentaje_recuperable__range=(Decimal('0'), Decimal('100'))),
                name='chk_config_igv_periodo_porcentaje'
            )
        ]

    def __str__(self):
        return f"IGV {self.empresa.razon_social} - Periodo {self.periodo_id} ({self.metodo} - {self.porcentaje_recuperable}%)"


class CierrePeriodo(models.Model):
    periodo = models.ForeignKey(
        'empresas.Periodo',
        on_delete=models.CASCADE,
        db_column='periodo_id',
        related_name='cierres'
    )
    version_calculo = models.IntegerField()
    cerrado_por = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.RESTRICT,
        db_column='cerrado_por',
        related_name='+'
    )
    cerrado_en = models.DateTimeField(auto_now_add=True)
    archivo_excel = models.CharField(max_length=500, null=True, blank=True)
    hash_resultado = models.CharField(max_length=128, null=True, blank=True)
    snapshot_resumen = models.JSONField(null=True, blank=True)
    vigente = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = 'cierre_periodo'
        verbose_name = 'Cierre de Período'
        verbose_name_plural = 'Cierres de Período'
        constraints = [
            models.UniqueConstraint(
                fields=['periodo', 'version_calculo'],
                name='uq_cierre_periodo_version'
            )
        ]

    def __str__(self):
        return f"Cierre Período {self.periodo_id} v{self.version_calculo} ({'Vigente' if self.vigente else 'Histórico'})"


class CierrePeriodoDetalle(models.Model):
    cierre_periodo = models.ForeignKey(
        'empresas.CierrePeriodo',
        on_delete=models.CASCADE,
        db_column='cierre_periodo_id',
        related_name='detalles'
    )
    producto = models.ForeignKey(
        'inventario.Producto',
        on_delete=models.RESTRICT,
        db_column='producto_id',
        related_name='+'
    )
    establecimiento = models.ForeignKey(
        'empresas.Establecimiento',
        on_delete=models.RESTRICT,
        db_column='establecimiento_id',
        related_name='+'
    )
    saldo_cantidad = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    saldo_valor_pen = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    cpp_pen = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    class Meta:
        db_table = 'cierre_periodo_detalle'
        verbose_name = 'Detalle de Cierre de Período'
        verbose_name_plural = 'Detalles de Cierre de Período'
        constraints = [
            models.UniqueConstraint(
                fields=['cierre_periodo', 'producto', 'establecimiento'],
                name='uq_cierre_detalle_producto_estab'
            )
        ]

    def __str__(self):
        return f"Detalle Cierre #{self.cierre_periodo_id} - Prod {self.producto_id} @ Estab {self.establecimiento_id}"
