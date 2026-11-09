"""
Bloque 17D — python manage.py importar_padron_ruc <ruta/padron_reducido_ruc.zip>

Importa el ZIP oficial descargado MANUALMENTE desde
https://www.sunat.gob.pe/descargaPRR/mrc137_padron_reducido.html como una versión nueva y la
activa solo si la carga termina y se valida. Si falla, el padrón activo anterior sigue vigente.
El ZIP nunca debe guardarse dentro del repositorio.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.consulta_ruc.padron import FUENTE_OFICIAL, LOTE_POR_DEFECTO, ZONA_SUNAT, ErrorImportacion, importar_padron


class Command(BaseCommand):
    help = 'Importa el Padrón Reducido del RUC (ZIP oficial de SUNAT) como nueva versión activa.'

    def add_arguments(self, parser):
        parser.add_argument('zip', help='Ruta al ZIP oficial (p. ej. padron_reducido_ruc.zip).')
        parser.add_argument('--lote', type=int, default=LOTE_POR_DEFECTO, help='Filas por lote (por defecto 20000).')
        parser.add_argument('--encoding', default='auto', help='Codificación del TXT: auto (por defecto: UTF-8 o, si no, cp1252), cp1252, latin-1, utf-8.')
        parser.add_argument('--fuente', default=FUENTE_OFICIAL, help='URL oficial de la que se descargó.')
        parser.add_argument('--minimo', type=int, default=1, help='Mínimo de registros válidos para activar.')
        parser.add_argument('--permitir-reduccion', action='store_true',
                            help='Activar aunque tenga menos de la mitad de registros que la versión activa.')
        parser.add_argument('--sin-limpieza', action='store_true',
                            help='No borrar antes las filas de versiones retiradas hace más de 10 minutos '
                                 '(ver limpiar_padrones_ruc).')

    def handle(self, *args, **opts):
        def progreso(r):
            if opts['verbosity'] >= 2 or r.leidos % 1_000_000 < opts['lote']:
                self.stdout.write(f'  ... {r.leidos:,} filas leídas, {r.validos:,} cargadas')

        self.stdout.write('Importando padrón reducido del RUC (esto puede tardar varios minutos)...')
        try:
            version, r = importar_padron(
                opts['zip'], fuente=opts['fuente'], lote=opts['lote'], codificacion=opts['encoding'],
                minimo=opts['minimo'], proporcion_minima=0 if opts['permitir_reduccion'] else 0.5,
                limpiar_retiradas=not opts['sin_limpieza'], progreso=progreso)
        except ErrorImportacion as exc:
            raise CommandError(f'No se importó el padrón: {exc} El padrón activo (si existe) no cambió.')
        fecha = (timezone.localtime(version.fecha_padron, ZONA_SUNAT).strftime('%d/%m/%Y %H:%M')
                 if version.fecha_padron else 'desconocida')
        self.stdout.write(self.style.SUCCESS('Padrón importado y activado.'))
        self.stdout.write('La versión anterior queda retirada con sus filas unos minutos (consultas en curso); '
                          'luego "limpiar_padrones_ruc" o la próxima importación las borran.')
        for etiqueta, valor in (
            ('Registros leídos', f'{r.leidos:,}'), ('Registros válidos', f'{r.validos:,}'),
            ('Registros omitidos', f'{r.omitidos:,} (incompletos {r.incompletas:,}, RUC inválido {r.ruc_invalidos:,})'),
            ('Duplicados', f'{r.duplicados:,}'), ('Tiempo', f'{r.segundos} s'),
            ('Versión', f'v{version.pk} — archivo {version.archivo_interno} del {fecha} (sha256 {version.sha256[:12]}…)'),
            ('Formato', f'{version.codificacion}, separador {version.separador!r}'),
        ):
            self.stdout.write(f'{etiqueta}: {valor}')
