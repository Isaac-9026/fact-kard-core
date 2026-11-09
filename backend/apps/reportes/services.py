from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum

from apps.kardex.models import Movimiento
from apps.empresas.models import Periodo
from apps.inventario.models import Producto
from apps.reportes.saldos_corte import q8

DECIMAL_ZERO = Decimal('0.00000000')


def _como_fecha(valor):
    if not valor:
        return None
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor))


def _saldo_previo(empresa_id, producto_id, almacen_id, inicio):
    """
    CON-014: saldo de arranque del filtro = estado contable tras el último movimiento
    del producto anterior a `inicio` (orden oficial). Sin `inicio` el arranque es 0.
    Empresa: valores reales de su valorización. Almacén: stock del almacén × CPP global.
    """
    cero = {'cantidad': DECIMAL_ZERO, 'cpp': None, 'valor': DECIMAL_ZERO}
    if inicio is None:
        return cero
    previos = Movimiento.objects.filter(empresa_id=empresa_id, producto_id=producto_id, fecha_movimiento__lt=inicio)
    ultimo = previos.select_related('valorizacion').order_by(
        '-fecha_movimiento', '-prioridad_dia', '-secuencia', '-id',
    ).first()
    if ultimo is None:
        return cero
    val = getattr(ultimo, 'valorizacion', None)
    cpp_previo = val.cpp_empresa if val is not None else None
    if almacen_id:
        en_almacen = previos.filter(almacen_id=almacen_id)
        entradas = en_almacen.filter(naturaleza='ENTRADA').aggregate(t=Sum('cantidad_base'))['t'] or DECIMAL_ZERO
        salidas = en_almacen.filter(naturaleza='SALIDA').aggregate(t=Sum('cantidad_base'))['t'] or DECIMAL_ZERO
        cantidad = q8(entradas - salidas)
        return {'cantidad': cantidad, 'cpp': cpp_previo, 'valor': q8(cantidad * (cpp_previo or DECIMAL_ZERO))}
    if val is None:
        return cero
    return {'cantidad': val.saldo_cantidad_empresa, 'cpp': cpp_previo, 'valor': val.saldo_valor_empresa}


def obtener_documento_referencia(movimiento):
    """
    Retorna la serie-número o código representativo del documento origen del movimiento.
    BE-005: un extorno referencia el documento del movimiento que revierte.
    """
    if movimiento.movimiento_extornado_id and movimiento.movimiento_extornado:
        return f"EXTORNO {obtener_documento_referencia(movimiento.movimiento_extornado)}"
    if movimiento.documento_detalle_id and movimiento.documento_detalle:
        doc = getattr(movimiento.documento_detalle, 'documento', None)
        if doc:
            tc = getattr(doc, 'tipo_comprobante', None)
            tc_cod = getattr(tc, 'codigo_sunat', None) or (str(doc.tipo_comprobante_id) if doc.tipo_comprobante_id else '')
            serie = doc.serie_normalizada or doc.serie or ''
            num = doc.numero_normalizado or doc.numero or ''
            ref = f"{serie}-{num}".strip('-')
            if tc_cod and ref:
                return f"{tc_cod} {ref}"
            return ref or f"DOC-{doc.id}"

    if movimiento.nota_interna_detalle_id and movimiento.nota_interna_detalle:
        ni = getattr(movimiento.nota_interna_detalle, 'nota_interna', None)
        if ni:
            return f"NI-{ni.id:06d}"

    if movimiento.transferencia_detalle_id and movimiento.transferencia_detalle:
        tr = getattr(movimiento.transferencia_detalle, 'transferencia', None)
        if tr:
            return f"TR-{tr.id:06d}"

    if movimiento.transferencia_id:
        return f"TR-{movimiento.transferencia_id:06d}"

    if movimiento.saldo_inicial_id:
        return f"SI-{movimiento.saldo_inicial_id:06d}"

    return f"MOV-{movimiento.id}"


def consultar_kardex_valorizado(
    empresa_id: int,
    producto_id: int = None,
    periodo_id: int = None,
    almacen_id: int = None,
    tipo_operacion_id: int = None,
    fecha_desde: str = None,
    fecha_hasta: str = None
):
    """
    Consulta oficial del Kardex Valorizado bajo el orden cronológico estricto del motor:
    (fecha_movimiento, prioridad_dia, secuencia, id).
    Aplica filtros oficiales y calcula totales de entradas, salidas y saldos.
    """
    # CON-014: el saldo valorizado de cada fila es el valor contable real acumulado por el
    # motor (ValorizacionMovimiento.saldo_*_empresa), no cantidad × CPP. El motor valoriza
    # por empresa + producto (CPP global); con filtro de almacén la cantidad es el stock
    # del almacén y su valor es cantidad × CPP global (no existe un valor por almacén):
    # se informa como ambito_saldo = 'ALMACEN'.
    ambito_saldo = 'ALMACEN' if almacen_id else 'EMPRESA'
    periodo = Periodo.objects.filter(pk=periodo_id, empresa_id=empresa_id).first() if periodo_id else None
    inicios = [d for d in (_como_fecha(fecha_desde), periodo.fecha_inicio if periodo else None) if d]
    inicio = max(inicios) if inicios else None

    # Ventana del reporte SIN el filtro de tipo de operación: el saldo de cada fila debe
    # incluir los movimientos ocultos por ese filtro.
    ventana = Movimiento.objects.filter(empresa_id=empresa_id).select_related(
        'valorizacion',
        'tipo_operacion',
        'almacen',
        'producto',
        'documento_detalle__documento__tipo_comprobante',
        'nota_interna_detalle__nota_interna',
        'transferencia_detalle__transferencia',
        'transferencia',
        'saldo_inicial',
        'movimiento_extornado__tipo_operacion',
        'movimiento_extornado__documento_detalle__documento__tipo_comprobante',
        'movimiento_extornado__nota_interna_detalle__nota_interna',
    )
    if periodo_id:
        ventana = ventana.filter(periodo_id=periodo_id)
    if producto_id:
        ventana = ventana.filter(producto_id=producto_id)
    if almacen_id:
        ventana = ventana.filter(almacen_id=almacen_id)
    if fecha_desde:
        ventana = ventana.filter(fecha_movimiento__gte=fecha_desde)
    if fecha_hasta:
        ventana = ventana.filter(fecha_movimiento__lte=fecha_hasta)

    # Orden cronológico oficial del motor Kardex
    ventana = ventana.order_by('fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')

    filas = []
    total_entradas_cant = DECIMAL_ZERO
    total_entradas_val = DECIMAL_ZERO
    total_salidas_cant = DECIMAL_ZERO
    total_salidas_val = DECIMAL_ZERO

    # Saldo de arranque y estado progresivo por producto (cantidad, cpp, valor).
    estados = {}
    iniciales = {}

    def estado_de(prod_id):
        if prod_id not in estados:
            iniciales[prod_id] = _saldo_previo(empresa_id, prod_id, almacen_id, inicio)
            estados[prod_id] = dict(iniciales[prod_id])
        return estados[prod_id]

    if producto_id:
        estado_de(producto_id)
    elif inicio is not None:
        # B10-07: sin filtro de producto, los productos con saldo anterior al inicio y sin
        # movimientos en la ventana también forman parte del saldo de la empresa (o almacén).
        previos = Movimiento.objects.filter(empresa_id=empresa_id, fecha_movimiento__lt=inicio)
        if almacen_id:
            previos = previos.filter(almacen_id=almacen_id)
        for prod_id in previos.order_by('producto_id').values_list('producto_id', flat=True).distinct():
            estado_de(prod_id)

    for mov in ventana:
        estado = estado_de(mov.producto_id)
        val = getattr(mov, 'valorizacion', None)
        if almacen_id:
            if mov.naturaleza == 'ENTRADA':
                estado['cantidad'] = q8(estado['cantidad'] + mov.cantidad_base)
            elif mov.naturaleza == 'SALIDA':
                estado['cantidad'] = q8(estado['cantidad'] - mov.cantidad_base)
            if val is not None and val.cpp_empresa is not None:
                estado['cpp'] = val.cpp_empresa
            estado['valor'] = q8(estado['cantidad'] * (estado['cpp'] or DECIMAL_ZERO))
        elif val is not None and val.saldo_valor_empresa is not None:
            estado['cantidad'] = val.saldo_cantidad_empresa
            estado['cpp'] = val.cpp_empresa
            estado['valor'] = val.saldo_valor_empresa
        else:
            # Sin valorización (no debería ocurrir en movimientos confirmados): se
            # arrastra el valor anterior y solo cambia la cantidad.
            if mov.naturaleza == 'ENTRADA':
                estado['cantidad'] = q8(estado['cantidad'] + mov.cantidad_base)
            elif mov.naturaleza == 'SALIDA':
                estado['cantidad'] = q8(estado['cantidad'] - mov.cantidad_base)

        if tipo_operacion_id and mov.tipo_operacion_id != int(tipo_operacion_id):
            continue

        val_costo = val.costo_unitario_pen if (val and val.costo_unitario_pen is not None) else None
        val_total = val.valor_movimiento_pen if (val and val.valor_movimiento_pen is not None) else None

        doc_ref = obtener_documento_referencia(mov)
        tipo_op_cod = (mov.tipo_operacion.codigo_sunat or mov.tipo_operacion.codigo_interno) if mov.tipo_operacion else ''
        tipo_op_desc = mov.tipo_operacion.descripcion if mov.tipo_operacion else ''
        almacen_cod = mov.almacen.codigo if mov.almacen else ''
        almacen_nom = mov.almacen.nombre if mov.almacen else ''

        entrada_cant = None
        entrada_costo = None
        entrada_val = None
        salida_cant = None
        salida_costo = None
        salida_val = None

        if mov.naturaleza == 'ENTRADA':
            entrada_cant = mov.cantidad_base
            entrada_costo = val_costo if val_costo is not None else DECIMAL_ZERO
            entrada_val = val_total if val_total is not None else DECIMAL_ZERO
            total_entradas_cant += entrada_cant
            total_entradas_val += entrada_val

        elif mov.naturaleza == 'SALIDA':
            salida_cant = mov.cantidad_base
            salida_costo = val_costo if val_costo is not None else DECIMAL_ZERO
            salida_val = val_total if val_total is not None else DECIMAL_ZERO
            total_salidas_cant += salida_cant
            total_salidas_val += salida_val

        elif mov.naturaleza == 'AJUSTE_VALOR':
            adj = val_total if val_total is not None else (mov.valor_ajuste_pen or DECIMAL_ZERO)
            if adj >= Decimal('0'):
                entrada_cant = DECIMAL_ZERO
                entrada_costo = DECIMAL_ZERO
                entrada_val = abs(adj)
                total_entradas_val += entrada_val
            else:
                salida_cant = DECIMAL_ZERO
                salida_costo = DECIMAL_ZERO
                salida_val = abs(adj)
                total_salidas_val += salida_val

        fila = {
            'id': mov.id,
            'fecha': mov.fecha_movimiento,
            'documento_referencia': doc_ref,
            'tipo_operacion_codigo': tipo_op_cod,
            'tipo_operacion_descripcion': tipo_op_desc,
            'naturaleza': mov.naturaleza,
            'almacen_codigo': almacen_cod,
            'almacen_nombre': almacen_nom,
            'producto_id': mov.producto_id,
            'producto_codigo': mov.producto.codigo_interno if mov.producto else '',
            'producto_descripcion': mov.producto.descripcion if mov.producto else '',
            'entrada_cantidad': entrada_cant,
            'entrada_costo_unitario': entrada_costo,
            'entrada_valor': entrada_val,
            'salida_cantidad': salida_cant,
            'salida_costo_unitario': salida_costo,
            'salida_valor': salida_val,
            'saldo_cantidad': estado['cantidad'],
            'cpp': estado['cpp'] if estado['cpp'] is not None else DECIMAL_ZERO,
            'saldo_valor': estado['valor'],
            'prioridad_dia': mov.prioridad_dia,
            'secuencia': mov.secuencia,
            'es_extorno': mov.es_extorno,
            'movimiento_extornado_id': mov.movimiento_extornado_id,
            'operacion_extornada_codigo': (
                mov.movimiento_extornado.tipo_operacion.codigo_interno
                if mov.movimiento_extornado_id and mov.movimiento_extornado else None
            ),
            'generado_por_motor': mov.generado_por_motor,
            'creado_en': mov.creado_en,
        }
        filas.append(fila)

    # Saldos de arranque y finales por producto (los finales incluyen los movimientos
    # de la ventana ocultos por el filtro de tipo de operación).
    productos = Producto.objects.in_bulk(list(estados))
    saldos_iniciales = []
    for prod_id, ini in iniciales.items():
        prod = productos.get(prod_id)
        saldos_iniciales.append({
            'producto_id': prod_id,
            'producto_codigo': prod.codigo_interno if prod else '',
            'cantidad': q8(ini['cantidad']),
            'cpp': q8(ini['cpp']) if ini['cpp'] is not None else None,
            'valor': q8(ini['valor']),
        })
    saldo_inicial_cantidad = sum((e['cantidad'] for e in iniciales.values()), DECIMAL_ZERO)
    saldo_inicial_valor = sum((e['valor'] for e in iniciales.values()), DECIMAL_ZERO)
    saldo_final_cantidad = sum((e['cantidad'] for e in estados.values()), DECIMAL_ZERO)
    saldo_final_valor = sum((e['valor'] for e in estados.values()), DECIMAL_ZERO)
    # Un CPP de cierre solo tiene sentido para un único producto.
    cpp_final = next(iter(estados.values()))['cpp'] if len(estados) == 1 else None

    resumen = {
        'total_entradas_cantidad': total_entradas_cant.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP),
        'total_entradas_valor': total_entradas_val.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP),
        'total_salidas_cantidad': total_salidas_cant.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP),
        'total_salidas_valor': total_salidas_val.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP),
        'saldo_inicial_cantidad': q8(saldo_inicial_cantidad),
        'saldo_inicial_valor': q8(saldo_inicial_valor),
        'saldo_final_cantidad': saldo_final_cantidad.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP),
        'cpp_final': cpp_final.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP) if cpp_final is not None else None,
        'saldo_final_valor': saldo_final_valor.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP),
        'total_registros': len(filas),
        'ambito_saldo': ambito_saldo,
    }

    return {
        'empresa_id': empresa_id,
        'filtros': {
            'producto_id': producto_id,
            'periodo_id': periodo_id,
            'almacen_id': almacen_id,
            'tipo_operacion_id': tipo_operacion_id,
            'fecha_desde': fecha_desde,
            'fecha_hasta': fecha_hasta,
        },
        'resumen': resumen,
        'saldos_iniciales': saldos_iniciales,
        'movimientos': filas,
    }
