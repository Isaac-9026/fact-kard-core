"""
Reglas centrales de fechas contables y períodos (CON-001).

Un documento solo puede afectar el Kardex si su fecha pertenece a un período
ABIERTO de su empresa y ningún período no abierto de la empresa contiene esa fecha.
"""
from datetime import date, datetime

from rest_framework.exceptions import ValidationError

from apps.empresas.models import Periodo


def etiqueta_periodo(periodo) -> str:
    return f'{periodo.anio}-{periodo.mes:02d}'


def parsear_fecha_calendario(valor, campo='fecha_emision') -> date:
    """Convierte 'YYYY-MM-DD' a date. Nunca reemplaza una fecha inválida por 'hoy'."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = (valor or '').strip() if isinstance(valor, str) else ''
    if not texto:
        raise ValidationError({campo: 'La fecha es obligatoria.'})
    try:
        return datetime.strptime(texto, '%Y-%m-%d').date()
    except ValueError:
        raise ValidationError({campo: f"La fecha '{texto}' no es válida. Use el formato AAAA-MM-DD."})


def periodo_abierto_para_fecha(*, empresa_id, fecha, campo='fecha_emision'):
    """
    Devuelve el período ABIERTO que contiene exactamente la fecha. Sin fallback a
    otro período: si la fecha cae en un período cerrado o fuera de todos, rechaza.
    """
    periodos = list(
        Periodo.objects.filter(
            empresa_id=empresa_id, fecha_inicio__lte=fecha, fecha_fin__gte=fecha,
        ).order_by('orden', 'id')
    )
    no_abiertos = [p for p in periodos if p.estado != 'ABIERTO']
    if no_abiertos:
        p = no_abiertos[0]
        raise ValidationError({
            campo: (
                f'La fecha {fecha.isoformat()} pertenece al período {etiqueta_periodo(p)} '
                f'en estado {p.estado}. No se pueden registrar operaciones en él.'
            )
        })
    abiertos = [p for p in periodos if p.estado == 'ABIERTO']
    if not abiertos:
        raise ValidationError({
            campo: f'No existe un período contable ABIERTO que contenga la fecha {fecha.isoformat()}.'
        })
    return abiertos[0]


def validar_fecha_en_periodo_abierto(*, empresa_id, periodo, fecha, campo='fecha_emision'):
    """
    Revalidación defensiva previa a generar movimientos: el período asignado debe
    estar ABIERTO, contener la fecha y no existir otro período no abierto que la contenga.
    """
    if periodo.empresa_id != empresa_id:
        raise ValidationError({'periodo': 'El período no pertenece a la empresa activa.'})
    if periodo.estado != 'ABIERTO':
        raise ValidationError({'periodo': 'El período debe estar ABIERTO.'})
    if not (periodo.fecha_inicio <= fecha <= periodo.fecha_fin):
        raise ValidationError({
            campo: (
                f'La fecha {fecha.isoformat()} no pertenece al período asignado '
                f'{etiqueta_periodo(periodo)} ({periodo.fecha_inicio} al {periodo.fecha_fin}).'
            )
        })
    otro_no_abierto = Periodo.objects.filter(
        empresa_id=empresa_id, fecha_inicio__lte=fecha, fecha_fin__gte=fecha,
    ).exclude(estado='ABIERTO').order_by('orden').first()
    if otro_no_abierto is not None:
        raise ValidationError({
            campo: (
                f'La fecha {fecha.isoformat()} también pertenece al período '
                f'{etiqueta_periodo(otro_no_abierto)} en estado {otro_no_abierto.estado}.'
            )
        })
