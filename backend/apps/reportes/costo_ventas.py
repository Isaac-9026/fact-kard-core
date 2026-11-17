"""
Costo de venta del período por el método contable de inventarios, con PROMEDIO PONDERADO DEL
PERÍODO (un solo costo unitario para todo el rango, como lo trabaja el dueño):

    Saldo inicial + Compras netas = Disponible (subtotal)
    P.U. promedio = valor disponible ÷ unidades disponibles
    Saldo final   = unidades finales × P.U. promedio
    Costo de venta = Disponible − Saldo final  (= unidades que salieron × P.U. promedio)

Reporte de SOLO LECTURA: no escribe en la base ni toca el motor del Kardex.

- Saldo inicial: valor del inventario según el Kardex al día anterior al primer período del rango
  (último movimiento previo), más los documentos de SALDO INICIAL registrados dentro del rango.
- Compras netas: compras + bonificaciones − devoluciones a proveedor ± notas de crédito/débito de
  compra (ajustes de valor). Una compra anulada (extorno) resta.
- Saldo final: unidades del Kardex al último día del rango, valorizadas al P.U. promedio del período
  (redondeado a céntimos).
- Desglose informativo: las unidades de cada tipo de salida (venta neta de devoluciones, mermas,
  consumo, ajustes, transferencias) × P.U. promedio; el redondeo va a "otros", así su suma es
  exactamente el costo de venta.
- Comparación: el Kardex usa promedio móvil (cambia con cada compra), por eso su saldo final y su
  costo de venta pueden diferir; se informan en `kardex` y `diferencia_metodo`.

Las cantidades están en la unidad base de cada producto. Los importes, en soles (PEN).
"""
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from rest_framework.exceptions import ValidationError

from apps.empresas.models import Empresa, Periodo
from apps.inventario.models import Producto
from apps.kardex.models import Movimiento

ZERO = Decimal('0.00000000')
Q8 = Decimal('0.00000001')
Q2 = Decimal('0.01')
METODO = 'Promedio ponderado del período: P.U. = (Saldo inicial + Compras) ÷ unidades disponibles'

GRUPOS_COMPRA = {
    'COMPRA': 'compras',
    'BONIFICACION': 'bonificaciones',
    'DEVOLUCION_COMPRA': 'devoluciones',
    'NC_DESCUENTO_COMPRA': 'notas_credito_debito',
    'ND_CARGO_COMPRA': 'notas_credito_debito',
}
GRUPOS_DESGLOSE = {
    'VENTA': 'ventas',
    'DEVOLUCION_VENTA': 'devoluciones_venta',
    'MERMA': 'mermas_desmedros',
    'DESMEDRO': 'mermas_desmedros',
    'CONSUMO_INTERNO': 'consumo_retiros',
    'RETIRO': 'consumo_retiros',
    'AJUSTE_INGRESO': 'ajustes',
    'AJUSTE_SALIDA': 'ajustes',
    'AJUSTE_VALOR_MANUAL': 'ajustes',
    'RESIDUO_AUTOMATICO': 'ajustes',
    'TRANSFERENCIA_SALIDA': 'transferencias',
    'TRANSFERENCIA_ENTRADA': 'transferencias',
}
CLAVES_COMPRA = ('compras', 'bonificaciones', 'devoluciones', 'notas_credito_debito')
CLAVES_DESGLOSE = ('ventas', 'devoluciones_venta', 'mermas_desmedros', 'consumo_retiros', 'ajustes',
                   'transferencias', 'otros')


def q8(valor):
    return Decimal(valor or 0).quantize(Q8, rounding=ROUND_HALF_UP)


def q2(valor):
    return Decimal(valor or 0).quantize(Q2, rounding=ROUND_HALF_UP)


def _texto(valor):
    return format(q8(valor), '.8f')


_CALCULAR = object()


def _bloque(cantidad, valor, *, con_cantidad=True, unitario=_CALCULAR):
    cantidad, valor = q8(cantidad), q8(valor)
    if unitario is _CALCULAR:
        unitario = q8(valor / cantidad) if con_cantidad and cantidad != ZERO else None
    elif unitario is not None:
        unitario = q8(unitario)
    return {
        'cantidad': _texto(cantidad) if con_cantidad else None,
        'costo_unitario': _texto(unitario) if unitario is not None else None,
        'valor': _texto(valor),
    }


def _validar_periodos(empresa_id, periodo_id, periodo_hasta_id):
    if not periodo_id:
        raise ValidationError({'periodo_id': 'Este parámetro es obligatorio.'})
    desde = Periodo.objects.filter(pk=periodo_id, empresa_id=empresa_id).first()
    if not desde:
        raise ValidationError({'periodo_id': 'El período no pertenece a la empresa activa.'})
    hasta = desde
    if periodo_hasta_id and periodo_hasta_id != periodo_id:
        hasta = Periodo.objects.filter(pk=periodo_hasta_id, empresa_id=empresa_id).first()
        if not hasta:
            raise ValidationError({'periodo_hasta_id': 'El período no pertenece a la empresa activa.'})
        if (hasta.fecha_inicio, hasta.orden) < (desde.fecha_inicio, desde.orden):
            raise ValidationError({'periodo_hasta_id': 'El período final no puede ser anterior al inicial.'})
    return desde, hasta


def _periodo_dict(periodo):
    return {
        'id': periodo.id, 'anio': periodo.anio, 'mes': periodo.mes, 'estado': periodo.estado,
        'etiqueta': f'{periodo.anio}-{periodo.mes:02d}',
    }


def _tipo_efectivo(movimiento):
    """Un extorno se clasifica con el tipo del movimiento que anula (su signo ya va invertido)."""
    if movimiento.es_extorno and movimiento.movimiento_extornado_id:
        return movimiento.movimiento_extornado.tipo_operacion.codigo_interno
    return movimiento.tipo_operacion.codigo_interno


def _efecto(movimiento):
    """(Δ cantidad, Δ valor) del movimiento sobre el inventario de la empresa."""
    valorizacion = movimiento.valorizacion
    valor = q8(valorizacion.valor_movimiento_pen)
    if movimiento.naturaleza == 'ENTRADA':
        return q8(movimiento.cantidad_base), valor
    if movimiento.naturaleza == 'SALIDA':
        return -q8(movimiento.cantidad_base), -valor
    return ZERO, valor  # AJUSTE_VALOR: el importe ya viene con signo


def _producto_vacio():
    return {
        'si_cant': ZERO, 'si_valor': ZERO, 'sf_cant': ZERO, 'sf_valor': ZERO,
        'compras': {clave: [ZERO, ZERO] for clave in CLAVES_COMPRA},
        'desglose': {clave: [ZERO, ZERO] for clave in CLAVES_DESGLOSE},
        'saldo_inicial_doc': [ZERO, ZERO],
        'con_movimiento': False,
    }


def generar_costo_ventas(*, empresa_id, periodo_id, periodo_hasta_id=None, producto_id=None):
    desde, hasta = _validar_periodos(empresa_id, periodo_id, periodo_hasta_id)
    if producto_id and not Producto.objects.filter(pk=producto_id, empresa_id=empresa_id).exists():
        raise ValidationError({'producto_id': 'El producto no pertenece a la empresa activa.'})
    inicio, fin = desde.fecha_inicio, hasta.fecha_fin
    antes_inicio = inicio - timedelta(days=1)

    movimientos = (
        Movimiento.objects.filter(empresa_id=empresa_id, fecha_movimiento__lte=fin)
        .select_related('valorizacion', 'tipo_operacion', 'movimiento_extornado__tipo_operacion')
        .order_by('producto_id', 'fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')
    )
    if producto_id:
        movimientos = movimientos.filter(producto_id=producto_id)

    datos = defaultdict(_producto_vacio)
    for mov in movimientos.iterator(chunk_size=2000):
        valorizacion = getattr(mov, 'valorizacion', None)
        if valorizacion is None:
            continue
        prod = datos[mov.producto_id]
        cantidad_saldo = q8(valorizacion.saldo_cantidad_empresa)
        valor_saldo = q8(valorizacion.saldo_valor_empresa)
        prod['sf_cant'], prod['sf_valor'] = cantidad_saldo, valor_saldo
        if mov.fecha_movimiento <= antes_inicio:
            prod['si_cant'], prod['si_valor'] = cantidad_saldo, valor_saldo
            continue
        prod['con_movimiento'] = True
        d_cant, d_valor = _efecto(mov)
        tipo = _tipo_efectivo(mov)
        if tipo == 'SALDO_INICIAL':
            destino = prod['saldo_inicial_doc']
            destino[0] += d_cant
            destino[1] += d_valor
        elif tipo in GRUPOS_COMPRA:
            destino = prod['compras'][GRUPOS_COMPRA[tipo]]
            destino[0] += d_cant
            destino[1] += d_valor
        else:
            # Lo que sale del inventario es costo: se registra con el signo invertido.
            destino = prod['desglose'][GRUPOS_DESGLOSE.get(tipo, 'otros')]
            destino[0] -= d_cant
            destino[1] -= d_valor

    ids = [pid for pid, p in datos.items()
           if p['con_movimiento'] or p['si_valor'] != ZERO or p['si_cant'] != ZERO]
    productos = {
        p.id: p for p in Producto.objects.filter(pk__in=ids)
        .select_related('tipo_existencia_codigo').prefetch_related('unidades__unidad_codigo')
    }

    filas = []
    totales = {'si': ZERO, 'compras': ZERO, 'disp': ZERO, 'sf': ZERO, 'cv': ZERO, 'sf_kardex': ZERO,
               'cv_kardex': ZERO, 'compras_detalle': defaultdict(lambda: ZERO),
               'desglose': defaultdict(lambda: ZERO)}
    for pid in sorted(ids, key=lambda i: (productos[i].codigo_interno, i)):
        p, producto = datos[pid], productos[pid]
        si_cant = q8(p['si_cant'] + p['saldo_inicial_doc'][0])
        si_valor = q8(p['si_valor'] + p['saldo_inicial_doc'][1])
        compras_cant = q8(sum((v[0] for v in p['compras'].values()), ZERO))
        compras_valor = q8(sum((v[1] for v in p['compras'].values()), ZERO))
        disp_cant = q8(si_cant + compras_cant)
        disp_valor = q8(si_valor + compras_valor)
        sf_cant = q8(p['sf_cant'])
        sf_kardex = q8(p['sf_valor'])

        # Promedio ponderado del período: un solo P.U. para el saldo final y el costo de venta.
        pu = disp_valor / disp_cant if disp_cant > ZERO else None
        sf_valor = q2(sf_cant * pu) if pu is not None else sf_kardex
        cv_cant = q8(disp_cant - sf_cant)
        cv_valor = q8(disp_valor - sf_valor)
        cv_kardex = q8(disp_valor - sf_kardex)

        desglose = {}
        for clave, (cant, _valor_kardex) in p['desglose'].items():
            desglose[clave] = [q8(cant), q2(cant * pu) if pu is not None else ZERO]
        redondeo = q8(cv_valor - sum((v[1] for v in desglose.values()), ZERO))
        desglose['otros'][1] = q8(desglose['otros'][1] + redondeo)

        unidad = next((u for u in producto.unidades.all() if u.es_base), None)
        filas.append({
            'producto': {
                'id': producto.id, 'codigo': producto.codigo_interno, 'descripcion': producto.descripcion,
                'unidad': unidad.unidad_codigo_id if unidad else None,
                'tipo_existencia': producto.tipo_existencia_codigo_id,
            },
            'saldo_inicial': _bloque(si_cant, si_valor),
            'compras': _bloque(compras_cant, compras_valor),
            'disponible': _bloque(disp_cant, disp_valor, unitario=pu),
            'saldo_final': _bloque(sf_cant, sf_valor, unitario=pu if sf_cant != ZERO else None),
            'costo_venta': _bloque(cv_cant, cv_valor, unitario=pu if cv_cant != ZERO else None),
            'costo_promedio': _texto(pu) if pu is not None else None,
            'compras_detalle': {k: _bloque(v[0], v[1]) for k, v in p['compras'].items()},
            'desglose': {k: _bloque(v[0], v[1], unitario=pu if v[0] != ZERO else None) for k, v in desglose.items()},
            'diferencia': _texto(cv_valor - sum((v[1] for v in desglose.values()), ZERO)),
            'kardex': {
                'saldo_final': _bloque(sf_cant, sf_kardex),
                'costo_venta': _bloque(cv_cant, cv_kardex),
            },
            'diferencia_metodo': _texto(cv_valor - cv_kardex),
        })
        totales['si'] += si_valor
        totales['compras'] += compras_valor
        totales['disp'] += disp_valor
        totales['sf'] += sf_valor
        totales['cv'] += cv_valor
        totales['sf_kardex'] += sf_kardex
        totales['cv_kardex'] += cv_kardex
        for k, v in p['compras'].items():
            totales['compras_detalle'][k] += v[1]
        for k, v in desglose.items():
            totales['desglose'][k] += v[1]

    suma_desglose_total = q8(sum(totales['desglose'].values(), ZERO))
    empresa = Empresa.objects.get(pk=empresa_id)
    return {
        'empresa': {'ruc': empresa.ruc, 'razon_social': empresa.razon_social},
        'periodo_desde': _periodo_dict(desde),
        'periodo_hasta': _periodo_dict(hasta),
        'fecha_inicio': inicio.isoformat(),
        'fecha_fin': fin.isoformat(),
        'moneda': 'PEN',
        'formula': 'Saldo inicial + Compras − Saldo final = Costo de venta',
        'metodo': METODO,
        'totales': {
            # Las cantidades no se suman entre productos con unidades distintas.
            'saldo_inicial': _bloque(ZERO, totales['si'], con_cantidad=False),
            'compras': _bloque(ZERO, totales['compras'], con_cantidad=False),
            'disponible': _bloque(ZERO, totales['disp'], con_cantidad=False),
            'saldo_final': _bloque(ZERO, totales['sf'], con_cantidad=False),
            'costo_venta': _bloque(ZERO, totales['cv'], con_cantidad=False),
            'compras_detalle': {k: _texto(totales['compras_detalle'][k]) for k in CLAVES_COMPRA},
            'desglose': {k: _texto(totales['desglose'][k]) for k in CLAVES_DESGLOSE},
            'diferencia': _texto(totales['cv'] - suma_desglose_total),
            'kardex': {
                'saldo_final': _bloque(ZERO, totales['sf_kardex'], con_cantidad=False),
                'costo_venta': _bloque(ZERO, totales['cv_kardex'], con_cantidad=False),
            },
            'diferencia_metodo': _texto(totales['cv'] - totales['cv_kardex']),
        },
        'productos': filas,
    }
