"""
Costo de venta con promedio ponderado del período:
Saldo inicial + Compras − Saldo final − Mermas = Costo de venta.
Solo lectura sobre la valorización del Kardex.
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
METODO = ('Kardex (promedio móvil): Saldo inicial + Compras − Saldo final, ambos saldos valorizados según el Kardex; '
          'se restan las salidas que no son ventas (mermas, consumo, ajustes, transferencias y otros).')
METODO_COMPARACION_MES = 'Promedio ponderado del mes: P.U. = (Saldo inicial + Compras) ÷ unidades disponibles.'
METODO_COMPARACION_RANGO = 'Promedio único del rango: un solo P.U. = (Saldo inicial + Compras del rango) ÷ unidades disponibles.'
METODO_ANUAL = ('Suma mensual del costo según Kardex (promedio móvil): cada mes parte de su saldo inicial según el '
                'Kardex. La comparación suma el promedio ponderado de cada mes.')
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
CLAVES_DESGLOSE = ('ventas', 'devoluciones_venta', 'consumo_retiros', 'ajustes', 'transferencias', 'otros')
# Salidas del inventario que no son ventas: se concilian aparte del costo de venta.
CLAVES_CONCILIACION = ('mermas_desmedros', 'consumo_retiros', 'ajustes', 'transferencias', 'otros')
CLAVES_VENTA = ('ventas', 'devoluciones_venta')
FORMULA = ('Saldo inicial + Compras − Saldo final (Kardex) = Salidas del inventario; '
           '− Salidas que no son ventas = Costo de venta')


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
        'desglose': {clave: [ZERO, ZERO] for clave in (*CLAVES_DESGLOSE, 'mermas_desmedros')},
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
    claves_total = ('si', 'compras', 'disp', 'sf', 'salidas', 'no_atribuibles', 'mermas', 'cv', 'cmp_sf', 'cmp_mermas', 'cmp_cv')
    totales = {c: ZERO for c in claves_total}
    totales['compras_detalle'] = defaultdict(lambda: ZERO)
    totales['conciliacion'] = defaultdict(lambda: ZERO)
    totales['desglose'] = defaultdict(lambda: ZERO)
    for pid in sorted(ids, key=lambda i: (productos[i].codigo_interno, i)):
        p, producto = datos[pid], productos[pid]
        si_cant = q8(p['si_cant'] + p['saldo_inicial_doc'][0])
        si_valor = q8(p['si_valor'] + p['saldo_inicial_doc'][1])
        compras_cant = q8(sum((v[0] for v in p['compras'].values()), ZERO))
        compras_valor = q8(sum((v[1] for v in p['compras'].values()), ZERO))
        disp_cant = q8(si_cant + compras_cant)
        disp_valor = q8(si_valor + compras_valor)
        sf_cant = q8(p['sf_cant'])
        sf_valor = q8(p['sf_valor'])

        # Resultado principal: todo según el Kardex (promedio móvil). Cuadra con el inventario valorizado.
        salidas_cant, salidas_valor = q8(disp_cant - sf_cant), q8(disp_valor - sf_valor)
        conciliacion = {k: (q8(p['desglose'][k][0]), q8(p['desglose'][k][1])) for k in CLAVES_CONCILIACION}
        no_atr_cant = q8(sum((v[0] for v in conciliacion.values()), ZERO))
        no_atr_valor = q8(sum((v[1] for v in conciliacion.values()), ZERO))
        cv_cant, cv_valor = q8(salidas_cant - no_atr_cant), q8(salidas_valor - no_atr_valor)
        desglose = {k: (q8(p['desglose'][k][0]), q8(p['desglose'][k][1])) for k in CLAVES_VENTA}
        merma_cant, merma_valor = conciliacion['mermas_desmedros']

        # Comparación: promedio ponderado del período (sin cambios respecto del método anterior).
        pu = disp_valor / disp_cant if disp_cant > ZERO else None
        if pu is None:
            cmp_sf = sf_valor
        elif sf_cant == disp_cant:
            cmp_sf = disp_valor            # sin salidas: no queda costo ni residuo
        else:
            cmp_sf = q8(sf_cant * pu)
        cmp_mermas = q8(merma_cant * pu) if pu is not None else ZERO
        cmp_cv = q8(disp_valor - cmp_sf - cmp_mermas)

        unidad = next((u for u in producto.unidades.all() if u.es_base), None)
        filas.append({
            'producto': {
                'id': producto.id, 'codigo': producto.codigo_interno, 'descripcion': producto.descripcion,
                'unidad': unidad.unidad_codigo_id if unidad else None,
                'tipo_existencia': producto.tipo_existencia_codigo_id,
            },
            'saldo_inicial': _bloque(si_cant, si_valor),
            'compras': _bloque(compras_cant, compras_valor),
            'disponible': _bloque(disp_cant, disp_valor),
            'saldo_final': _bloque(sf_cant, sf_valor),
            'salidas': _bloque(salidas_cant, salidas_valor),
            'conciliacion': {k: _bloque(*v) for k, v in conciliacion.items()},
            'no_atribuibles': _bloque(no_atr_cant, no_atr_valor),
            'mermas': _bloque(merma_cant, merma_valor),
            'costo_venta': _bloque(cv_cant, cv_valor),
            'costo_promedio': _texto(cv_valor / cv_cant) if cv_cant != ZERO else None,
            'compras_detalle': {k: _bloque(v[0], v[1]) for k, v in p['compras'].items()},
            'desglose': {k: _bloque(*v) for k, v in desglose.items()},
            'diferencia': _texto(cv_valor - sum((v[1] for v in desglose.values()), ZERO)),
            'comparacion': {
                'metodo': METODO_COMPARACION_MES if desde.id == hasta.id else METODO_COMPARACION_RANGO,
                'costo_unitario': _texto(pu) if pu is not None else None,
                'saldo_final': _bloque(sf_cant, cmp_sf, unitario=pu if sf_cant != ZERO else None),
                'mermas': _bloque(merma_cant, cmp_mermas, unitario=pu if merma_cant != ZERO else None),
                'costo_venta': _bloque(q8(disp_cant - sf_cant - merma_cant), cmp_cv, unitario=pu),
            },
            # Comparación − Kardex: positivo si el promedio da más costo que el Kardex.
            'diferencia_metodo': _texto(cmp_cv - cv_valor),
        })
        for clave, valor in (('si', si_valor), ('compras', compras_valor), ('disp', disp_valor), ('sf', sf_valor),
                             ('salidas', salidas_valor), ('no_atribuibles', no_atr_valor), ('mermas', merma_valor),
                             ('cv', cv_valor), ('cmp_sf', cmp_sf), ('cmp_mermas', cmp_mermas), ('cmp_cv', cmp_cv)):
            totales[clave] += valor
        for k, v in p['compras'].items():
            totales['compras_detalle'][k] += v[1]
        for k, v in conciliacion.items():
            totales['conciliacion'][k] += v[1]
        for k, v in desglose.items():
            totales['desglose'][k] += v[1]

    def total(clave):
        return _bloque(ZERO, totales[clave], con_cantidad=False)

    suma_desglose = q8(sum(totales['desglose'].values(), ZERO))
    empresa = Empresa.objects.get(pk=empresa_id)
    return {
        'empresa': {'ruc': empresa.ruc, 'razon_social': empresa.razon_social},
        'periodo_desde': _periodo_dict(desde),
        'periodo_hasta': _periodo_dict(hasta),
        'fecha_inicio': inicio.isoformat(),
        'fecha_fin': fin.isoformat(),
        'moneda': 'PEN',
        'formula': FORMULA,
        'metodo': METODO,
        'metodo_comparacion': METODO_COMPARACION_MES if desde.id == hasta.id else METODO_COMPARACION_RANGO,
        'totales': {
            # Las cantidades no se suman entre productos con unidades distintas.
            'saldo_inicial': total('si'),
            'compras': total('compras'),
            'disponible': total('disp'),
            'saldo_final': total('sf'),
            'salidas': total('salidas'),
            'conciliacion': {k: _texto(totales['conciliacion'][k]) for k in CLAVES_CONCILIACION},
            'no_atribuibles': total('no_atribuibles'),
            'mermas': total('mermas'),
            'costo_venta': total('cv'),
            'compras_detalle': {k: _texto(totales['compras_detalle'][k]) for k in CLAVES_COMPRA},
            'desglose': {k: _texto(totales['desglose'][k]) for k in CLAVES_VENTA},
            'diferencia': _texto(totales['cv'] - suma_desglose),
            'comparacion': {
                'saldo_final': total('cmp_sf'),
                'mermas': total('cmp_mermas'),
                'costo_venta': total('cmp_cv'),
            },
            'diferencia_metodo': _texto(totales['cmp_cv'] - totales['cv']),
        },
        'productos': filas,
    }


COLUMNAS_MENSUALES = ('saldo_inicial', 'compras', 'saldo_final', 'no_atribuibles', 'costo_venta')


def resumen_mensual(reportes):
    """
    Una fila por mes (cada reporte es un mes) y el total, sumando con la precisión de cálculo.
    Lo usan la vista «Por año» y la hoja «Costo de Venta» del Excel, para que muestren lo mismo.
    """
    filas = []
    sumas = {'compras': ZERO, 'no_atribuibles': ZERO, 'costo_venta': ZERO, 'costo_venta_promedio': ZERO,
             'diferencia_metodo': ZERO}
    for reporte in reportes:
        t = reporte['totales']
        fila = {'periodo': reporte['periodo_desde']}
        for clave in COLUMNAS_MENSUALES:
            fila[clave] = Decimal(t[clave]['valor'])
        fila['costo_venta_promedio'] = Decimal(t['comparacion']['costo_venta']['valor'])
        fila['diferencia_metodo'] = Decimal(t['diferencia_metodo'])
        for clave in sumas:
            sumas[clave] += fila[clave]
        filas.append(fila)
    total = dict(sumas)
    if filas:
        total['saldo_inicial'] = filas[0]['saldo_inicial']
        total['saldo_final'] = filas[-1]['saldo_final']
    return filas, total


def generar_costo_ventas_anual(*, empresa_id, anio, producto_id=None):
    """Kardex → Costo de Venta «Por año»: el costo de cada mes del año y su suma (consulta)."""
    if not anio:
        raise ValidationError({'anio': 'Este parámetro es obligatorio.'})
    if producto_id and not Producto.objects.filter(pk=producto_id, empresa_id=empresa_id).exists():
        raise ValidationError({'producto_id': 'El producto no pertenece a la empresa activa.'})
    periodos = list(Periodo.objects.filter(empresa_id=empresa_id, anio=anio).order_by('fecha_inicio', 'orden'))
    if not periodos:
        raise ValidationError({'anio': f'La empresa no tiene períodos en {anio}.'})
    reportes = [generar_costo_ventas(empresa_id=empresa_id, periodo_id=p.id, producto_id=producto_id) for p in periodos]
    filas, total = resumen_mensual(reportes)
    empresa = Empresa.objects.get(pk=empresa_id)

    def textos(fila):
        return {clave: _texto(valor) for clave, valor in fila.items() if clave != 'periodo'}

    return {
        'empresa': {'ruc': empresa.ruc, 'razon_social': empresa.razon_social},
        'anio': anio,
        'producto_id': producto_id,
        'moneda': 'PEN',
        'formula': FORMULA,
        'metodo': METODO_ANUAL,
        'metodo_comparacion': 'Promedio ponderado de cada mes (suma mensual).',
        'meses': [{'periodo': f['periodo'], **textos(f)} for f in filas],
        'total': textos(total),
    }
