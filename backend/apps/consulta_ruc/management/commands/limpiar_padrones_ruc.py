"""
Bloque 17D — python manage.py limpiar_padrones_ruc [--retencion-minutos 10]

Borra las filas de las versiones del padrón RETIRADAS hace más de N minutos (por defecto 10),
conservando sus metadatos. Nunca toca la versión ACTIVA ni una retirada dentro del plazo, que puede
estar siendo leída por una consulta en curso. No ejecuta VACUUM FULL: el DELETE no bloquea las
consultas y autovacuum deja el espacio para la próxima importación.
"""
import argparse

from django.core.management.base import BaseCommand

from apps.consulta_ruc.padron import RETENCION_MINUTOS, limpiar_versiones_retiradas, versiones_retiradas_con_filas


def entero_no_negativo(valor):
    """Solo enteros >= 0: un negativo se rechaza (no se convierte a 0) y no se limpia nada."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f'debe ser un entero mayor o igual a 0 (recibido: {valor!r}).') from None
    if numero < 0:
        raise argparse.ArgumentTypeError(f'debe ser un entero mayor o igual a 0 (recibido: {numero}).')
    return numero


class Command(BaseCommand):
    help = 'Borra las filas de versiones retiradas del Padrón Reducido del RUC (nunca la activa).'

    def add_arguments(self, parser):
        parser.add_argument('--retencion-minutos', type=entero_no_negativo, default=RETENCION_MINUTOS,
                            help=f'Minutos (entero >= 0) que se conserva una versión recién retirada '
                                 f'(por defecto {RETENCION_MINUTOS}; 0 = limpieza manual inmediata).')

    def handle(self, *args, **opts):
        limpiadas = limpiar_versiones_retiradas(retencion_minutos=opts['retencion_minutos'])
        if limpiadas:
            self.stdout.write(self.style.SUCCESS(
                'Filas borradas de las versiones retiradas: ' + ', '.join(f'v{i}' for i in limpiadas) + '.'))
        else:
            self.stdout.write('No hay versiones retiradas para limpiar.')
        pendientes = versiones_retiradas_con_filas()
        if pendientes:
            self.stdout.write('Se conservan (dentro del plazo de retención): '
                              + ', '.join(f'v{v.pk}' for v in pendientes) + '.')
