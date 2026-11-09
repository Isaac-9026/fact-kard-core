from typing import Any, Optional
from apps.auditoria.models import Auditoria


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
