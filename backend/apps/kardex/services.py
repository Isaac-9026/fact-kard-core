from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Max, Q, Sum
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import registrar_auditoria
from apps.catalogos.models import TipoOperacion
from apps.empresas.models import ConfigEmpresa, Periodo
from apps.empresas.periodos import validar_fecha_en_periodo_abierto
from apps.kardex.models import (
    Incidencia, Movimiento, Recalculo, RecalculoDetalle, SaldoCppActual,
    StockAlmacen, ValorizacionMovimiento,
)

Q8 = Decimal('0.00000001')
MAX_PASADAS_DEPENDENCIA = 25
Q6 = Decimal('0.000001')
ZERO = Decimal('0.00000000')


def q8(value):
    return Decimal(value).quantize(Q8, rounding=ROUND_HALF_UP)


def cpp(value, quantity):
    return ZERO if quantity == ZERO else (value / quantity).quantize(Q6, rounding=ROUND_HALF_UP)


def siguiente_secuencia_movimiento(*, empresa_id, producto_id, fecha_movimiento, prioridad_dia):
    ultima = Movimiento.objects.filter(
        empresa_id=empresa_id,
        producto_id=producto_id,
        fecha_movimiento=fecha_movimiento,
        prioridad_dia=prioridad_dia,
    ).aggregate(valor=Max('secuencia'))['valor']
    return (ultima or 0) + 1


def hay_movimientos_posteriores(movimiento):
    """Indica si el movimiento quedó antes de otro en el orden oficial del Kardex."""
    posteriores = Movimiento.objects.filter(
        empresa_id=movimiento.empresa_id,
        producto_id=movimiento.producto_id,
    )
    if movimiento.transferencia_id:
        posteriores = posteriores.exclude(transferencia_id=movimiento.transferencia_id)
    return posteriores.filter(
        Q(fecha_movimiento__gt=movimiento.fecha_movimiento)
        | Q(
            fecha_movimiento=movimiento.fecha_movimiento,
            prioridad_dia__gt=movimiento.prioridad_dia,
        )
        | Q(
            fecha_movimiento=movimiento.fecha_movimiento,
            prioridad_dia=movimiento.prioridad_dia,
            secuencia__gt=movimiento.secuencia,
        )
        | Q(
            fecha_movimiento=movimiento.fecha_movimiento,
            prioridad_dia=movimiento.prioridad_dia,
            secuencia=movimiento.secuencia,
            id__gt=movimiento.id,
        )
    ).exists()


def _saldo(empresa_id, producto_id):
    saldo = SaldoCppActual.objects.select_for_update().filter(
        empresa_id=empresa_id, producto_id=producto_id,
    ).first()
    return saldo or SaldoCppActual.objects.create(
        empresa_id=empresa_id, producto_id=producto_id,
        cantidad_total=ZERO, valor_total_pen=ZERO, cpp_pen=ZERO,
    )


def _stock(empresa_id, almacen_id, producto_id):
    stock = StockAlmacen.objects.select_for_update().filter(
        empresa_id=empresa_id, almacen_id=almacen_id, producto_id=producto_id,
    ).first()
    return stock or StockAlmacen.objects.create(
        empresa_id=empresa_id, almacen_id=almacen_id,
        producto_id=producto_id, cantidad_actual=ZERO,
    )


def _incidencia(**kwargs):
    tipo = kwargs['tipo']
    filtros = {key: kwargs.get(key) for key in ('empresa_id', 'periodo_id', 'producto_id', 'movimiento_id')}
    filtros.update(tipo=tipo, estado='PENDIENTE')
    return Incidencia.objects.get_or_create(
        **filtros,
        defaults={
            'severidad': kwargs.get('severidad', 'ERROR'),
            'bloquea_cierre': True,
            'descripcion': kwargs['descripcion'],
            'detalle': kwargs.get('detalle'),
            'documento_id': kwargs.get('documento_id'),
            'documento_detalle_id': kwargs.get('documento_detalle_id'),
        },
    )[0]


def _estado_previo(movimiento):
    """(cantidad, valor) de empresa tras el movimiento inmediatamente anterior en el orden oficial."""
    f, p, sec = movimiento.fecha_movimiento, movimiento.prioridad_dia, movimiento.secuencia
    anterior = Movimiento.objects.filter(
        empresa_id=movimiento.empresa_id, producto_id=movimiento.producto_id, valorizacion__isnull=False,
    ).filter(
        Q(fecha_movimiento__lt=f)
        | Q(fecha_movimiento=f, prioridad_dia__lt=p)
        | Q(fecha_movimiento=f, prioridad_dia=p, secuencia__lt=sec)
        | Q(fecha_movimiento=f, prioridad_dia=p, secuencia=sec, id__lt=movimiento.id)
    ).select_related('valorizacion').order_by('-fecha_movimiento', '-prioridad_dia', '-secuencia', '-id').first()
    if anterior is None:
        return ZERO, ZERO
    return anterior.valorizacion.saldo_cantidad_empresa, anterior.valorizacion.saldo_valor_empresa


def _residuo(saldo, movimiento, periodo):
    if saldo.cantidad_total != ZERO or saldo.valor_total_pen == ZERO:
        return
    tolerancia = ConfigEmpresa.objects.filter(empresa_id=saldo.empresa_id).values_list(
        'tolerancia_residuo_pen', flat=True,
    ).first() or Decimal('0.05000000')
    if abs(saldo.valor_total_pen) > tolerancia:
        _incidencia(
            empresa_id=saldo.empresa_id, periodo_id=periodo.id, producto_id=saldo.producto_id,
            movimiento_id=movimiento.id, tipo='RESIDUO_VALORIZACION',
            descripcion='El residuo de valorización supera la tolerancia configurada.',
            detalle={'residuo': str(saldo.valor_total_pen), 'tolerancia': str(tolerancia)},
        )
        saldo.cpp_pen = ZERO
        return
    tipo = TipoOperacion.objects.get(codigo_interno='RESIDUO_AUTOMATICO')
    ajuste = Movimiento.objects.create(
        empresa_id=saldo.empresa_id, producto_id=saldo.producto_id,
        almacen_id=movimiento.almacen_id, periodo=periodo, tipo_operacion=tipo,
        fecha_movimiento=movimiento.fecha_movimiento, prioridad_dia=3,
        # Bloque 4: secuencia determinista tras los ajustes ya registrados ese día (antes
        # quedaba en 0 y se adelantaba a ellos). Mismo criterio que _crear_residuo_en_recalculo.
        secuencia=siguiente_secuencia_movimiento(
            empresa_id=saldo.empresa_id, producto_id=saldo.producto_id,
            fecha_movimiento=movimiento.fecha_movimiento, prioridad_dia=3,
        ),
        naturaleza='AJUSTE_VALOR', cantidad_base=ZERO,
        valor_ajuste_pen=-saldo.valor_total_pen, generado_por_motor=True,
        creado_por_id=movimiento.creado_por_id,
    )
    # CON-014: el residuo queda ordenado (prioridad 3) antes de la salida que lo originó;
    # su saldo es el estado en SU posición + el ajuste, para que el Kardex sea continuo.
    pos_cant, pos_valor = _estado_previo(ajuste)
    pos_valor = q8(pos_valor - saldo.valor_total_pen)
    ValorizacionMovimiento.objects.create(
        movimiento=ajuste, costo_unitario_pen=ZERO,
        valor_movimiento_pen=-saldo.valor_total_pen,
        saldo_cantidad_empresa=pos_cant, saldo_valor_empresa=pos_valor, cpp_empresa=cpp(pos_valor, pos_cant),
    )
    saldo.valor_total_pen = ZERO
    saldo.cpp_pen = ZERO
    saldo.ultimo_movimiento = ajuste


@transaction.atomic
def aplicar_movimiento(*, empresa_id, producto_id, almacen_id, periodo, tipo_operacion,
                       fecha, cantidad, usuario_id, costo_unitario=None, valor_ajuste=None,
                       documento_detalle=None, movimiento_origen=None, es_extorno=False,
                       movimiento_extornado=None):
    cantidad = q8(cantidad)
    saldo = _saldo(empresa_id, producto_id)
    stock = _stock(empresa_id, almacen_id, producto_id)
    naturaleza = tipo_operacion.naturaleza
    costo = q8(costo_unitario if costo_unitario is not None else (saldo.cpp_pen or ZERO))
    valor = q8(valor_ajuste if naturaleza == 'AJUSTE_VALOR' else cantidad * costo)
    if naturaleza == 'SALIDA':
        if stock.cantidad_actual < cantidad or saldo.cantidad_total < cantidad:
            raise ValidationError({'stock': 'Stock insuficiente para confirmar el movimiento.'})
        stock.cantidad_actual = q8(stock.cantidad_actual - cantidad)
        saldo.cantidad_total = q8(saldo.cantidad_total - cantidad)
        saldo.valor_total_pen = q8(saldo.valor_total_pen - valor)
        prioridad = 4
    elif naturaleza == 'ENTRADA':
        stock.cantidad_actual = q8(stock.cantidad_actual + cantidad)
        saldo.cantidad_total = q8(saldo.cantidad_total + cantidad)
        saldo.valor_total_pen = q8(saldo.valor_total_pen + valor)
        prioridad = 2
    else:
        saldo.valor_total_pen = q8(saldo.valor_total_pen + valor)
        prioridad = 3
    saldo.cpp_pen = cpp(saldo.valor_total_pen, saldo.cantidad_total)
    secuencia = siguiente_secuencia_movimiento(
        empresa_id=empresa_id,
        producto_id=producto_id,
        fecha_movimiento=fecha,
        prioridad_dia=prioridad,
    )
    movimiento = Movimiento.objects.create(
        empresa_id=empresa_id, producto_id=producto_id, almacen_id=almacen_id,
        periodo=periodo, documento_detalle=documento_detalle,
        movimiento_origen=movimiento_origen, movimiento_extornado=movimiento_extornado,
        tipo_operacion=tipo_operacion, fecha_movimiento=fecha, prioridad_dia=prioridad,
        secuencia=secuencia, naturaleza=naturaleza, cantidad_base=cantidad,
        valor_ajuste_pen=valor if naturaleza == 'AJUSTE_VALOR' else None,
        es_extorno=es_extorno, creado_por_id=usuario_id,
    )
    saldo.ultimo_movimiento = movimiento
    # CON-005: en un movimiento retroactivo el saldo actual no corresponde a su posición
    # cronológica; el residuo lo evalúa el recálculo que se ejecuta a continuación.
    tiene_posteriores = hay_movimientos_posteriores(movimiento)
    if not tiene_posteriores:
        _residuo(saldo, movimiento, periodo)
    if saldo.valor_total_pen < ZERO:
        _incidencia(
            empresa_id=empresa_id, periodo_id=periodo.id, producto_id=producto_id,
            movimiento_id=movimiento.id, tipo='VALOR_INVENTARIO_NEGATIVO',
            descripcion='El valor del inventario resultó negativo.',
            detalle={'valor': str(saldo.valor_total_pen)},
        )
    saldo.save(update_fields=['cantidad_total', 'valor_total_pen', 'cpp_pen', 'ultimo_movimiento', 'actualizado_en'])
    stock.save(update_fields=['cantidad_actual', 'actualizado_en'])
    ValorizacionMovimiento.objects.create(
        movimiento=movimiento, costo_unitario_pen=costo,
        valor_movimiento_pen=valor, saldo_cantidad_empresa=saldo.cantidad_total,
        saldo_valor_empresa=saldo.valor_total_pen, cpp_empresa=saldo.cpp_pen,
    )
    if tiene_posteriores:
        ejecutar_recalculo_producto(
            empresa_id=empresa_id,
            producto_id=producto_id,
            fecha_desde=fecha,
            usuario_id=usuario_id,
        )
    return movimiento


def _crear_residuo_en_recalculo(*, movimiento, tipo, importe, usuario_id, estado_posicion=(ZERO, ZERO)):
    """Ajuste RESIDUO_AUTOMATICO nuevo surgido en un recálculo (mismo criterio que _residuo)."""
    secuencia = siguiente_secuencia_movimiento(
        empresa_id=movimiento.empresa_id, producto_id=movimiento.producto_id,
        fecha_movimiento=movimiento.fecha_movimiento, prioridad_dia=3,
    )
    ajuste = Movimiento.objects.create(
        empresa_id=movimiento.empresa_id, producto_id=movimiento.producto_id,
        almacen_id=movimiento.almacen_id, periodo_id=movimiento.periodo_id, tipo_operacion=tipo,
        fecha_movimiento=movimiento.fecha_movimiento, prioridad_dia=3, secuencia=secuencia,
        naturaleza='AJUSTE_VALOR', cantidad_base=ZERO, valor_ajuste_pen=importe,
        generado_por_motor=True, creado_por_id=usuario_id or movimiento.creado_por_id,
    )
    # CON-014: saldo en la posición del residuo (antes de las salidas del día) + ajuste.
    pos_cant, pos_valor = estado_posicion[0], q8(estado_posicion[1] + importe)
    ValorizacionMovimiento.objects.create(
        movimiento=ajuste, costo_unitario_pen=ZERO, valor_movimiento_pen=importe,
        saldo_cantidad_empresa=pos_cant, saldo_valor_empresa=pos_valor, cpp_empresa=cpp(pos_valor, pos_cant),
    )
    return ajuste


@transaction.atomic
def ejecutar_recalculo_producto(*, empresa_id, producto_id, fecha_desde, usuario_id=None):
    _saldo(empresa_id, producto_id)
    stocks = {}
    movimientos_base = Movimiento.objects.filter(
        empresa_id=empresa_id, producto_id=producto_id,
    ).select_related(
        'tipo_operacion', 'periodo', 'saldo_inicial', 'nota_interna_detalle',
        'movimiento_origen__valorizacion', 'movimiento_extornado__valorizacion',
    ).order_by('fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')

    # Bloque 6: la historia anterior a fecha_desde no se carga en memoria. Solo hace
    # falta su punto de partida: stock por almacén (agregado en SQL) y el saldo de la
    # última valorización. El tramo recalculado y el orden oficial no cambian.
    anteriores = Movimiento.objects.filter(
        empresa_id=empresa_id, producto_id=producto_id, fecha_movimiento__lt=fecha_desde,
    )
    ultimo_anterior = anteriores.select_related('valorizacion').order_by(
        '-fecha_movimiento', '-prioridad_dia', '-secuencia', '-id',
    ).first()
    movimientos_afectados = list(movimientos_base.filter(fecha_movimiento__gte=fecha_desde))

    # C-03: Prohibir recálculo que altere movimientos o comience en períodos cerrados
    periodos_cerrados = set(
        m.periodo for m in movimientos_afectados if m.periodo and m.periodo.estado == 'CERRADO'
    )
    periodo_desde_cerrado = Periodo.objects.filter(
        empresa_id=empresa_id,
        estado='CERRADO',
        fecha_inicio__lte=fecha_desde,
        fecha_fin__gte=fecha_desde,
    ).first()
    if periodo_desde_cerrado:
        periodos_cerrados.add(periodo_desde_cerrado)

    if periodos_cerrados:
        nombres = ", ".join(f"{p.anio}-{p.mes:02d}" for p in sorted(periodos_cerrados, key=lambda p: (p.anio, p.mes)))
        raise ValidationError({
            'recalculo': f"No se puede recalcular porque afectaría los períodos cerrados: {nombres}. Debe reabrir el período oficialmente antes de recalcular."
        })

    version = (Recalculo.objects.filter(empresa_id=empresa_id, producto_id=producto_id).aggregate(
        valor=Max('version'),
    )['valor'] or 0) + 1
    recalculo = Recalculo.objects.create(
        empresa_id=empresa_id, producto_id=producto_id, fecha_desde=fecha_desde,
        version=version, estado='EN_PROCESO', ejecutado_por_id=usuario_id,
    )

    # Los movimientos anteriores solo reconstruyen el punto de partida. Su
    # valorización es historia consolidada y no debe versionarse nuevamente.
    por_almacen = anteriores.values('almacen_id').annotate(
        entradas=Sum('cantidad_base', filter=Q(naturaleza='ENTRADA')),
        salidas=Sum('cantidad_base', filter=Q(naturaleza='SALIDA')),
    )
    for fila in por_almacen:
        stocks[fila['almacen_id']] = q8((fila['entradas'] or ZERO) - (fila['salidas'] or ZERO))

    if ultimo_anterior is not None:
        valorizacion_previa = getattr(ultimo_anterior, 'valorizacion', None)
        if valorizacion_previa is None:
            raise ValidationError({
                'recalculo': 'El último movimiento anterior a fecha_desde no tiene valorización.',
            })
        cantidad = q8(valorizacion_previa.saldo_cantidad_empresa or ZERO)
        valor = q8(valorizacion_previa.saldo_valor_empresa or ZERO)
    else:
        cantidad = ZERO
        valor = ZERO

    # CON-003: extornos presentes en el tramo recalculado, por movimiento extornado.
    extorno_de = {
        m.movimiento_extornado_id: m for m in movimientos_afectados if m.movimiento_extornado_id
    }
    ids_afectados = {m.id for m in movimientos_afectados}

    # CON-005: los RESIDUO_AUTOMATICO del tramo se reevalúan. Su valor se decide en
    # el punto en que la cantidad vuelve a 0 ese mismo día (el ajuste se registra con
    # prioridad 3 y queda ordenado antes de la salida que lo originó).
    tipo_residuo = TipoOperacion.objects.filter(codigo_interno='RESIDUO_AUTOMATICO').first()
    tolerancia = ConfigEmpresa.objects.filter(empresa_id=empresa_id).values_list(
        'tolerancia_residuo_pen', flat=True,
    ).first() or Decimal('0.05000000')

    def es_residuo(m):
        return bool(
            tipo_residuo and m.generado_por_motor and m.naturaleza == 'AJUSTE_VALOR'
            and m.tipo_operacion_id == tipo_residuo.id
        )

    anteriores_val = {m.id: getattr(m, 'valorizacion', None) for m in movimientos_afectados}

    def simular(forzados):
        """
        Recorre el tramo en el orden oficial SIN escribir. Devuelve los resultados y
        las dependencias de costo del mismo día (Bloque 3: una devolución ordenada antes
        que su movimiento origen recibe en `forzados` el costo recalculado del origen).
        """
        cantidad, valor = cantidad_inicial, valor_inicial
        stocks_sim = dict(stocks)
        # CON-004: costo recalculado en ESTA ejecución; prima sobre las valorizaciones
        # precargadas, que quedan obsoletas al actualizarse.
        costos = {}
        dependencias = []
        escrituras = []
        incidencias = []
        residuos_nuevos = []
        residuos_resueltos = {}
        estado_en_residuo = {}
        antes_de_salidas = {}
        residuos_disponibles = {}
        for m in movimientos_afectados:
            if es_residuo(m):
                residuos_disponibles.setdefault(m.fecha_movimiento, []).append(m)

        def costo_de_origen(movimiento, ref_id, ref, cpp_vigente):
            if ref_id in costos:
                return costos[ref_id]
            if ref_id in ids_afectados:
                # Origen del mismo tramo aún no procesado (p. ej. devolución de venta del
                # mismo día: ENTRADA prioridad 2 antes que la SALIDA prioridad 4).
                dependencias.append((movimiento.id, ref_id))
                return forzados.get(movimiento.id, cpp_vigente)
            if ref is not None and hasattr(ref, 'valorizacion'):
                return q8(ref.valorizacion.costo_unitario_pen)
            return None

        def stock_negativo(movimiento):
            incidencias.append(dict(
                empresa_id=empresa_id, periodo_id=movimiento.periodo_id, producto_id=producto_id,
                movimiento_id=movimiento.id, tipo='STOCK_INSUFICIENTE',
                descripcion='El recálculo detectó stock negativo posterior.',
            ))

        for movimiento in movimientos_afectados:
            anterior = anteriores_val[movimiento.id]
            if es_residuo(movimiento):
                if movimiento.id not in residuos_resueltos:
                    estado_en_residuo[movimiento.id] = (cantidad, valor)
                continue
            if movimiento.prioridad_dia >= 4 and movimiento.fecha_movimiento not in antes_de_salidas:
                antes_de_salidas[movimiento.fecha_movimiento] = (cantidad, valor)
            cpp_vigente = cpp(valor, cantidad)
            if movimiento.transferencia_id:
                # Una transferencia solo redistribuye stock entre almacenes; no altera el
                # saldo ni el CPP global de empresa + producto.
                costo = anterior.costo_unitario_pen if anterior else cpp_vigente
                movimiento_valor = q8(movimiento.cantidad_base * costo)
                delta_stock = movimiento.cantidad_base if movimiento.naturaleza == 'ENTRADA' else -movimiento.cantidad_base
                stocks_sim[movimiento.almacen_id] = q8(stocks_sim.get(movimiento.almacen_id, ZERO) + delta_stock)
                if stocks_sim[movimiento.almacen_id] < ZERO:
                    stock_negativo(movimiento)
            elif movimiento.naturaleza == 'ENTRADA':
                if movimiento.saldo_inicial_id and movimiento.saldo_inicial:
                    movimiento_valor = q8(movimiento.saldo_inicial.valor_pen)
                    costo = cpp(movimiento_valor, movimiento.cantidad_base)
                elif movimiento.movimiento_extornado_id:
                    # CON-003: el extorno sigue al costo recalculado del extornado; si este aún
                    # no se procesó entra al CPP vigente y el extornado tomará este costo.
                    if movimiento.movimiento_extornado_id in costos:
                        costo = costos[movimiento.movimiento_extornado_id]
                    elif movimiento.movimiento_extornado_id in ids_afectados:
                        costo = cpp_vigente
                    else:
                        costo = q8(
                            costo_de_origen(movimiento, movimiento.movimiento_extornado_id,
                                            movimiento.movimiento_extornado, cpp_vigente)
                            or (anterior.costo_unitario_pen if anterior else cpp_vigente)
                        )
                    movimiento_valor = q8(movimiento.cantidad_base * costo)
                elif movimiento.movimiento_origen_id and movimiento.movimiento_origen and hasattr(movimiento.movimiento_origen, 'valorizacion'):
                    # CON-004 / Bloque 3: devolución al costo recalculado del movimiento origen.
                    costo = q8(costo_de_origen(movimiento, movimiento.movimiento_origen_id,
                                               movimiento.movimiento_origen, cpp_vigente))
                    movimiento_valor = q8(movimiento.cantidad_base * costo)
                else:
                    costo = anterior.costo_unitario_pen if anterior else ZERO
                    movimiento_valor = q8(movimiento.cantidad_base * costo)
                cantidad = q8(cantidad + movimiento.cantidad_base)
                valor = q8(valor + movimiento_valor)
                stocks_sim[movimiento.almacen_id] = stocks_sim.get(movimiento.almacen_id, ZERO) + movimiento.cantidad_base
            elif movimiento.naturaleza == 'SALIDA':
                extorno_previo = extorno_de.get(movimiento.id)
                if movimiento.nota_interna_detalle_id and movimiento.nota_interna_detalle.costo_unitario_pen is not None:
                    costo = q8(movimiento.nota_interna_detalle.costo_unitario_pen)
                elif extorno_previo is not None and extorno_previo.id in costos:
                    # CON-003: salida ya extornada antes en el orden → mismo costo que su extorno.
                    costo = costos[extorno_previo.id]
                elif (movimiento.movimiento_origen_id or movimiento.es_extorno or movimiento.movimiento_extornado_id) and anterior:
                    if movimiento.movimiento_origen_id and movimiento.movimiento_origen and hasattr(movimiento.movimiento_origen, 'valorizacion'):
                        costo = q8(costo_de_origen(movimiento, movimiento.movimiento_origen_id,
                                                   movimiento.movimiento_origen, cpp_vigente))
                    elif movimiento.movimiento_extornado_id and movimiento.movimiento_extornado and hasattr(movimiento.movimiento_extornado, 'valorizacion'):
                        costo = q8(costo_de_origen(movimiento, movimiento.movimiento_extornado_id,
                                                   movimiento.movimiento_extornado, cpp_vigente))
                    else:
                        costo = anterior.costo_unitario_pen
                else:
                    costo = cpp_vigente
                movimiento_valor = q8(movimiento.cantidad_base * costo)
                cantidad = q8(cantidad - movimiento.cantidad_base)
                valor = q8(valor - movimiento_valor)
                stocks_sim[movimiento.almacen_id] = stocks_sim.get(movimiento.almacen_id, ZERO) - movimiento.cantidad_base
                if stocks_sim[movimiento.almacen_id] < ZERO:
                    stock_negativo(movimiento)
            else:
                costo = ZERO; movimiento_valor = movimiento.valor_ajuste_pen or ZERO; valor = q8(valor + movimiento_valor)
            costos[movimiento.id] = q8(costo)

            # CON-005: cantidad 0 con valor ≠ 0 → absorber residuo o incidencia bloqueante.
            if cantidad == ZERO and valor != ZERO:
                if abs(valor) <= tolerancia and tipo_residuo is not None:
                    pendientes = residuos_disponibles.get(movimiento.fecha_movimiento) or []
                    if pendientes:
                        residuos_resueltos[pendientes.pop(0).id] = q8(-valor)
                    else:
                        # Posición del nuevo residuo: tras los ajustes del día, antes de sus salidas.
                        posicion = (antes_de_salidas.get(movimiento.fecha_movimiento, (cantidad, valor))
                                    if movimiento.prioridad_dia >= 4 else (cantidad, valor))
                        residuos_nuevos.append((movimiento, q8(-valor), posicion))
                    valor = ZERO
                else:
                    incidencias.append(dict(
                        empresa_id=empresa_id, periodo_id=movimiento.periodo_id, producto_id=producto_id,
                        movimiento_id=movimiento.id, tipo='RESIDUO_VALORIZACION',
                        descripcion=(
                            'El residuo de valorización supera la tolerancia configurada.'
                            if tipo_residuo is not None else
                            'Residuo de valorización sin tipo RESIDUO_AUTOMATICO configurado.'
                        ),
                        detalle={'residuo': str(valor), 'tolerancia': str(tolerancia), 'origen': 'RECALCULO'},
                    ))
            escrituras.append((movimiento, anterior, costo, movimiento_valor, cantidad, valor))

        return {
            'cantidad': cantidad, 'valor': valor, 'stocks': stocks_sim, 'costos': costos,
            'dependencias': dependencias, 'escrituras': escrituras, 'incidencias': incidencias,
            'residuos_nuevos': residuos_nuevos, 'residuos_resueltos': residuos_resueltos,
            'estado_en_residuo': estado_en_residuo,
        }

    cantidad_inicial, valor_inicial = cantidad, valor
    # Bloque 3: resolución por dependencia causal. Si una devolución quedó antes que su
    # origen del mismo día, se repite la simulación forzando el costo recalculado del
    # origen hasta que coincidan (punto fijo; converge porque cada pasada acerca el CPP).
    forzados = {}
    for _ in range(MAX_PASADAS_DEPENDENCIA):
        resultado = simular(forzados)
        cambios = {
            dep: resultado['costos'][orig] for dep, orig in resultado['dependencias']
            if resultado['costos'].get(dep) != resultado['costos'].get(orig)
        }
        if not cambios:
            break
        forzados.update(cambios)
    else:
        resultado['incidencias'].append(dict(
            empresa_id=empresa_id, periodo_id=movimientos_afectados[-1].periodo_id, producto_id=producto_id,
            movimiento_id=None, tipo='RECALCULO_DEPENDENCIA_SIN_CONVERGER',
            descripcion='Una devolución del mismo día no alcanzó el costo exacto de su movimiento origen.',
            detalle={'pendientes': {str(k): str(v) for k, v in cambios.items()}},
        ))

    def guardar_valorizacion(movimiento, anterior, costo, movimiento_valor, saldo_cant, saldo_valor):
        nuevo_cpp = cpp(saldo_valor, saldo_cant)
        if not anterior:
            return
        RecalculoDetalle.objects.create(
            recalculo=recalculo, movimiento=movimiento, cpp_anterior=anterior.cpp_empresa,
            cpp_nuevo=nuevo_cpp, valor_anterior=anterior.valor_movimiento_pen,
            valor_nuevo=movimiento_valor, saldo_anterior=anterior.saldo_valor_empresa,
            saldo_nuevo=saldo_valor,
        )
        ValorizacionMovimiento.objects.filter(pk=anterior.pk).update(
            costo_unitario_pen=costo, valor_movimiento_pen=movimiento_valor,
            saldo_cantidad_empresa=saldo_cant, saldo_valor_empresa=saldo_valor,
            cpp_empresa=nuevo_cpp, recalculo=recalculo,
            version_actual=anterior.version_actual + 1,
        )

    # Escrituras: una sola vez, con el resultado convergido.
    for escritura in resultado['escrituras']:
        guardar_valorizacion(*escritura)
    for kwargs in resultado['incidencias']:
        _incidencia(**kwargs)
    for causa, importe, posicion in resultado['residuos_nuevos']:
        _crear_residuo_en_recalculo(movimiento=causa, tipo=tipo_residuo, importe=importe, usuario_id=usuario_id,
                                    estado_posicion=posicion)
    # CON-005: cada RESIDUO_AUTOMATICO queda con el importe vigente o neutralizado (0).
    for movimiento in movimientos_afectados:
        if not es_residuo(movimiento):
            continue
        anterior = anteriores_val[movimiento.id]
        cant_pos, valor_pos = resultado['estado_en_residuo'].get(
            movimiento.id, (resultado['cantidad'], resultado['valor']),
        )
        importe = resultado['residuos_resueltos'].get(movimiento.id, ZERO)
        # CON-014: saldo en la posición del residuo + su importe (continuidad del Kardex).
        guardar_valorizacion(movimiento, anterior, ZERO, importe, cant_pos, q8(valor_pos + importe))
    cantidad, valor = resultado['cantidad'], resultado['valor']
    stocks = resultado['stocks']
    saldo = SaldoCppActual.objects.select_for_update().get(empresa_id=empresa_id, producto_id=producto_id)
    saldo.cantidad_total=cantidad; saldo.valor_total_pen=valor; saldo.cpp_pen=cpp(valor, cantidad)
    ultimo_movimiento = (
        movimientos_afectados[-1] if movimientos_afectados else ultimo_anterior
    )
    saldo.ultimo_movimiento=ultimo_movimiento; saldo.save()
    for almacen_id, cantidad_stock in stocks.items():
        StockAlmacen.objects.update_or_create(
            empresa_id=empresa_id, almacen_id=almacen_id, producto_id=producto_id,
            defaults={'cantidad_actual': q8(cantidad_stock)},
        )
    recalculo.estado='OK'; recalculo.save(update_fields=['estado'])
    registrar_auditoria(empresa_id, usuario_id, 'RECALCULAR', 'RECALCULO', recalculo.id,
                        None, {'producto_id': producto_id, 'version': version})
    return recalculo


def validar_cierre_periodo(*, empresa_id, periodo_id):
    if Incidencia.objects.filter(
        empresa_id=empresa_id, periodo_id=periodo_id, bloquea_cierre=True, estado='PENDIENTE',
    ).exists():
        raise ValidationError({'incidencias': 'El período tiene incidencias pendientes que bloquean el cierre.'})
    return True


def _validar_reglas_documento(documento, empresa_id):
    from apps.documentos.models import Documento
    from apps.documentos.reglas import (
        validar_cantidades_devolucion, validar_documento_origen,
        validar_linea_nota, validar_naturaleza_linea,
    )
    origen = None
    if documento.documento_origen_id:
        origen = Documento.objects.select_for_update().select_related('tipo_comprobante').filter(
            pk=documento.documento_origen_id, empresa_id=empresa_id,
        ).first()
    validar_documento_origen(
        empresa_id=empresa_id, clase=documento.clase, tipo_comprobante=documento.tipo_comprobante,
        tercero_id=documento.tercero_id, ruc_emisor=documento.ruc_emisor,
        moneda_codigo=documento.moneda_codigo_id, fecha_emision=documento.fecha_emision, origen=origen,
    )
    lineas = []
    for detalle in documento.detalles.all():
        validar_naturaleza_linea(
            clase=documento.clase, tipo_comprobante=documento.tipo_comprobante,
            tipo_operacion=detalle.tipo_operacion, linea_num=detalle.linea,
        )
        validar_linea_nota(
            tipo_comprobante=documento.tipo_comprobante, tipo_operacion=detalle.tipo_operacion,
            producto_id=detalle.producto_id, detalle_origen=detalle.detalle_origen,
            origen=origen, linea_num=detalle.linea,
        )
        lineas.append((detalle.linea, detalle.detalle_origen, detalle.tipo_operacion, detalle.cantidad_base))
    if documento.tipo_comprobante.es_nota:
        validar_cantidades_devolucion(lineas, excluir_documento_id=documento.id)


@transaction.atomic
def confirmar_documento_motor(*, documento_id, empresa_id, usuario_id):
    from django.utils import timezone
    from apps.documentos.models import Documento
    documento = Documento.objects.select_for_update(of=('self',)).select_related(
        'periodo', 'tipo_comprobante', 'documento_origen',
    ).prefetch_related('detalles__tipo_operacion', 'detalles__detalle_origen').filter(
        pk=documento_id, empresa_id=empresa_id,
    ).first()
    if documento is None:
        raise ValidationError({'detail': 'El documento no existe o no pertenece a la empresa activa.'})
    if documento.estado != 'BORRADOR':
        raise ValidationError({'estado': 'Solo puede confirmarse un documento BORRADOR.'})
    if documento.estado_revision != 'REVISADO':
        raise ValidationError({'estado_revision': 'El documento debe estar REVISADO.'})
    # CON-007: revalidar reglas de la nota con el origen BLOQUEADO. Orden de bloqueo
    # consistente con la anulación: documento → documento de origen → período.
    _validar_reglas_documento(documento, empresa_id)
    # A-04: Bloquear el período con select_for_update para evitar condición de carrera frente al cierre
    periodo = Periodo.objects.select_for_update().get(id=documento.periodo_id, empresa_id=empresa_id)
    # CON-001: la seguridad no depende de cómo se creó el documento (manual o captura).
    validar_fecha_en_periodo_abierto(
        empresa_id=empresa_id, periodo=periodo, fecha=documento.fecha_emision,
    )
    # CON-006: un documento en moneda extranjera sin TC válido no puede valorizarse en PEN.
    if documento.moneda_codigo_id != 'PEN':
        if documento.moneda_codigo_id != 'USD':
            raise ValidationError({'moneda_codigo': f"La moneda '{documento.moneda_codigo_id}' no está soportada para valorizar."})
        if not documento.monto_tc or documento.monto_tc <= ZERO:
            raise ValidationError({
                'tipo_cambio': 'El documento está en USD y no tiene un tipo de cambio válido. No puede confirmarse.'
            })
    detalles = list(documento.detalles.all())
    # CON-002: toda línea que afecta Kardex necesita producto. Se valida antes de
    # aplicar cualquier movimiento para no dejar documentos confirmados sin stock.
    sin_producto = [d.linea for d in detalles if d.afecta_kardex_aplicado and d.producto_id is None]
    if sin_producto:
        lineas = ', '.join(str(n) for n in sin_producto)
        raise ValidationError({
            'detalles': (
                f'Las líneas {lineas} afectan el Kardex y no tienen producto asignado. '
                'Homologue o asigne el producto antes de confirmar.'
            )
        })
    for detalle in detalles:
        if not detalle.afecta_kardex_aplicado:
            continue
        cantidad = detalle.cantidad_base or ZERO
        costo = detalle.costo_unitario_pen
        origen = None
        if detalle.detalle_origen_id:
            origen = Movimiento.objects.filter(
                empresa_id=empresa_id, documento_detalle_id=detalle.detalle_origen_id,
            ).select_related('valorizacion').order_by('id').first()
            if origen is None:
                raise ValidationError({'detalle_origen': 'No existe movimiento histórico para la línea origen.'})
            costo = origen.valorizacion.costo_unitario_pen
        valor_ajuste = None
        if detalle.tipo_operacion.naturaleza == 'AJUSTE_VALOR':
            # A-05: Multiplicar precio por cantidad si existe e incorporar IGV no recuperable
            if detalle.cantidad_original and detalle.cantidad_original > ZERO:
                valor_base = (detalle.precio_unitario or ZERO) * detalle.cantidad_original
            else:
                valor_base = detalle.precio_unitario or ZERO

            porcentaje_cf = detalle.porcentaje_credito_fiscal_aplicado
            if porcentaje_cf is not None and porcentaje_cf < Decimal('100.0000'):
                porcentaje_no_recup = (Decimal('100.0000') - porcentaje_cf) / Decimal('100.0000')
                igv_no_recuperable = (detalle.igv or ZERO) * porcentaje_no_recup
            else:
                igv_no_recuperable = ZERO

            costo_linea_doc = valor_base + igv_no_recuperable
            monto_tc = documento.monto_tc if (documento.moneda_codigo_id == 'USD' and documento.monto_tc) else Decimal('1')
            importe = q8(costo_linea_doc * monto_tc)
            efecto = getattr(documento.tipo_comprobante, 'efecto_nota', 'NINGUNO')
            valor_ajuste = -abs(importe) if efecto == 'CREDITO' else abs(importe)
        aplicar_movimiento(
            empresa_id=empresa_id, producto_id=detalle.producto_id,
            almacen_id=detalle.almacen_id, periodo=documento.periodo,
            tipo_operacion=detalle.tipo_operacion, fecha=documento.fecha_emision,
            cantidad=cantidad, usuario_id=usuario_id, costo_unitario=costo,
            valor_ajuste=valor_ajuste, documento_detalle=detalle, movimiento_origen=origen,
        )
    documento.estado='CONFIRMADO'; documento.confirmado_por_id=usuario_id; documento.confirmado_en=timezone.now()
    documento.save(update_fields=['estado', 'confirmado_por', 'confirmado_en'])
    registrar_auditoria(empresa_id, usuario_id, 'CONFIRMAR', 'DOCUMENTO', documento.id,
                        {'estado': 'BORRADOR'}, {'estado': 'CONFIRMADO'})
    return documento


# BE-005: tipos explícitos para los movimientos generados por anulación. La Tabla 12
# de SUNAT no tiene un código de "anulación/extorno"; se usa 99 (OTROS) y el reporte
# identifica el extorno y su movimiento/documento original. Nunca se reutiliza otro
# tipo (VENTA, SALDO_INICIAL, …) solo porque comparte naturaleza.
TIPOS_EXTORNO = {
    'ENTRADA': ('EXTORNO_ENTRADA', 'EXTORNO POR ANULACION (ENTRADA)'),
    'SALIDA': ('EXTORNO_SALIDA', 'EXTORNO POR ANULACION (SALIDA)'),
    'AJUSTE_VALOR': ('EXTORNO_AJUSTE_VALOR', 'EXTORNO POR ANULACION (AJUSTE DE VALOR)'),
}
CODIGO_SUNAT_EXTORNO = '99'


def tipo_operacion_extorno(naturaleza):
    codigo, descripcion = TIPOS_EXTORNO[naturaleza]
    tipo, _ = TipoOperacion.objects.get_or_create(
        codigo_interno=codigo,
        defaults={
            'codigo_sunat': CODIGO_SUNAT_EXTORNO, 'descripcion': descripcion, 'naturaleza': naturaleza,
            'es_interna': True, 'afecta_kardex': True, 'origen_requerido': 'MOV_EXTORNADO', 'activo': True,
        },
    )
    if tipo.naturaleza != naturaleza or tipo.origen_requerido != 'MOV_EXTORNADO':
        raise ValidationError({
            'tipo_operacion': (
                f"El tipo '{codigo}' del catálogo no es un extorno de naturaleza {naturaleza}. "
                'Corrija el catálogo de tipos de operación.'
            )
        })
    return tipo


@transaction.atomic
def anular_documento_motor(*, documento_id, empresa_id, usuario_id, motivo):
    from apps.documentos.models import Documento
    documento = Documento.objects.select_for_update(of=('self',)).select_related('periodo').filter(
        pk=documento_id, empresa_id=empresa_id,
    ).first()
    if documento is None:
        raise ValidationError({'detail': 'El documento no existe o no pertenece a la empresa activa.'})
    # CON-008: una segunda anulación no debe generar extornos duplicados.
    if documento.estado == 'ANULADO':
        raise ValidationError({'estado': 'El documento ya se encuentra ANULADO.'})
    # Bloque 23: un comprobante que ya entró al flujo de envío SUNAT no se anula solo internamente.
    from django.conf import settings
    if 'apps.emision_electronica' in settings.INSTALLED_APPS:
        from apps.emision_electronica.coherencia import validar_anulacion_interna
        validar_anulacion_interna(documento)
    # CON-008: con notas CONFIRMADAS vigentes, anular el origen revertiría dos veces lo ya devuelto.
    notas = list(
        Documento.objects.filter(
            empresa_id=empresa_id, documento_origen_id=documento.id, estado='CONFIRMADO',
        ).order_by('id').values_list('serie_normalizada', 'numero_normalizado')
    )
    if notas:
        listado = ', '.join(f'{serie}-{numero}' for serie, numero in notas)
        raise ValidationError({
            'detail': f'Debe anular primero las notas relacionadas confirmadas: {listado}.'
        })
    periodo = Periodo.objects.select_for_update().get(id=documento.periodo_id, empresa_id=empresa_id)
    if periodo.estado != 'ABIERTO':
        _incidencia(empresa_id=empresa_id, periodo_id=documento.periodo_id,
                    tipo='ANULACION_PERIODO_CERRADO', documento_id=documento.id,
                    descripcion='Se intentó anular un documento de período cerrado.')
        raise ValidationError({'periodo': 'No se puede anular directamente en un período CERRADO.'})
    if documento.estado == 'CONFIRMADO':
        # CON-001: los extornos se fechan con fecha_emision; debe seguir dentro del período abierto.
        validar_fecha_en_periodo_abierto(
            empresa_id=empresa_id, periodo=periodo, fecha=documento.fecha_emision,
        )
    if documento.estado == 'CONFIRMADO':
        for original in Movimiento.objects.filter(
            empresa_id=empresa_id, documento_detalle__documento=documento,
        ).select_related('tipo_operacion', 'valorizacion'):
            if original.naturaleza == 'AJUSTE_VALOR':
                tipo = tipo_operacion_extorno('AJUSTE_VALOR')
                monto_ajuste_original = original.valor_ajuste_pen
                if monto_ajuste_original is None and hasattr(original, 'valorizacion'):
                    monto_ajuste_original = original.valorizacion.valor_movimiento_pen
                aplicar_movimiento(
                    empresa_id=empresa_id, producto_id=original.producto_id,
                    almacen_id=original.almacen_id, periodo=documento.periodo,
                    tipo_operacion=tipo, fecha=documento.fecha_emision,
                    cantidad=ZERO, usuario_id=usuario_id,
                    costo_unitario=ZERO,
                    valor_ajuste=-(monto_ajuste_original or ZERO), es_extorno=True,
                    movimiento_extornado=original,
                )
            else:
                tipo = tipo_operacion_extorno('SALIDA' if original.naturaleza == 'ENTRADA' else 'ENTRADA')
                aplicar_movimiento(
                    empresa_id=empresa_id, producto_id=original.producto_id,
                    almacen_id=original.almacen_id, periodo=documento.periodo,
                    tipo_operacion=tipo, fecha=documento.fecha_emision,
                    cantidad=original.cantidad_base, usuario_id=usuario_id,
                    costo_unitario=original.valorizacion.costo_unitario_pen,
                    valor_ajuste=None, es_extorno=True,
                    movimiento_extornado=original,
                )
    documento.estado='ANULADO'; documento.save(update_fields=['estado'])
    registrar_auditoria(empresa_id, usuario_id, 'ANULAR', 'DOCUMENTO', documento.id,
                        {'estado': 'CONFIRMADO'}, {'estado': 'ANULADO'}, motivo)
    return documento
