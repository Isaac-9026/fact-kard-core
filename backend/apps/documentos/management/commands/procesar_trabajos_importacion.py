"""
Management command `procesar_trabajos_importacion` para procesar la cola `ImportacionTrabajo`.

- Recupera trabajos huérfanos en `PROCESANDO` sin heartbeat vigente al arrancar.
- Reclama y procesa trabajos secuencialmente vía `procesar_siguiente_trabajo()`.
- Soporta `--once` para tests/cron y maneja `SIGTERM`/`SIGINT` de forma limpia.
"""
import logging
import signal
import threading
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import InterfaceError, OperationalError, close_old_connections, connection, connections
from django.utils import timezone

from apps.documentos.importacion_worker import (
    procesar_siguiente_trabajo,
    recuperar_trabajos_huerfanos,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Procesa la cola persistente de trabajos de importación Excel y anulación de lotes.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Recupera huérfanos si aplica, procesa como máximo un trabajo en cola y finaliza.',
        )
        parser.add_argument(
            '--intervalo',
            type=int,
            default=2,
            help='Segundos entre sondeos cuando no hay trabajos en cola (por defecto: 2).',
        )
        parser.add_argument(
            '--archivo-vivo',
            default='',
            help='Archivo heartbeat para healthcheck del contenedor tareas.',
        )

    def _actualizar_archivo_vivo(self, ruta_vivo: str) -> None:
        if not ruta_vivo:
            return
        try:
            ruta = Path(ruta_vivo)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(timezone.localtime().strftime('%Y-%m-%d %H:%M:%S\n'), encoding='utf-8')
        except OSError as exc:
            logger.warning('No se pudo escribir heartbeat en %s: %s', ruta_vivo, exc)

    def _registrar_senales(self, detener: threading.Event) -> list[tuple[int, object]]:
        if threading.current_thread() is not threading.main_thread():
            return []
        anteriores = []
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                prev = signal.getsignal(sig)

                def _handler(signum, frame):  # noqa: ARG001
                    detener.set()

                signal.signal(sig, _handler)
                anteriores.append((sig, prev))
            except (ValueError, OSError):
                continue
        return anteriores

    def _restaurar_senales(self, anteriores: list[tuple[int, object]]) -> None:
        for sig, prev in anteriores:
            try:
                signal.signal(sig, prev)
            except (ValueError, OSError):
                continue

    def _refrescar_conexiones(self) -> None:
        # En tests (TestCase) la conexión está dentro de transaction.atomic(); cerrarla rompería la prueba.
        if not connection.in_atomic_block:
            close_old_connections()

    def handle(self, *args, **options):
        once = bool(options['once'])
        intervalo = max(1, int(options['intervalo'] or 2))
        ruta_vivo = (options['archivo_vivo'] or '').strip()

        detener = threading.Event()
        senales = self._registrar_senales(detener)
        try:
            self._actualizar_archivo_vivo(ruta_vivo)
            try:
                self._refrescar_conexiones()
                huerfanos = recuperar_trabajos_huerfanos()
                if huerfanos:
                    self.stdout.write(
                        f'[importaciones] Recuperados al inicio: {huerfanos} trabajo(s) huérfano(s) marcados ERROR.'
                    )
            except (OperationalError, InterfaceError) as exc:
                logger.warning('Error temporal recuperando huérfanos al iniciar: %s', exc)
                connections.close_all()
                if once:
                    raise

            while not detener.is_set():
                self._actualizar_archivo_vivo(ruta_vivo)
                try:
                    self._refrescar_conexiones()
                    trabajo = procesar_siguiente_trabajo()
                except (OperationalError, InterfaceError) as exc:
                    logger.warning('Error temporal de base de datos en worker: %s', exc)
                    connections.close_all()
                    if once:
                        raise
                    detener.wait(timeout=intervalo)
                    continue
                finally:
                    self._refrescar_conexiones()

                if trabajo is not None:
                    self.stdout.write(
                        f'[importaciones] Trabajo #{trabajo.id} ({trabajo.tipo}) -> {trabajo.estado}'
                    )
                    if once:
                        break
                    continue

                if once:
                    break

                detener.wait(timeout=intervalo)
        finally:
            self._restaurar_senales(senales)
