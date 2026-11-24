"""
Configuración → Períodos e IGV → «Abrir año».

Crea en una sola operación los meses que faltan de un año (por ejemplo, para importar un Excel
histórico). El Kardex, el IGV y los cierres siguen siendo mensuales: cada mes se crea igual que
con «Nuevo período» (mismo registro y misma auditoría). Los períodos que ya existen, abiertos o
cerrados, no se tocan.
"""
import calendar
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import registrar_auditoria
from apps.empresas.models import Empresa, Periodo, TasaIgvVigencia

ANIO_MINIMO = 2000
NOMBRES_MES = ('Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto',
               'Septiembre', 'Octubre', 'Noviembre', 'Diciembre')


def rango_mes(anio, mes):
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def crear_periodo_mensual(*, empresa_id, usuario_id, anio, mes, fecha_inicio=None, fecha_fin=None, motivo=None):
    """Alta de un período mensual con su auditoría (la usan «Nuevo período» y «Abrir año»)."""
    if fecha_inicio is None or fecha_fin is None:
        fecha_inicio, fecha_fin = rango_mes(anio, mes)
    periodo = Periodo.objects.create(
        empresa_id=empresa_id, anio=anio, mes=mes, orden=anio * 100 + mes,
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, estado='ABIERTO',
    )
    registrar_auditoria(
        empresa_id=empresa_id,
        usuario_id=usuario_id,
        accion='CREAR',
        entidad='periodo',
        registro_id=periodo.id,
        valor_nuevo={
            'anio': periodo.anio,
            'mes': periodo.mes,
            'orden': periodo.orden,
            'fecha_inicio': periodo.fecha_inicio.isoformat(),
            'fecha_fin': periodo.fecha_fin.isoformat(),
            'estado': periodo.estado,
        },
        motivo=motivo or f'Creación de período {periodo.anio}-{periodo.mes:02d}',
    )
    return periodo


def validar_anio(valor):
    maximo = timezone.localdate().year + 1
    try:
        anio = int(valor)
    except (TypeError, ValueError):
        raise ValidationError({'anio': 'Indique un año válido.'})
    if not ANIO_MINIMO <= anio <= maximo:
        raise ValidationError({'anio': f'El año debe estar entre {ANIO_MINIMO} y {maximo}.'})
    return anio


def validar_meses(valor):
    if not isinstance(valor, (list, tuple)) or not valor:
        raise ValidationError({'meses': 'Seleccione al menos un mes.'})
    meses = set()
    for m in valor:
        if isinstance(m, bool):
            raise ValidationError({'meses': 'Los meses deben ser números del 1 al 12.'})
        try:
            numero = int(m)
        except (TypeError, ValueError):
            raise ValidationError({'meses': 'Los meses deben ser números del 1 al 12.'})
        if str(numero) != str(m).strip() or not 1 <= numero <= 12:
            raise ValidationError({'meses': 'Los meses deben ser números del 1 al 12.'})
        meses.add(numero)
    return sorted(meses)


def cobertura_igv(empresa_id, inicio, fin, primera_vigencia=None):
    """
    Días del mes sin vigencia de IGV. Una vigencia rige desde su fecha en adelante, así que solo
    quedan sin cubrir los días anteriores a la primera vigencia registrada.
    """
    if primera_vigencia is None:
        primera_vigencia = (
            TasaIgvVigencia.objects.filter(empresa_id=empresa_id).order_by('vigente_desde')
            .values_list('vigente_desde', flat=True).first()
        )
    total = (fin - inicio).days + 1
    if primera_vigencia is None:
        sin_cobertura = total
    elif primera_vigencia <= inicio:
        sin_cobertura = 0
    else:
        sin_cobertura = min(total, (primera_vigencia - inicio).days)
    return {
        'cubierto': sin_cobertura == 0,
        'dias_sin_cobertura': sin_cobertura,
        'sin_cobertura_hasta': (
            None if sin_cobertura == 0 else (inicio + timedelta(days=sin_cobertura - 1)).isoformat()
        ),
    }


def _mensaje_igv(meses_sin_cobertura, primera_vigencia):
    if not meses_sin_cobertura:
        return None
    lista = ', '.join(meses_sin_cobertura)
    if primera_vigencia is None:
        base = 'La empresa no tiene vigencias de IGV registradas'
    else:
        base = f'La primera vigencia de IGV rige desde {primera_vigencia.strftime("%d/%m/%Y")}'
    return (f'{base}: {lista} tiene(n) días sin cobertura. Configure la vigencia en Configuración → Empresa '
            'antes de importar o registrar comprobantes de esas fechas que la requieran. Puede abrir los meses igual.')


def vista_previa_anio(*, empresa_id, anio):
    anio = validar_anio(anio)
    existentes = {p.mes: p for p in Periodo.objects.filter(empresa_id=empresa_id, anio=anio)}
    primera = (
        TasaIgvVigencia.objects.filter(empresa_id=empresa_id).order_by('vigente_desde')
        .values_list('vigente_desde', flat=True).first()
    )
    meses = []
    sin_cobertura = []
    for mes in range(1, 13):
        inicio, fin = rango_mes(anio, mes)
        periodo = existentes.get(mes)
        igv = cobertura_igv(empresa_id, inicio, fin, primera)
        if periodo is None and not igv['cubierto']:
            sin_cobertura.append(f'{anio}-{mes:02d}')
        meses.append({
            'mes': mes,
            'nombre': NOMBRES_MES[mes - 1],
            'etiqueta': f'{anio}-{mes:02d}',
            'fecha_inicio': (periodo.fecha_inicio if periodo else inicio).isoformat(),
            'fecha_fin': (periodo.fecha_fin if periodo else fin).isoformat(),
            'existe': periodo is not None,
            'periodo_id': periodo.id if periodo else None,
            'estado': periodo.estado if periodo else None,
            'igv': igv,
        })
    return {
        'anio': anio,
        'meses': meses,
        'faltantes': [m['mes'] for m in meses if not m['existe']],
        'primera_vigencia_igv': primera.isoformat() if primera else None,
        'advertencia_igv': _mensaje_igv(sin_cobertura, primera),
    }


def abrir_anio(*, empresa_id, usuario, anio, meses):
    """
    Crea los meses elegidos que faltan. Todo o nada; los existentes se informan y no se modifican.
    El bloqueo de la empresa serializa reintentos y solicitudes simultáneas: nunca hay duplicados.
    """
    anio = validar_anio(anio)
    meses = validar_meses(meses)
    with transaction.atomic():
        Empresa.objects.select_for_update().only('id').get(pk=empresa_id)
        # Meses del año que ya existían (elegidos o no): se informan y no se tocan.
        existentes = set(Periodo.objects.filter(empresa_id=empresa_id, anio=anio).values_list('mes', flat=True))
        creados = []
        for mes in meses:
            if mes in existentes:
                continue
            periodo = crear_periodo_mensual(
                empresa_id=empresa_id, usuario_id=usuario.id, anio=anio, mes=mes,
                motivo=f'Apertura del año {anio}: período {anio}-{mes:02d}',
            )
            creados.append(periodo)
    previa = vista_previa_anio(empresa_id=empresa_id, anio=anio)
    sin_cobertura = [
        f'{anio}-{p.mes:02d}' for p in creados if not previa['meses'][p.mes - 1]['igv']['cubierto']
    ]
    return {
        'anio': anio,
        'creados': [{'id': p.id, 'mes': p.mes, 'etiqueta': f'{anio}-{p.mes:02d}'} for p in creados],
        'existentes': sorted(existentes),
        'total_creados': len(creados),
        'total_existentes': len(existentes),
        'advertencia_igv': _mensaje_igv(
            sin_cobertura,
            date.fromisoformat(previa['primera_vigencia_igv']) if previa['primera_vigencia_igv'] else None,
        ),
    }
