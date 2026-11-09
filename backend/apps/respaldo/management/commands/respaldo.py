"""
Bloque 24 — `python manage.py respaldo <acción>` (Windows y Linux).

  crear                          respaldo completo (base + artefactos SUNAT + media) + copia externa + retención
  verificar <ruta> [--pg-restore] comprueba manifest, archivos y SHA-256 SIN modificar nada
  retener [--simular]            aplica (o muestra) la política de retención
  restaurar <ruta> --confirmar <nombre> [--base-datos N] [--artefactos DIR] [--media DIR]
                                 restauración controlada (nunca sobrescribe; verificación previa obligatoria)

Códigos de salida: 0 correcto · 1 fallo (respaldo NO creado / verificación o restauración fallida)
· 2 respaldo local correcto pero la copia externa o la retención fallaron.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.respaldo import servicio as s


class Command(BaseCommand):
    help = 'Respaldo, verificación, retención y restauración de FACT-KARD (Bloque 24).'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='accion', required=True)
        crear = sub.add_parser('crear', help='Crea un respaldo completo.')
        crear.add_argument('--destino', help='Directorio de respaldos (por defecto FACT_KARD_BACKUP_DIR).')
        crear.add_argument('--sin-retencion', action='store_true', help='No aplicar la retención después.')
        verificar = sub.add_parser('verificar', help='Verifica un respaldo sin modificar nada.')
        verificar.add_argument('ruta')
        verificar.add_argument('--pg-restore', action='store_true', help='Además, lee el volcado con pg_restore --list.')
        retener = sub.add_parser('retener', help='Aplica la política de retención.')
        retener.add_argument('--destino', help='Directorio de respaldos (por defecto FACT_KARD_BACKUP_DIR).')
        retener.add_argument('--simular', action='store_true', help='Solo muestra qué se eliminaría.')
        restaurar = sub.add_parser('restaurar', help='Restaura un respaldo verificado en destinos explícitos.')
        restaurar.add_argument('ruta')
        restaurar.add_argument('--confirmar', required=True, help='Nombre exacto del respaldo (p. ej. 2026-11-02_023000).')
        restaurar.add_argument('--base-datos', help='Base destino YA creada y vacía.')
        restaurar.add_argument('--artefactos', help='Directorio destino vacío para los artefactos SUNAT.')
        restaurar.add_argument('--media', help='Directorio destino vacío para MEDIA_ROOT.')
        restaurar.add_argument('--permitir-base-actual', action='store_true',
                               help='Permite restaurar sobre la base configurada (solo recuperación total).')

    def handle(self, *args, **o):
        accion = o['accion']
        if accion == 'crear':
            r = s.crear_respaldo(destino=o.get('destino'), aplicar_retencion=not o['sin_retencion'])
            return self._fin(r, f'Respaldo creado: {r.ruta}' if r.ruta else None)
        if accion == 'verificar':
            r = s.verificar_respaldo(o['ruta'], comprobar_dump=o['pg_restore'])
            return self._fin(r, 'Verificación correcta: todos los archivos y SHA-256 coinciden.')
        if accion == 'retener':
            r = s.Resultado()
            s.aplicar_politica_retencion(o.get('destino') or settings.FACT_KARD_BACKUP_DIR, r, simular=o['simular'])
            return self._fin(r, 'Retención aplicada.' if not o['simular'] else 'Simulación de retención.')
        r = s.restaurar_respaldo(o['ruta'], confirmar=o['confirmar'], base_datos=o.get('base_datos'),
                                 artefactos=o.get('artefactos'), media=o.get('media'),
                                 permitir_base_actual=o['permitir_base_actual'])
        return self._fin(r, 'Restauración completada.')

    def _fin(self, r, mensaje_ok):
        for a in r.advertencias:
            self.stdout.write(self.style.WARNING(f'ADVERTENCIA: {a}'))
        for e in r.eliminados:
            self.stdout.write(f'Retención: {e}')
        if r.copia_externa == 'OK':
            self.stdout.write(self.style.SUCCESS('Copia externa: OK (verificada).'))
        for e in r.errores:
            self.stderr.write(self.style.ERROR(f'ERROR: {e}'))
        if r.ok:
            if mensaje_ok:
                self.stdout.write(self.style.SUCCESS(mensaje_ok))
            return
        # 2: el respaldo local está completo, pero la copia externa o la retención fallaron.
        raise SystemExit(2 if r.local_ok else 1)
