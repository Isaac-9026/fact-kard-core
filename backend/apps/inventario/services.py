from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import registrar_auditoria
from apps.catalogos.models import TipoOperacion
from apps.inventario.models import NotaInterna, SaldoInicial, Transferencia
from apps.kardex.models import Movimiento, SaldoCppActual, StockAlmacen, ValorizacionMovimiento
from apps.kardex.services import (
    ejecutar_recalculo_producto, hay_movimientos_posteriores,
    siguiente_secuencia_movimiento,
)


OCHO_DECIMALES = Decimal('0.00000001')
SEIS_DECIMALES = Decimal('0.000001')
CERO = Decimal('0.00000000')


def _q8(valor):
    return Decimal(valor).quantize(OCHO_DECIMALES, rounding=ROUND_HALF_UP)


def _cpp(valor, cantidad):
    if cantidad == CERO:
        return CERO
    return (valor / cantidad).quantize(SEIS_DECIMALES, rounding=ROUND_HALF_UP)


def _bloquear_saldo(empresa_id, producto_id):
    saldo = SaldoCppActual.objects.select_for_update().filter(
        empresa_id=empresa_id, producto_id=producto_id,
    ).first()
    if saldo is None:
        saldo = SaldoCppActual.objects.create(
            empresa_id=empresa_id, producto_id=producto_id,
            cantidad_total=CERO, valor_total_pen=CERO, cpp_pen=CERO,
        )
    return saldo


def _bloquear_stock(empresa_id, almacen_id, producto_id):
    stock = StockAlmacen.objects.select_for_update().filter(
        empresa_id=empresa_id, almacen_id=almacen_id, producto_id=producto_id,
    ).first()
    if stock is None:
        stock = StockAlmacen.objects.create(
            empresa_id=empresa_id, almacen_id=almacen_id,
            producto_id=producto_id, cantidad_actual=CERO,
        )
    return stock


def _crear_valorizacion(movimiento, costo, valor, saldo):
    return ValorizacionMovimiento.objects.create(
        movimiento=movimiento,
        costo_unitario_pen=_q8(costo),
        valor_movimiento_pen=_q8(valor),
        saldo_cantidad_empresa=saldo.cantidad_total,
        saldo_valor_empresa=saldo.valor_total_pen,
        cpp_empresa=saldo.cpp_pen,
    )


@transaction.atomic
def confirmar_saldo_inicial(*, saldo_id, empresa_id, usuario):
    saldo_inicial = SaldoInicial.objects.select_for_update().select_related(
        'periodo', 'almacen', 'producto',
    ).filter(empresa_id=empresa_id, pk=saldo_id).first()
    if saldo_inicial is None:
        raise ValidationError({'detail': 'Saldo inicial no encontrado.'})
    if saldo_inicial.estado != 'BORRADOR':
        raise ValidationError({'estado': 'Solo puede confirmarse un saldo inicial BORRADOR.'})
    from apps.empresas.models import Periodo
    periodo = Periodo.objects.select_for_update().get(id=saldo_inicial.periodo_id, empresa_id=empresa_id)
    if periodo.estado != 'ABIERTO':
        raise ValidationError({'periodo': 'El período debe estar ABIERTO.'})

    saldo = _bloquear_saldo(empresa_id, saldo_inicial.producto_id)
    stock = _bloquear_stock(empresa_id, saldo_inicial.almacen_id, saldo_inicial.producto_id)
    saldo.cantidad_total = _q8(saldo.cantidad_total + saldo_inicial.cantidad)
    saldo.valor_total_pen = _q8(saldo.valor_total_pen + saldo_inicial.valor_pen)
    saldo.cpp_pen = _cpp(saldo.valor_total_pen, saldo.cantidad_total)
    stock.cantidad_actual = _q8(stock.cantidad_actual + saldo_inicial.cantidad)

    tipo = TipoOperacion.objects.get(codigo_interno='SALDO_INICIAL')
    movimiento = Movimiento.objects.create(
        empresa_id=empresa_id, producto_id=saldo_inicial.producto_id,
        almacen_id=saldo_inicial.almacen_id, periodo=saldo_inicial.periodo,
        saldo_inicial=saldo_inicial, tipo_operacion=tipo,
        fecha_movimiento=saldo_inicial.periodo.fecha_inicio, prioridad_dia=1,
        secuencia=siguiente_secuencia_movimiento(
            empresa_id=empresa_id,
            producto_id=saldo_inicial.producto_id,
            fecha_movimiento=saldo_inicial.periodo.fecha_inicio,
            prioridad_dia=1,
        ),
        naturaleza='ENTRADA', cantidad_base=saldo_inicial.cantidad,
        creado_por=usuario,
    )
    saldo.ultimo_movimiento = movimiento
    saldo.save(update_fields=['cantidad_total', 'valor_total_pen', 'cpp_pen', 'ultimo_movimiento', 'actualizado_en'])
    stock.save(update_fields=['cantidad_actual', 'actualizado_en'])
    _crear_valorizacion(movimiento, saldo_inicial.cpp_inicial, saldo_inicial.valor_pen, saldo)
    if hay_movimientos_posteriores(movimiento):
        ejecutar_recalculo_producto(
            empresa_id=empresa_id, producto_id=saldo_inicial.producto_id,
            fecha_desde=movimiento.fecha_movimiento, usuario_id=usuario.id,
        )
    saldo_inicial.estado = 'CONFIRMADO'
    saldo_inicial.save(update_fields=['estado'])
    registrar_auditoria(
        empresa_id, usuario.id, 'CONFIRMAR_SALDO_INICIAL', 'SALDO_INICIAL',
        saldo_inicial.id, {'estado': 'BORRADOR'}, {'estado': 'CONFIRMADO'},
    )
    return saldo_inicial


@transaction.atomic
def confirmar_nota_interna(*, nota_id, empresa_id, usuario):
    nota = NotaInterna.objects.select_for_update().select_related(
        'periodo', 'tipo_operacion',
    ).prefetch_related('detalles').filter(empresa_id=empresa_id, pk=nota_id).first()
    if nota is None:
        raise ValidationError({'detail': 'Nota interna no encontrada.'})
    if nota.estado != 'BORRADOR':
        raise ValidationError({'estado': 'Solo puede confirmarse una nota interna BORRADOR.'})
    from apps.empresas.models import Periodo
    periodo = Periodo.objects.select_for_update().get(id=nota.periodo_id, empresa_id=empresa_id)
    if periodo.estado != 'ABIERTO' or not (periodo.fecha_inicio <= nota.fecha <= periodo.fecha_fin):
        raise ValidationError({'periodo': 'La fecha debe pertenecer a un período ABIERTO.'})

    naturaleza = nota.tipo_operacion.naturaleza
    for detalle in nota.detalles.select_related('producto').all():
        saldo = _bloquear_saldo(empresa_id, detalle.producto_id)
        stock = _bloquear_stock(empresa_id, nota.almacen_id, detalle.producto_id)
        cantidad = _q8(detalle.cantidad_base)
        costo = detalle.costo_unitario_pen if detalle.costo_unitario_pen is not None else (saldo.cpp_pen or CERO)
        valor = _q8(cantidad * costo)
        prioridad = 3 if naturaleza == 'AJUSTE_VALOR' else (2 if naturaleza == 'ENTRADA' else 4)

        if naturaleza == 'SALIDA':
            if stock.cantidad_actual < cantidad or saldo.cantidad_total < cantidad:
                raise ValidationError({'stock': f'Stock insuficiente para el producto {detalle.producto_id}.'})
            stock.cantidad_actual = _q8(stock.cantidad_actual - cantidad)
            saldo.cantidad_total = _q8(saldo.cantidad_total - cantidad)
            saldo.valor_total_pen = _q8(saldo.valor_total_pen - valor)
        elif naturaleza == 'ENTRADA':
            stock.cantidad_actual = _q8(stock.cantidad_actual + cantidad)
            saldo.cantidad_total = _q8(saldo.cantidad_total + cantidad)
            saldo.valor_total_pen = _q8(saldo.valor_total_pen + valor)
        else:
            valor = _q8(detalle.valor_ajuste_pen or CERO)
            saldo.valor_total_pen = _q8(saldo.valor_total_pen + valor)

        saldo.cpp_pen = _cpp(saldo.valor_total_pen, saldo.cantidad_total)
        movimiento = Movimiento.objects.create(
            empresa_id=empresa_id, producto_id=detalle.producto_id,
            almacen_id=nota.almacen_id, periodo=nota.periodo,
            nota_interna_detalle=detalle, tipo_operacion=nota.tipo_operacion,
            fecha_movimiento=nota.fecha, prioridad_dia=prioridad,
            secuencia=siguiente_secuencia_movimiento(
                empresa_id=empresa_id,
                producto_id=detalle.producto_id,
                fecha_movimiento=nota.fecha,
                prioridad_dia=prioridad,
            ),
            naturaleza=naturaleza, cantidad_base=cantidad,
            valor_ajuste_pen=valor if naturaleza == 'AJUSTE_VALOR' else None,
            creado_por=usuario,
        )
        saldo.ultimo_movimiento = movimiento
        saldo.save(update_fields=['cantidad_total', 'valor_total_pen', 'cpp_pen', 'ultimo_movimiento', 'actualizado_en'])
        stock.save(update_fields=['cantidad_actual', 'actualizado_en'])
        _crear_valorizacion(movimiento, costo, valor, saldo)
        if hay_movimientos_posteriores(movimiento):
            ejecutar_recalculo_producto(
                empresa_id=empresa_id, producto_id=detalle.producto_id,
                fecha_desde=movimiento.fecha_movimiento, usuario_id=usuario.id,
            )

    nota.estado = 'CONFIRMADO'
    nota.save(update_fields=['estado'])
    registrar_auditoria(
        empresa_id, usuario.id, 'CONFIRMAR_NOTA_INTERNA', 'NOTA_INTERNA',
        nota.id, {'estado': 'BORRADOR'}, {'estado': 'CONFIRMADO'},
    )
    return nota


@transaction.atomic
def confirmar_transferencia(*, transferencia_id, empresa_id, usuario):
    transferencia = Transferencia.objects.select_for_update().select_related(
        'almacen_origen', 'almacen_destino',
    ).prefetch_related('detalles').filter(empresa_id=empresa_id, pk=transferencia_id).first()
    if transferencia is None:
        raise ValidationError({'detail': 'Transferencia no encontrada.'})
    if transferencia.estado != 'BORRADOR':
        raise ValidationError({'estado': 'Solo puede confirmarse una transferencia BORRADOR.'})

    from apps.empresas.models import Periodo
    periodo = Periodo.objects.select_for_update().filter(
        empresa_id=empresa_id, estado='ABIERTO', fecha_inicio__lte=transferencia.fecha,
        fecha_fin__gte=transferencia.fecha,
    ).first()
    if periodo is None:
        raise ValidationError({'fecha': 'Debe existir un período ABIERTO para la fecha.'})
    tipos = TipoOperacion.objects.in_bulk(
        ['TRANSFERENCIA_SALIDA', 'TRANSFERENCIA_ENTRADA'], field_name='codigo_interno',
    )
    if len(tipos) != 2:
        raise ValidationError({'tipo_operacion': 'Faltan tipos de operación de transferencia.'})

    for detalle in transferencia.detalles.select_related('producto').all():
        saldo = _bloquear_saldo(empresa_id, detalle.producto_id)
        origen = _bloquear_stock(empresa_id, transferencia.almacen_origen_id, detalle.producto_id)
        destino = _bloquear_stock(empresa_id, transferencia.almacen_destino_id, detalle.producto_id)
        cantidad = _q8(detalle.cantidad_base)
        if origen.cantidad_actual < cantidad:
            raise ValidationError({'stock': f'Stock insuficiente para el producto {detalle.producto_id}.'})
        cpp = saldo.cpp_pen or CERO
        valor = _q8(cantidad * cpp)
        origen.cantidad_actual = _q8(origen.cantidad_actual - cantidad)
        destino.cantidad_actual = _q8(destino.cantidad_actual + cantidad)
        origen.save(update_fields=['cantidad_actual', 'actualizado_en'])
        destino.save(update_fields=['cantidad_actual', 'actualizado_en'])

        salida = Movimiento.objects.create(
            empresa_id=empresa_id, producto_id=detalle.producto_id,
            almacen_id=transferencia.almacen_origen_id, periodo=periodo,
            transferencia=transferencia, transferencia_detalle=detalle,
            tipo_operacion=tipos['TRANSFERENCIA_SALIDA'], fecha_movimiento=transferencia.fecha,
            prioridad_dia=4,
            secuencia=siguiente_secuencia_movimiento(
                empresa_id=empresa_id,
                producto_id=detalle.producto_id,
                fecha_movimiento=transferencia.fecha,
                prioridad_dia=4,
            ),
            naturaleza='SALIDA', cantidad_base=cantidad, creado_por=usuario,
        )
        entrada = Movimiento.objects.create(
            empresa_id=empresa_id, producto_id=detalle.producto_id,
            almacen_id=transferencia.almacen_destino_id, periodo=periodo,
            transferencia=transferencia, transferencia_detalle=detalle,
            tipo_operacion=tipos['TRANSFERENCIA_ENTRADA'], fecha_movimiento=transferencia.fecha,
            prioridad_dia=2,
            secuencia=siguiente_secuencia_movimiento(
                empresa_id=empresa_id,
                producto_id=detalle.producto_id,
                fecha_movimiento=transferencia.fecha,
                prioridad_dia=2,
            ),
            naturaleza='ENTRADA', cantidad_base=cantidad, creado_por=usuario,
        )
        _crear_valorizacion(salida, cpp, valor, saldo)
        _crear_valorizacion(entrada, cpp, valor, saldo)
        if hay_movimientos_posteriores(entrada) or hay_movimientos_posteriores(salida):
            ejecutar_recalculo_producto(
                empresa_id=empresa_id, producto_id=detalle.producto_id,
                fecha_desde=transferencia.fecha, usuario_id=usuario.id,
            )

    transferencia.estado = 'CONFIRMADO'
    transferencia.save(update_fields=['estado'])
    registrar_auditoria(
        empresa_id, usuario.id, 'CONFIRMAR_TRANSFERENCIA', 'TRANSFERENCIA',
        transferencia.id, {'estado': 'BORRADOR'}, {'estado': 'CONFIRMADO'},
    )
    return transferencia


@transaction.atomic
def anular_nota_interna_servicio(*, nota_id, empresa_id, usuario, motivo=''):
    nota = NotaInterna.objects.select_for_update().select_related(
        'periodo', 'tipo_operacion',
    ).filter(empresa_id=empresa_id, pk=nota_id).first()
    if nota is None:
        raise ValidationError({'detail': 'Nota interna no encontrada.'})
    if nota.estado == 'ANULADO':
        raise ValidationError({'estado': 'La nota interna ya se encuentra ANULADA.'})

    from apps.empresas.models import Periodo
    periodo = Periodo.objects.select_for_update().get(id=nota.periodo_id, empresa_id=empresa_id)
    if periodo.estado != 'ABIERTO':
        raise ValidationError({'periodo': 'No se puede anular directamente en un período CERRADO. Requiere reapertura previa.'})

    motivo_limpio = (motivo or '').strip()
    if nota.estado == 'CONFIRMADO' and not motivo_limpio:
        raise ValidationError({'motivo': 'El motivo de anulación es obligatorio para notas confirmadas.'})

    if nota.estado == 'CONFIRMADO':
        from apps.kardex.services import tipo_operacion_extorno, aplicar_movimiento
        movimientos_originales = list(
            Movimiento.objects.filter(
                empresa_id=empresa_id,
                nota_interna_detalle__nota_interna_id=nota.id,
                es_extorno=False,
            ).select_related('tipo_operacion', 'valorizacion', 'producto').order_by('id')
        )
        for original in movimientos_originales:
            if original.naturaleza == 'AJUSTE_VALOR':
                tipo = tipo_operacion_extorno('AJUSTE_VALOR')
                monto_ajuste_original = original.valor_ajuste_pen
                if monto_ajuste_original is None and hasattr(original, 'valorizacion'):
                    monto_ajuste_original = original.valorizacion.valor_movimiento_pen
                aplicar_movimiento(
                    empresa_id=empresa_id,
                    producto_id=original.producto_id,
                    almacen_id=original.almacen_id,
                    periodo=periodo,
                    tipo_operacion=tipo,
                    fecha=nota.fecha,
                    cantidad=CERO,
                    usuario_id=usuario.id,
                    costo_unitario=CERO,
                    valor_ajuste=-(monto_ajuste_original or CERO),
                    es_extorno=True,
                    movimiento_extornado=original,
                )
            else:
                tipo = tipo_operacion_extorno('SALIDA' if original.naturaleza == 'ENTRADA' else 'ENTRADA')
                # Validación preventiva de stock en caso de extorno de ENTRADA (que genera SALIDA)
                if tipo.naturaleza == 'SALIDA':
                    stock_actual = _bloquear_stock(empresa_id, original.almacen_id, original.producto_id)
                    saldo_actual = _bloquear_saldo(empresa_id, original.producto_id)
                    if stock_actual.cantidad_actual < original.cantidad_base or saldo_actual.cantidad_total < original.cantidad_base:
                        cod = getattr(original.producto, 'codigo_interno', str(original.producto_id))
                        raise ValidationError({
                            'stock': f'Stock insuficiente para extornar la operación del producto {cod}: las existencias ya fueron consumidas por movimientos posteriores.'
                        })

                costo_orig = original.valorizacion.costo_unitario_pen if hasattr(original, 'valorizacion') else CERO
                aplicar_movimiento(
                    empresa_id=empresa_id,
                    producto_id=original.producto_id,
                    almacen_id=original.almacen_id,
                    periodo=periodo,
                    tipo_operacion=tipo,
                    fecha=nota.fecha,
                    cantidad=original.cantidad_base,
                    usuario_id=usuario.id,
                    costo_unitario=costo_orig,
                    valor_ajuste=None,
                    es_extorno=True,
                    movimiento_extornado=original,
                )
        anterior = {'estado': 'CONFIRMADO'}
    else:
        anterior = {'estado': 'BORRADOR'}

    nota.estado = 'ANULADO'
    if motivo_limpio:
        nota.observacion = f"{nota.observacion}\n[Anulación]: {motivo_limpio}".strip() if nota.observacion else f"[Anulación]: {motivo_limpio}"
    nota.save(update_fields=['estado', 'observacion'])

    registrar_auditoria(
        empresa_id,
        usuario.id,
        'ANULAR_NOTA_INTERNA',
        'NOTA_INTERNA',
        nota.id,
        anterior,
        {'estado': 'ANULADO'},
        motivo_limpio or None,
    )
    return nota


