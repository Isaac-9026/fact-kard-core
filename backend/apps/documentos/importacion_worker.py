"""
Worker y cola persistente para importaciones masivas y anulaciones de lotes (Paso 3).

- Cola en PostgreSQL (`ImportacionTrabajo`) tomada con `SELECT ... FOR UPDATE SKIP LOCKED`.
- Serialización por empresa con `pg_advisory_xact_lock(NAMESPACE_IMPORTACION, empresa_id)`.
- Transacción contable única (`transaction.atomic()`): el lote/anulación y el estado `COMPLETADO`
  se confirman juntos o se revierten juntos.
- Progreso y heartbeat en Redis (`importacion:progreso:<trabajo_id>`) con fallback seguro.
- Recuperación de trabajos huérfanos en `PROCESANDO` sin heartbeat vigente al iniciar el worker.
"""
import gc
import logging
from datetime import datetime

from django.core.cache import caches
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.documentos.importacion_kardex_confirmar import (
    _almacen,
    anular_lote_importacion,
    confirmar_importacion_kardex,
)
from apps.documentos.importacion_staging import (
    guardar_archivos_staging,
    leer_archivos_staging,
    limpiar_staging,
)
from apps.documentos.models import ImportacionLote, ImportacionTrabajo
from apps.empresas.models import Empresa
from apps.usuarios.models import UsuarioEmpresa

logger = logging.getLogger(__name__)

NAMESPACE_IMPORTACION = 41001
PROGRESO_TTL_SEGUNDOS = 3600
HEARTBEAT_TTL_SEGUNDOS = 120
MENSAJE_HUERFANO = 'Proceso interrumpido por reinicio del servidor; no se aplicaron cambios, puede reintentar.'


def clave_progreso(trabajo_id: int) -> str:
    return f'importacion:progreso:{int(trabajo_id)}'


def _porcentaje_entero(actual: int, total: int) -> int:
    if total <= 0 or actual <= 0:
        return 0
    if actual >= total:
        return 100
    return min(100, (int(actual) * 100) // int(total))


def reportar_progreso(
    trabajo_id: int,
    fase: str,
    actual: int = 0,
    total: int = 0,
    mensaje: str = '',
    *,
    ttl: int = PROGRESO_TTL_SEGUNDOS,
) -> dict:
    """Publica progreso y heartbeat en Redis sin fallar si caché/Redis no responde."""
    actual_int = max(0, int(actual or 0))
    total_int = max(0, int(total or 0))
    payload = {
        'trabajo_id': int(trabajo_id),
        'fase': str(fase)[:40],
        'actual': actual_int,
        'total': total_int,
        'porcentaje': 100 if fase == 'COMPLETADO' else _porcentaje_entero(actual_int, total_int),
        'mensaje': str(mensaje)[:240],
        'heartbeat': timezone.now().isoformat(),
    }
    try:
        caches['default'].set(clave_progreso(trabajo_id), payload, timeout=ttl)
    except Exception as exc:  # noqa: BLE001 - Redis opcional; nunca tumbar el worker
        logger.warning('No se pudo guardar progreso en caché para trabajo #%s: %s', trabajo_id, exc)
    return payload


def leer_progreso(trabajo_id: int) -> dict | None:
    """Lee el progreso desde Redis de forma segura; retorna None si no existe o falla caché."""
    try:
        dato = caches['default'].get(clave_progreso(trabajo_id))
        return dato if isinstance(dato, dict) else None
    except Exception as exc:  # noqa: BLE001 - fallback seguro
        logger.warning('No se pudo leer progreso en caché para trabajo #%s: %s', trabajo_id, exc)
        return None


def _heartbeat_vigente(trabajo_id: int, ahora=None) -> bool:
    progreso = leer_progreso(trabajo_id)
    if not progreso:
        return False
    crudo = progreso.get('heartbeat')
    if not crudo:
        return False
    try:
        marca = datetime.fromisoformat(str(crudo))
    except ValueError:
        return False
    if timezone.is_naive(marca):
        marca = timezone.make_aware(marca, timezone.get_current_timezone())
    ref = ahora or timezone.now()
    edad = (ref - marca).total_seconds()
    return 0 <= edad <= HEARTBEAT_TTL_SEGUNDOS


def progreso_para_trabajo(trabajo: ImportacionTrabajo) -> dict | None:
    """Devuelve progreso en vivo desde Redis cuando está en proceso o resumen coherente con BD."""
    if trabajo.estado == 'PROCESANDO':
        en_redis = leer_progreso(trabajo.id)
        if en_redis:
            return en_redis
        return {
            'trabajo_id': trabajo.id,
            'fase': 'PROCESANDO',
            'actual': 0,
            'total': 0,
            'porcentaje': 0,
            'mensaje': 'Procesando operación...',
            'heartbeat': (trabajo.iniciado_en or timezone.now()).isoformat(),
        }
    if trabajo.estado == 'EN_COLA':
        en_redis = leer_progreso(trabajo.id)
        if en_redis:
            return en_redis
        return {
            'trabajo_id': trabajo.id,
            'fase': 'EN_COLA',
            'actual': 0,
            'total': 0,
            'porcentaje': 0,
            'mensaje': 'En cola esperando procesamiento...',
            'heartbeat': (trabajo.creado_en or timezone.now()).isoformat(),
        }
    if trabajo.estado == 'COMPLETADO':
        resumen = trabajo.resumen_json or {}
        total = int(resumen.get('comprobantes') or resumen.get('comprobantes_anulados') or 1)
        return {
            'trabajo_id': trabajo.id,
            'fase': 'COMPLETADO',
            'actual': total,
            'total': total,
            'porcentaje': 100,
            'mensaje': 'Proceso completado correctamente.',
            'heartbeat': (trabajo.finalizado_en or timezone.now()).isoformat(),
        }
    return {
        'trabajo_id': trabajo.id,
        'fase': 'ERROR',
        'actual': 0,
        'total': 0,
        'porcentaje': 0,
        'mensaje': (trabajo.error_detalle or 'Error en el procesamiento.')[:240],
        'heartbeat': (trabajo.finalizado_en or timezone.now()).isoformat(),
    }


def serializar_trabajo(trabajo: ImportacionTrabajo) -> dict:
    almacen = None
    if trabajo.almacen_id and trabajo.almacen:
        almacen = {
            'id': trabajo.almacen_id,
            'codigo': trabajo.almacen.codigo,
            'nombre': trabajo.almacen.nombre,
        }
    return {
        'id': trabajo.id,
        'trabajo_id': trabajo.id,
        'tipo': trabajo.tipo,
        'estado': trabajo.estado,
        'lote_id': trabajo.lote_id,
        'lote': trabajo.lote_id,
        'almacen': almacen,
        'archivos': [a.get('nombre') for a in (trabajo.archivos_meta_json or []) if isinstance(a, dict)],
        'intentos': trabajo.intentos,
        'resumen': trabajo.resumen_json or {},
        'error_detalle': trabajo.error_detalle or '',
        'progreso': progreso_para_trabajo(trabajo),
        'creado_en': trabajo.creado_en,
        'iniciado_en': trabajo.iniciado_en,
        'finalizado_en': trabajo.finalizado_en,
    }


def adquirir_lock_empresa(empresa_id: int) -> None:
    """Serializa trabajos de la misma empresa dentro de la transacción sin bloquear la fila `Empresa`."""
    if not connection.in_atomic_block:
        raise RuntimeError('adquirir_lock_empresa debe invocarse dentro de transaction.atomic().')
    if connection.vendor != 'postgresql':
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [NAMESPACE_IMPORTACION, int(empresa_id)])


def _formatear_validacion(exc: ValidationError) -> str:
    detalle = getattr(exc, 'detail', exc)
    if isinstance(detalle, dict):
        partes = []
        for campo, valor in detalle.items():
            if campo == 'resumen':
                continue
            valores = valor if isinstance(valor, list) else [valor]
            partes.append(f'{campo}: {" ".join(str(v) for v in valores)}')
        return '; '.join(partes) or 'Error de validación en el trabajo.'
    if isinstance(detalle, list):
        return ' '.join(str(v) for v in detalle)
    return str(detalle)


def _revalidar_permisos_trabajo(trabajo: ImportacionTrabajo) -> None:
    usuario = trabajo.usuario
    if usuario is None or not getattr(usuario, 'activo', False):
        raise ValidationError({'permisos': 'El usuario que solicitó el trabajo no existe o está inactivo.'})
    if not Empresa.objects.filter(pk=trabajo.empresa_id, estado='ACTIVA').exists():
        raise ValidationError({'permisos': 'La empresa está inactiva; no se pueden aplicar movimientos.'})
    if getattr(usuario, 'es_admin_global', False):
        return
    es_admin = UsuarioEmpresa.objects.filter(
        usuario=usuario, empresa_id=trabajo.empresa_id, activo=True, rol='ADMIN',
    ).exists()
    if not es_admin:
        raise ValidationError({'permisos': 'El usuario ya no tiene permisos de Administrador en la empresa.'})


def encolar_confirmacion_importacion(*, empresa_id: int, usuario, archivos, almacen_id=None, proveedores=None) -> ImportacionTrabajo:
    """Valida almacén/archivos, persiste archivos en staging y encola `ImportacionTrabajo`."""
    if not archivos:
        raise ValidationError({'archivos': 'Adjunte al menos un archivo Excel (.xlsx).'})
    almacen = _almacen(empresa_id, almacen_id)
    parametros = {'proveedores': proveedores} if proveedores else {}

    with transaction.atomic():
        trabajo = ImportacionTrabajo.objects.create(
            empresa_id=empresa_id,
            usuario=usuario,
            tipo='CONFIRMAR',
            estado='EN_COLA',
            almacen=almacen,
            parametros_json=parametros,
        )
        try:
            rel_dir, meta = guardar_archivos_staging(trabajo.id, archivos)
            trabajo.staging_dir = rel_dir
            trabajo.archivos_meta_json = meta
            trabajo.save(update_fields=['staging_dir', 'archivos_meta_json'])
        except Exception:
            limpiar_staging(trabajo)
            raise

    reportar_progreso(trabajo.id, 'EN_COLA', 0, 1, 'Importación en cola esperando procesamiento...')
    return trabajo


def encolar_anulacion_lote(*, empresa_id: int, lote_id: int, usuario, motivo: str) -> ImportacionTrabajo:
    """
    Valida motivo, lote y unicidad de anulación activa, creando `ImportacionTrabajo(tipo='ANULAR')`.
    La contraseña ya fue validada en la vista HTTP y nunca se guarda en BD.
    """
    motivo_limpio = (motivo or '').strip()
    if len(motivo_limpio) < 5:
        raise ValidationError({'motivo': 'Indique el motivo de la anulación (mínimo 5 caracteres).'})

    with transaction.atomic():
        lote = (
            ImportacionLote.objects.select_for_update()
            .select_related('almacen')
            .filter(pk=lote_id, empresa_id=empresa_id)
            .first()
        )
        if lote is None:
            raise ValidationError({'lote': 'El lote no existe o no pertenece a la empresa activa.'})
        if lote.estado == 'ANULADO':
            raise ValidationError({'lote': 'El lote ya está anulado.'})
        if ImportacionTrabajo.objects.filter(
            tipo='ANULAR', estado__in=('EN_COLA', 'PROCESANDO'), lote=lote,
        ).exists():
            raise ValidationError({'lote': 'Ya existe una anulación en curso para este lote.'})

        try:
            trabajo = ImportacionTrabajo.objects.create(
                empresa_id=empresa_id,
                usuario=usuario,
                tipo='ANULAR',
                estado='EN_COLA',
                lote=lote,
                almacen=lote.almacen,
                parametros_json={'motivo': motivo_limpio[:500]},
            )
        except IntegrityError:
            raise ValidationError({'lote': 'Ya existe una anulación en curso para este lote.'})

    reportar_progreso(trabajo.id, 'EN_COLA', 0, 1, 'Anulación en cola esperando procesamiento...')
    return trabajo


def recuperar_trabajos_huerfanos() -> int:
    """
    Al iniciar el worker, marca como ERROR todo trabajo quedado en `PROCESANDO` sin heartbeat
    vigente en Redis y limpia su directorio de staging.
    """
    ahora = timezone.now()
    recuperados = 0
    with transaction.atomic():
        candidatos = list(
            ImportacionTrabajo.objects.select_for_update(skip_locked=True)
            .filter(estado='PROCESANDO')
            .order_by('id')
        )
        for trabajo in candidatos:
            if _heartbeat_vigente(trabajo.id, ahora=ahora):
                continue
            trabajo.estado = 'ERROR'
            trabajo.error_detalle = MENSAJE_HUERFANO
            trabajo.finalizado_en = ahora
            trabajo.save(update_fields=['estado', 'error_detalle', 'finalizado_en'])
            limpiar_staging(trabajo)
            reportar_progreso(trabajo.id, 'ERROR', 0, 1, MENSAJE_HUERFANO)
            recuperados += 1
    return recuperados


def _tomar_trabajo_en_cola() -> ImportacionTrabajo | None:
    with transaction.atomic():
        trabajo = (
            ImportacionTrabajo.objects.select_for_update(skip_locked=True)
            .filter(estado='EN_COLA')
            .order_by('creado_en', 'id')
            .first()
        )
        if trabajo is None:
            return None
        trabajo.estado = 'PROCESANDO'
        trabajo.iniciado_en = timezone.now()
        trabajo.intentos = (trabajo.intentos or 0) + 1
        trabajo.error_detalle = ''
        trabajo.save(update_fields=['estado', 'iniciado_en', 'intentos', 'error_detalle'])
        return trabajo


def _construir_callback_progreso(trabajo_id: int):
    import time

    estado = {'fase': None, 'actual': -1, 'ultimo_ts': 0.0}

    def _callback(fase: str, mensaje: str, actual: int = 0, total: int = 0):
        ahora = time.monotonic()
        if (
            fase == estado['fase']
            and fase != 'RECALCULANDO_KARDEX'
            and total > 0
            and actual < total
            and (ahora - estado['ultimo_ts']) < 30.0
        ):
            paso = max(1, total // 25)
            if actual - estado['actual'] < paso:
                return
        estado['fase'] = fase
        estado['actual'] = actual
        estado['ultimo_ts'] = ahora
        reportar_progreso(trabajo_id, fase, actual, total, mensaje)

    return _callback


def _marcar_error(trabajo_id: int, mensaje: str) -> ImportacionTrabajo:
    with transaction.atomic():
        trabajo = ImportacionTrabajo.objects.select_for_update().get(pk=trabajo_id)
        trabajo.estado = 'ERROR'
        trabajo.error_detalle = mensaje
        trabajo.finalizado_en = timezone.now()
        trabajo.save(update_fields=['estado', 'error_detalle', 'finalizado_en'])
    limpiar_staging(trabajo)
    reportar_progreso(trabajo.id, 'ERROR', 0, 1, mensaje)
    return trabajo


def ejecutar_trabajo(trabajo_id: int) -> ImportacionTrabajo:
    """Ejecuta un trabajo reclamado en `PROCESANDO` dentro de una única transacción contable atómica."""
    cabecera = ImportacionTrabajo.objects.filter(pk=trabajo_id).values('empresa_id').first()
    if not cabecera:
        raise ImportacionTrabajo.DoesNotExist(f'ImportacionTrabajo #{trabajo_id} no existe.')

    empresa_id = cabecera['empresa_id']
    on_progreso = _construir_callback_progreso(trabajo_id)
    on_progreso('INICIANDO', 'Iniciando procesamiento...', 0, 1)

    try:
        with transaction.atomic():
            adquirir_lock_empresa(empresa_id)
            trabajo = (
                ImportacionTrabajo.objects.select_for_update(of=('self',))
                .select_related('usuario', 'almacen', 'lote')
                .get(pk=trabajo_id, empresa_id=empresa_id)
            )
            if trabajo.estado != 'PROCESANDO':
                return trabajo

            _revalidar_permisos_trabajo(trabajo)

            if trabajo.tipo == 'CONFIRMAR':
                on_progreso('LEYENDO_ARCHIVOS', 'Cargando archivos desde staging...', 0, 1)
                archivos = leer_archivos_staging(trabajo)
                params = trabajo.parametros_json or {}
                resultado = confirmar_importacion_kardex(
                    empresa_id=trabajo.empresa_id,
                    usuario=trabajo.usuario,
                    archivos=archivos,
                    almacen_id=trabajo.almacen_id,
                    proveedores=params.get('proveedores'),
                    on_progreso=on_progreso,
                )
                trabajo.lote_id = resultado['lote']
            elif trabajo.tipo == 'ANULAR':
                if not trabajo.lote_id:
                    raise ValidationError({'lote': 'El trabajo de anulación no tiene un lote asociado.'})
                params = trabajo.parametros_json or {}
                resultado = anular_lote_importacion(
                    empresa_id=trabajo.empresa_id,
                    lote_id=trabajo.lote_id,
                    usuario=trabajo.usuario,
                    motivo=params.get('motivo', ''),
                    on_progreso=on_progreso,
                )
            else:
                raise ValidationError({'tipo': f'Tipo de trabajo no soportado: {trabajo.tipo}.'})

            trabajo.estado = 'COMPLETADO'
            trabajo.resumen_json = resultado
            trabajo.error_detalle = ''
            trabajo.finalizado_en = timezone.now()
            trabajo.save(update_fields=['estado', 'lote', 'resumen_json', 'error_detalle', 'finalizado_en'])

        limpiar_staging(trabajo)
        total_final = int(resultado.get('comprobantes') or resultado.get('comprobantes_anulados') or 1)
        reportar_progreso(trabajo.id, 'COMPLETADO', total_final, total_final, 'Proceso completado correctamente.')
        return trabajo
    except ValidationError as exc:
        return _marcar_error(trabajo_id, _formatear_validacion(exc))
    except Exception:  # noqa: BLE001 - rollback completo ocurrido; marcar ERROR legible sin exponer trazas
        logger.exception('Error inesperado procesando trabajo de importación #%s', trabajo_id)
        return _marcar_error(
            trabajo_id,
            'Ocurrió un error al procesar la operación; no se aplicaron cambios contables. Puede reintentar.',
        )
    finally:
        gc.collect()


def procesar_siguiente_trabajo() -> ImportacionTrabajo | None:
    """Reclama con `SKIP LOCKED` y procesa un trabajo `EN_COLA`. Devuelve el trabajo o `None`."""
    trabajo = _tomar_trabajo_en_cola()
    if trabajo is None:
        return None
    return ejecutar_trabajo(trabajo.id)
