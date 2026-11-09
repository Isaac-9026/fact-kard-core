"""Bloque 17D — python manage.py estado_padron_ruc: metadatos de la versión activa (nunca filas)."""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.consulta_ruc.models import VersionPadronRuc
from apps.consulta_ruc.padron import estado_padron, versiones_retiradas_con_filas


class Command(BaseCommand):
    help = 'Muestra el estado del Padrón Reducido del RUC importado.'

    def handle(self, *args, **opts):
        e = estado_padron()
        self.stdout.write(f"Proveedor configurado: {getattr(settings, 'CONSULTA_RUC_PROVEEDOR', '') or '(ninguno)'}")
        self.stdout.write(f"Disponible: {'Sí' if e['disponible'] else 'No (ejecute importar_padron_ruc)'}")
        if e['disponible']:
            self.stdout.write(f"Versión: v{e['version']} ({e['archivo']})")
            self.stdout.write(f"Padrón actualizado al: {e['fecha_padron'] or 'desconocido'}")
            self.stdout.write(f"Última importación: {e['fecha_importacion']}")
            self.stdout.write(f"Registros: {e['registros']:,}")
        retenidas = versiones_retiradas_con_filas()
        if retenidas:
            self.stdout.write('Versiones retiradas aún con filas (se limpian con limpiar_padrones_ruc): '
                              + ', '.join(f'v{v.pk}' for v in retenidas))
        fallida = VersionPadronRuc.objects.filter(estado=VersionPadronRuc.FALLIDA).order_by('-id').first()
        if fallida:
            self.stdout.write(f'Última importación fallida: v{fallida.pk} — {fallida.error}')
