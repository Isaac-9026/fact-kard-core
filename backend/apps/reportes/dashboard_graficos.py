"""
Datos del dashboard. Solo lectura: ventas sin IGV (las notas de crédito restan), costo de venta
con el mismo cálculo del reporte de costo de venta, compras, margen y saldos CPP actuales.
"""
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q, Sum
from rest_framework.exceptions import ValidationError

from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import Periodo
from apps.inventario.models import Producto
from apps.kardex.models import SaldoCppActual
from apps.reportes.costo_ventas import ZERO, _periodo_dict, _texto, generar_costo_ventas

MESES_MAXIMO = 12
TOP_INVENTARIO = 8
TOP_PARTICIPACION = 5
CIEN = Decimal('100')
UNO = Decimal('1')
Q2 = Decimal('0.01')


def _pct(valor):
    return format(valor.quantize(Q2, rounding=ROUND_HALF_UP), '.2f') if valor is not None else None


def _ratio(parte, total):
    return parte / total * CIEN if total != ZERO else None


def _variacion(actual, anterior):
    if anterior is None or anterior == ZERO:
        return None
    return (actual - anterior) / abs(anterior) * CIEN


def _factor(documento):
    signo = -UNO if documento.tipo_comprobante.efecto_nota == 'CREDITO' else UNO
    tc = documento.monto_tc if documento.moneda_codigo_id != 'PEN' and documento.monto_tc else UNO
    return signo * tc


def _ventas_confirmadas(empresa_id, periodo_id):
    return Documento.objects.filter(
        empresa_id=empresa_id, periodo_id=periodo_id, clase='VENTA', estado='CONFIRMADO',
    ).select_related('tipo_comprobante')


def _ventas_periodo(empresa_id, periodo_id, producto_id=None):
    if producto_id:
        lineas = _lineas_venta(empresa_id, periodo_id).filter(producto_id=producto_id)
        total = sum((_importe(linea) for linea in lineas), ZERO)
        comprobantes = len({ln.documento_id for ln in lineas if not ln.documento.tipo_comprobante.es_nota})
        return total, comprobantes
    total, comprobantes = ZERO, 0
    for doc in _ventas_confirmadas(empresa_id, periodo_id).prefetch_related('detalles'):
        base = doc.subtotal
        if base is None:
            base = sum(((d.precio_unitario or ZERO) * (d.cantidad_original or ZERO) for d in doc.detalles.all()), ZERO)
        total += base * _factor(doc)
        if not doc.tipo_comprobante.es_nota:
            comprobantes += 1
    return total, comprobantes


def _lineas_venta(empresa_id, periodo_id):
    return DocumentoDetalle.objects.filter(
        documento__empresa_id=empresa_id, documento__periodo_id=periodo_id,
        documento__clase='VENTA', documento__estado='CONFIRMADO', producto__isnull=False,
    ).select_related('documento__tipo_comprobante')


def _importe(linea):
    return (linea.precio_unitario or ZERO) * (linea.cantidad_original or ZERO) * _factor(linea.documento)


def _ventas_por_producto(empresa_id, periodo_id):
    ventas = defaultdict(lambda: ZERO)
    for linea in _lineas_venta(empresa_id, periodo_id):
        ventas[linea.producto_id] += _importe(linea)
    return ventas


def _resumen_mes(empresa_id, periodo, producto_id=None, reporte=None):
    reporte = reporte or generar_costo_ventas(empresa_id=empresa_id, periodo_id=periodo.id, producto_id=producto_id)
    totales = reporte['totales']
    ventas, comprobantes = _ventas_periodo(empresa_id, periodo.id, producto_id)
    costo = Decimal(totales['costo_venta']['valor'])
    margen = ventas - costo
    return {
        'periodo': periodo, 'ventas': ventas, 'costo_venta': costo, 'margen': margen,
        'margen_pct': _ratio(margen, ventas), 'compras': Decimal(totales['compras']['valor']),
        'comprobantes': comprobantes,
    }


def _con_actividad():
    return Q(movimientos__isnull=False) | Q(documentos__estado='CONFIRMADO')


def _serie(empresa_id, periodo, meses, reporte_actual, producto_id=None):
    periodos = list(
        Periodo.objects.filter(empresa_id=empresa_id, fecha_inicio__lte=periodo.fecha_inicio)
        .filter(_con_actividad() | Q(pk=periodo.pk))
        .distinct().order_by('-fecha_inicio', '-orden')[:meses]
    )
    return [
        _resumen_mes(empresa_id, p, producto_id, reporte_actual if p.pk == periodo.pk else None)
        for p in reversed(periodos)
    ]


def _productos(reporte, ventas):
    filas = []
    for fila in reporte['productos']:
        producto = fila['producto']
        venta = ventas.get(producto['id'], ZERO)
        costo = Decimal(fila['costo_venta']['valor'])
        if venta == ZERO and costo == ZERO:
            continue
        margen = venta - costo
        filas.append({
            'producto': {'id': producto['id'], 'codigo': producto['codigo'], 'descripcion': producto['descripcion']},
            'unidad': producto.get('unidad'),
            'unidades': fila['costo_venta']['cantidad'],
            'costo_unitario': fila['costo_venta']['costo_unitario'],
            'ventas': venta, 'costo_venta': costo, 'margen': margen, 'margen_pct': _ratio(margen, venta),
        })
    filas.sort(key=lambda f: (-f['ventas'], -f['costo_venta'], f['producto']['id']))
    return filas


def _participacion_producto(producto, ventas):
    propio = ventas.get(producto.id, ZERO)
    total = sum((v for v in ventas.values() if v > ZERO), ZERO)
    if total == ZERO or propio <= ZERO:
        return []
    sectores = [(producto.descripcion, propio)]
    if total - propio > ZERO:
        sectores.append(('Resto de productos', total - propio))
    return [{'nombre': n, 'ventas': _texto(v), 'porcentaje': _pct(_ratio(v, total))} for n, v in sectores]


def _participacion(filas):
    con_ventas = [f for f in filas if f['ventas'] > ZERO]
    total = sum((f['ventas'] for f in con_ventas), ZERO)
    if total == ZERO:
        return []
    top = con_ventas[:TOP_PARTICIPACION]
    sectores = [(f['producto']['descripcion'], f['ventas']) for f in top]
    resto = total - sum((f['ventas'] for f in top), ZERO)
    if resto > ZERO:
        sectores.append(('Otros', resto))
    return [{'nombre': n, 'ventas': _texto(v), 'porcentaje': _pct(_ratio(v, total))} for n, v in sectores]


def _dias_stock(cantidad, vendidas, dias_mes):
    if not vendidas or vendidas <= ZERO or cantidad <= ZERO:
        return None
    return format((cantidad * dias_mes / vendidas).quantize(Decimal('1'), rounding=ROUND_HALF_UP), 'f')


def _inventario(empresa_id, producto_id=None, vendidas=None, dias_mes=None):
    saldos = SaldoCppActual.objects.filter(empresa_id=empresa_id, valor_total_pen__gt=ZERO)
    if producto_id:
        saldos = saldos.filter(producto_id=producto_id)
    total = saldos.aggregate(total=Sum('valor_total_pen'))['total'] or ZERO
    filas = saldos.select_related('producto').order_by('-valor_total_pen', 'producto_id')[:TOP_INVENTARIO]
    return {
        'valor_total': _texto(total),
        'productos_con_stock': saldos.count(),
        'top_productos': [
            {
                'producto': {'id': s.producto_id, 'codigo': s.producto.codigo_interno, 'descripcion': s.producto.descripcion},
                'cantidad': _texto(s.cantidad_total),
                'valor': _texto(s.valor_total_pen),
                'dias_stock': _dias_stock(s.cantidad_total, (vendidas or {}).get(s.producto_id), dias_mes),
            }
            for s in filas
        ],
    }


def _kpi(actual, anterior):
    return {
        'actual': _texto(actual),
        'anterior': _texto(anterior) if anterior is not None else None,
        'variacion_pct': _pct(_variacion(actual, anterior)),
    }


def _mes_texto(m):
    return {
        'periodo': _periodo_dict(m['periodo']), 'ventas': _texto(m['ventas']),
        'costo_venta': _texto(m['costo_venta']), 'margen': _texto(m['margen']),
        'margen_pct': _pct(m['margen_pct']), 'compras': _texto(m['compras']), 'comprobantes': m['comprobantes'],
    }


def _periodo_por_defecto(empresa_id):
    periodos = Periodo.objects.filter(empresa_id=empresa_id).order_by('-fecha_inicio', '-orden')
    return periodos.filter(_con_actividad()).distinct().first() or periodos.first()


def generar_graficos_dashboard(*, empresa_id, periodo_id=None, meses=6, producto_id=None):
    if meses > MESES_MAXIMO:
        raise ValidationError({'meses': f'Debe ser un entero entre 1 y {MESES_MAXIMO}.'})
    if periodo_id:
        periodo = Periodo.objects.filter(pk=periodo_id, empresa_id=empresa_id).first()
        if not periodo:
            raise ValidationError({'periodo_id': 'El período no pertenece a la empresa activa.'})
    else:
        periodo = _periodo_por_defecto(empresa_id)
    producto = None
    if producto_id:
        producto = Producto.objects.filter(pk=producto_id, empresa_id=empresa_id).first()
        if not producto:
            raise ValidationError({'producto_id': 'El producto no pertenece a la empresa activa.'})
    producto_dict = (
        {'id': producto.id, 'codigo': producto.codigo_interno, 'descripcion': producto.descripcion} if producto else None
    )

    inventario = _inventario(empresa_id, producto_id)
    if not periodo:
        return {
            'moneda': 'PEN', 'producto': producto_dict, 'periodo': None, 'kpis': None,
            'serie_mensual': [], 'mejor_mes': None,
            'productos': [], 'participacion': [], 'inventario': inventario,
        }

    reporte = generar_costo_ventas(empresa_id=empresa_id, periodo_id=periodo.id, producto_id=producto_id)
    vendidas = {
        f['producto']['id']: Decimal(f['costo_venta']['cantidad'] or '0') for f in reporte['productos']
    }
    inventario = _inventario(
        empresa_id, producto_id, vendidas, (periodo.fecha_fin - periodo.fecha_inicio).days + 1,
    )
    serie = _serie(empresa_id, periodo, meses, reporte, producto_id)
    actual = serie[-1]
    anterior = serie[-2] if len(serie) > 1 else {}
    con_ventas = [m for m in serie if m['ventas'] > ZERO]
    mejor = max(con_ventas, key=lambda m: m['ventas']) if con_ventas else None
    ventas = _ventas_por_producto(empresa_id, periodo.id)
    productos = _productos(reporte, ventas)

    return {
        'moneda': 'PEN',
        'producto': producto_dict,
        'periodo': _periodo_dict(periodo),
        'kpis': {
            **{c: _kpi(actual[c], anterior.get(c)) for c in ('ventas', 'costo_venta', 'margen', 'compras')},
            'margen_pct': _pct(actual['margen_pct']),
            'comprobantes': actual['comprobantes'],
        },
        'serie_mensual': [_mes_texto(m) for m in serie],
        'mejor_mes': {'periodo': _periodo_dict(mejor['periodo']), 'ventas': _texto(mejor['ventas'])} if mejor else None,
        'productos': [
            {**f, **{c: _texto(f[c]) for c in ('ventas', 'costo_venta', 'margen')}, 'margen_pct': _pct(f['margen_pct'])}
            for f in productos
        ],
        'participacion': _participacion_producto(producto, ventas) if producto else _participacion(productos),
        'inventario': inventario,
    }
