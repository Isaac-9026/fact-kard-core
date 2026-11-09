from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class Auditoria(models.Model):
    empresa = models.ForeignKey(
        'empresas.Empresa',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='empresa_id',
        related_name='auditorias'
    )
    usuario = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='usuario_id',
        related_name='auditorias'
    )
    accion = models.CharField(max_length=80)
    entidad = models.CharField(max_length=100)
    registro_id = models.BigIntegerField(null=True, blank=True)
    valor_anterior = models.JSONField(null=True, blank=True)
    valor_nuevo = models.JSONField(null=True, blank=True)
    motivo = models.TextField(null=True, blank=True)
    fecha = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = 'auditoria'
        # Bloque 7: listado paginado por empresa en orden -fecha, -id (la tabla solo crece).
        indexes = [
            models.Index(fields=['empresa', '-fecha', '-id'], name='ix_auditoria_empresa_fecha'),
        ]
        verbose_name = 'Auditoría'
        verbose_name_plural = 'Auditorías'

    def __str__(self):
        return f"{self.fecha.strftime('%Y-%m-%d %H:%M:%S')} - {self.entidad} - {self.accion}"
