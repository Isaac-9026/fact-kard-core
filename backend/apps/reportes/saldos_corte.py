"""
Bloque 4 — saldos a una fecha de corte (no el estado actual).

Fuente de verdad del valor: el saldo contable de la empresa por producto
(ValorizacionMovimiento.saldo_*_empresa del último movimiento hasta el corte, o el
CierrePeriodoDetalle vigente si el período está cerrado). El motor no guarda un valor
por almacén ni por establecimiento: allí el valor es cantidad × CPP global y la
diferencia de redondeo se asigna de forma determinista (`repartir_valor`), sin crear
ni perder importes y sin inventar costos distintos por almacén.
"""
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from apps.empresas.models import CierrePeriodo, ConfigEmpresa
from apps.kardex.models import Movimiento

ZERO = Decimal('0.00000000')
Q8 = Decimal('0.00000001')


def q8(valor):
    return Decimal(valor or 0).quantize(Q8, rounding=ROUND_HALF_UP)


def repartir_valor(total, partes, cpp, preferida=None):
    """
    Reparte `total` entre `partes` [(clave, cantidad), ...] como cantidad × CPP y asigna la
    diferencia de redondeo a `preferida` (aunque no tenga cantidad, como hace el cierre con
    el establecimiento principal) o, sin preferida, a la última parte.
    La suma de lo repartido es exactamente `total`.
    """
    valores = {clave: q8(cantidad * (cpp or ZERO)) for clave, cantidad in partes}
    diferencia = q8(q8(total) - sum(valores.values(), ZERO))
    if diferencia:
        destino = preferida if preferida is not None else (partes[-1][0] if partes else None)
        if destino is None:
            raise ValueError('No hay dónde asignar la diferencia de redondeo.')
        valores[destino] = q8(valores.get(destino, ZERO) + diferencia)
    return valores


def saldos_al_corte(empresa_id, corte=None, producto_id=None):
    """
    Estado por producto tras el último movimiento con fecha <= corte (todo, si corte es None):
    {producto_id: {'cantidad', 'cpp', 'valor', 'almacenes': {almacen_id: cant},
                   'establecimientos': {estab_id: cant}, 'almacen_estab': {almacen_id: estab_id}}}
    """
    movimientos = Movimiento.objects.filter(empresa_id=empresa_id).select_related('valorizacion', 'almacen')
    if corte is not None:
        movimientos = movimientos.filter(fecha_movimiento__lte=corte)
    if producto_id:
        movimientos = movimientos.filter(producto_id=producto_id)
    estado = {}
    for mov in movimientos.order_by('producto_id', 'fecha_movimiento', 'prioridad_dia', 'secuencia', 'id'):
        prod = estado.setdefault(mov.producto_id, {
            'cantidad': ZERO, 'cpp': ZERO, 'valor': ZERO,
            'almacenes': defaultdict(lambda: ZERO), 'establecimientos': defaultdict(lambda: ZERO),
            'almacen_estab': {},
        })
        signo = 1 if mov.naturaleza == 'ENTRADA' else -1 if mov.naturaleza == 'SALIDA' else 0
        if signo:
            prod['almacenes'][mov.almacen_id] = q8(prod['almacenes'][mov.almacen_id] + signo * mov.cantidad_base)
            estab = mov.almacen.establecimiento_id
            prod['establecimientos'][estab] = q8(prod['establecimientos'][estab] + signo * mov.cantidad_base)
        prod['almacen_estab'].setdefault(mov.almacen_id, mov.almacen.establecimiento_id)
        val = getattr(mov, 'valorizacion', None)
        if val is not None:
            prod['cantidad'] = q8(val.saldo_cantidad_empresa)
            prod['cpp'] = q8(val.cpp_empresa)
            prod['valor'] = q8(val.saldo_valor_empresa)
    return estado


def establecimiento_principal_id(empresa_id):
    return ConfigEmpresa.objects.filter(empresa_id=empresa_id).values_list(
        'establecimiento_principal_id', flat=True,
    ).first()


_SIN_DATO = object()


def valores_por_establecimiento(empresa_id, estado_producto, principal=_SIN_DATO):
    """Valor por establecimiento con la misma regla que el cierre (diferencia al principal)."""
    if principal is _SIN_DATO:
        principal = establecimiento_principal_id(empresa_id)
    partes = sorted((e, c) for e, c in estado_producto['establecimientos'].items() if c != ZERO)
    return repartir_valor(estado_producto['valor'], partes, estado_producto['cpp'], preferida=principal)


def resumen_saldos_al_corte(*, empresa_id, periodo=None, fecha_hasta=None, producto_id=None, almacen_id=None):
    """
    Resumen por producto y almacén al final del rango solicitado.
    Prioridad: 1) cierre vigente del período (si el corte es su fecha fin), 2) saldo
    histórico reconstruido desde los movimientos hasta el corte, 3) estado actual (sin corte).
    """
    from datetime import date

    cortes = [c for c in (
        date.fromisoformat(str(fecha_hasta)) if fecha_hasta else None,
        periodo.fecha_fin if periodo else None,
    ) if c]
    corte = min(cortes) if cortes else None
    estado = saldos_al_corte(empresa_id, corte, producto_id)

    cierre = None
    if periodo is not None and periodo.estado == 'CERRADO' and corte == periodo.fecha_fin:
        cierre = CierrePeriodo.objects.filter(periodo_id=periodo.id, vigente=True).prefetch_related('detalles').first()
    fuente = (f'CIERRE v{cierre.version_calculo}' if cierre else
              f'HISTORICO al {corte.isoformat()}' if corte else 'ACTUAL')

    detalles_cierre = defaultdict(dict)
    if cierre:
        for det in cierre.detalles.all():
            detalles_cierre[det.producto_id][det.establecimiento_id] = det

    filas = []
    for prod_id, prod in estado.items():
        if cierre and prod_id in detalles_cierre:
            dets = detalles_cierre[prod_id]
            por_estab = {e: q8(d.saldo_valor_pen) for e, d in dets.items()}
            cantidad_empresa = q8(sum((q8(d.saldo_cantidad) for d in dets.values()), ZERO))
            valor_empresa = q8(sum(por_estab.values(), ZERO))
            cpp = q8(next(iter(dets.values())).cpp_pen)
        else:
            por_estab = valores_por_establecimiento(empresa_id, prod)
            cantidad_empresa, valor_empresa, cpp = prod['cantidad'], prod['valor'], prod['cpp']
        for estab_id in sorted(set(prod['almacen_estab'].values()) | set(por_estab)):
            almacenes = sorted((a, c) for a, c in prod['almacenes'].items() if prod['almacen_estab'].get(a) == estab_id)
            con_stock = [(a, c) for a, c in almacenes if c != ZERO] or almacenes[-1:]
            valores = repartir_valor(por_estab.get(estab_id, ZERO), con_stock, cpp)
            if not almacenes:
                # Establecimiento principal sin stock que recibe el redondeo (mismo criterio
                # que el cierre): se informa como fila de ajuste, sin almacén.
                almacenes = [(None, ZERO)]
                valores = {None: por_estab.get(estab_id, ZERO)}
            for alm_id, cantidad in almacenes:
                if almacen_id and alm_id != int(almacen_id):
                    continue
                filas.append({
                    'producto_id': prod_id, 'establecimiento_id': estab_id, 'almacen_id': alm_id,
                    'cantidad_almacen': cantidad, 'cpp': cpp, 'valor_almacen': valores.get(alm_id, ZERO),
                    'cantidad_empresa': cantidad_empresa, 'valor_empresa': valor_empresa,
                })
    return {'corte': corte, 'fuente': fuente, 'filas': filas}


def valores_establecimiento_por_movimiento(empresa_id, producto_id, hasta, principal=_SIN_DATO):
    """
    Bloque 5: tras cada movimiento (orden oficial, fecha <= hasta), parte del saldo real
    de la empresa que corresponde a cada establecimiento: {movimiento_id: {estab_id: valor}}.
    Mismo reparto que el cierre (cantidad × CPP global, redondeo al principal). Si la suma
    de cantidades por establecimiento no coincide con la de la empresa (p. ej. entre la
    entrada y la salida de una transferencia del mismo día) no se reparte ese instante.
    """
    if principal is _SIN_DATO:
        principal = establecimiento_principal_id(empresa_id)
    cantidades = defaultdict(lambda: ZERO)
    resultado = {}
    movimientos = Movimiento.objects.filter(
        empresa_id=empresa_id, producto_id=producto_id, fecha_movimiento__lte=hasta,
    ).select_related('valorizacion', 'almacen').order_by('fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')
    for mov in movimientos:
        signo = 1 if mov.naturaleza == 'ENTRADA' else -1 if mov.naturaleza == 'SALIDA' else 0
        if signo:
            estab = mov.almacen.establecimiento_id
            cantidades[estab] = q8(cantidades[estab] + signo * mov.cantidad_base)
        val = getattr(mov, 'valorizacion', None)
        if val is None:
            continue
        partes = sorted((e, c) for e, c in cantidades.items() if c != ZERO)
        if q8(sum((c for _, c in partes), ZERO)) != q8(val.saldo_cantidad_empresa):
            continue
        resultado[mov.id] = repartir_valor(val.saldo_valor_empresa, partes, val.cpp_empresa, preferida=principal)
    return resultado
