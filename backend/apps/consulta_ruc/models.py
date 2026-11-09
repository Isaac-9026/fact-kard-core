"""
Bloque 17D — copia local del Padrón Reducido del RUC publicado por SUNAT.

Estos modelos NO son Empresa, Tercero, Cliente ni Proveedor: guardan solo el dataset oficial
para que el proveedor `padron_reducido` responda GET /api/consulta-ruc/<ruc>/ sin salir a internet.

Versionado (actualización segura):
- Cada importación crea una `VersionPadronRuc` en estado CARGANDO y carga sus filas aparte.
- Solo cuando la carga termina y se valida, la versión pasa a ACTIVA en una transacción que a
  la vez retira la anterior. Las consultas leen siempre la versión ACTIVA.
- Si la importación falla, la versión queda FALLIDA (sus filas se borran) y la ACTIVA anterior
  sigue respondiendo. Nunca se borra el padrón vigente antes de tener uno nuevo validado.
"""
from django.db import models
from django.db.models import Q


class VersionPadronRuc(models.Model):
    CARGANDO, ACTIVA, RETIRADA, FALLIDA = 'CARGANDO', 'ACTIVA', 'RETIRADA', 'FALLIDA'
    ESTADOS = ((CARGANDO, 'Cargando'), (ACTIVA, 'Activa'), (RETIRADA, 'Retirada'), (FALLIDA, 'Fallida'))

    estado = models.CharField(max_length=10, choices=ESTADOS, default=CARGANDO)
    fuente = models.CharField(max_length=200)                  # URL oficial de la que proviene
    archivo = models.CharField(max_length=255)                 # nombre del ZIP importado (sin ruta)
    archivo_interno = models.CharField(max_length=255)         # TXT dentro del ZIP
    sha256 = models.CharField(max_length=64)                   # huella del ZIP importado
    # Fecha/hora del archivo interno según el ZIP oficial: identifica la publicación del padrón.
    fecha_padron = models.DateTimeField(null=True, blank=True)
    codificacion = models.CharField(max_length=20, blank=True)
    separador = models.CharField(max_length=4, blank=True)
    registros_leidos = models.BigIntegerField(default=0)
    registros_validos = models.BigIntegerField(default=0)      # filas cargadas en esta versión
    registros_omitidos = models.BigIntegerField(default=0)
    registros_duplicados = models.BigIntegerField(default=0)
    iniciado_en = models.DateTimeField(auto_now_add=True)
    finalizado_en = models.DateTimeField(null=True, blank=True)
    activada_en = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'padron_ruc_version'
        constraints = [
            # A lo sumo una versión activa a la vez (la que responden las consultas).
            models.UniqueConstraint(fields=['estado'], condition=Q(estado='ACTIVA'), name='uq_padron_ruc_una_activa'),
        ]

    def __str__(self):
        return f'Padrón RUC v{self.pk} ({self.estado})'

    @property
    def completa(self):
        return self.estado in (self.ACTIVA, self.RETIRADA) and self.finalizado_en is not None


class PadronRuc(models.Model):
    """Una fila del padrón oficial dentro de una versión. Solo datos que trae el padrón."""
    version = models.ForeignKey(VersionPadronRuc, on_delete=models.CASCADE, related_name='filas', db_index=False)
    ruc = models.CharField(max_length=11)
    razon_social = models.CharField(max_length=300)
    estado = models.CharField(max_length=60, blank=True)
    condicion = models.CharField(max_length=60, blank=True)
    ubigeo = models.CharField(max_length=6, null=True, blank=True)
    domicilio_fiscal = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = 'padron_ruc'
        constraints = [
            # El RUC es único DENTRO de cada versión. La restricción crea el índice (version_id, ruc)
            # que usa la consulta `filter(version=activa, ruc=...)`; por eso no se agrega otro índice
            # ni db_index en `ruc` o `version` (sería redundante y encarecería la importación).
            models.UniqueConstraint(fields=['version', 'ruc'], name='uq_padron_ruc_version_ruc'),
        ]

    def __str__(self):
        return f'{self.ruc} {self.razon_social[:40]}'
