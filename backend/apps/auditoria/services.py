import threading
from contextlib import contextmanager
from typing import Any, Optional

from django.utils import timezone

from apps.auditoria.models import Auditoria

_lote_auditoria = threading.local()


@contextmanager
def buffer_auditoria_lote():
    """
    Acumula inserciones de auditoría dentro de un lote transaccional y las persiste en bloque
    mediante `bulk_create(..., batch_size=500)`. Solo INSERT, nunca UPDATE/DELETE.
    """
    if getattr(_lote_auditoria, 'buffer', None) is not None:
        yield
        return
    _lote_auditoria.buffer = []
    try:
        yield
        registros = _lote_auditoria.buffer
        _lote_auditoria.buffer = None
        if registros:
            Auditoria.objects.bulk_create(registros, batch_size=500)
    finally:
        _lote_auditoria.buffer = None


def registrar_auditoria(
    empresa_id: Optional[int],
    usuario_id: Optional[int],
    accion: str,
    entidad: str,
    registro_id: Optional[int] = None,
    valor_anterior: Optional[Any] = None,
    valor_nuevo: Optional[Any] = None,
    motivo: Optional[str] = None
) -> Auditoria:
    """
    Servicio transversal de auditoría para FACT-KARD.
    Inserta un nuevo registro inmutable en la tabla 'auditoria'.

    REGLA ESTRICTA: Solo realiza INSERT. Cualquier intento de UPDATE o DELETE
    está bloqueado a nivel de base de datos por los triggers trg_auditoria_no_update
    y trg_auditoria_no_delete.
    """
    buffer = getattr(_lote_auditoria, 'buffer', None)
    if buffer is not None:
        registro = Auditoria(
            empresa_id=empresa_id,
            usuario_id=usuario_id,
            accion=accion,
            entidad=entidad,
            registro_id=registro_id,
            valor_anterior=valor_anterior,
            valor_nuevo=valor_nuevo,
            motivo=motivo,
            fecha=timezone.now(),
        )
        buffer.append(registro)
        return registro

    return Auditoria.objects.create(
        empresa_id=empresa_id,
        usuario_id=usuario_id,
        accion=accion,
        entidad=entidad,
        registro_id=registro_id,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        motivo=motivo,
    )
