from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from rest_framework.exceptions import ValidationError

from apps.empresas.models import CierrePeriodo, ConfigEmpresa, Empresa, Establecimiento, Periodo
from apps.inventario.models import Producto
from apps.kardex.models import Movimiento, ValorizacionMovimiento
from apps.reportes.saldos_corte import (
    establecimiento_principal_id, q8, saldos_al_corte, valores_establecimiento_por_movimiento,
    valores_por_establecimiento,
)


ZERO = Decimal('0.00000000')


def texto_decimal(valor):
    return format(q8(valor), '.8f')


def validar_filtros_formato(*, empresa_id, periodo_id, establecimiento_id=None, producto_id=None):
    if not periodo_id:
        raise ValidationError({'periodo_id': 'Este parámetro es obligatorio.'})
    periodo = Periodo.objects.filter(pk=periodo_id, empresa_id=empresa_id).first()
    if not periodo:
        raise ValidationError({'periodo_id': 'El período no pertenece a la empresa activa.'})
    establecimiento = None
    if establecimiento_id:
        establecimiento = Establecimiento.objects.filter(
            pk=establecimiento_id, empresa_id=empresa_id,
        ).first()
        if not establecimiento:
            raise ValidationError({'establecimiento_id': 'El establecimiento no pertenece a la empresa activa.'})
    producto = None
    if producto_id:
        producto = Producto.objects.filter(pk=producto_id, empresa_id=empresa_id).first()
        if not producto:
            raise ValidationError({'producto_id': 'El producto no pertenece a la empresa activa.'})
    return periodo, establecimiento, producto


def _documento_sunat(movimiento):
    # BE-005: el extorno se reporta con el comprobante del movimiento que anula.
    if movimiento.movimiento_extornado_id and movimiento.movimiento_extornado:
        return _documento_sunat(movimiento.movimiento_extornado)
    if movimiento.documento_detalle_id:
        documento = movimiento.documento_detalle.documento
        return {
            'tipo_documento': documento.tipo_comprobante.codigo_sunat,
            'serie': documento.serie_normalizada or documento.serie or '',
            'numero': documento.numero_normalizado or documento.numero or '',
        }
    if movimiento.nota_interna_detalle_id:
        identificador = movimiento.nota_interna_detalle.nota_interna_id
        return {'tipo_documento': '00', 'serie': 'NI', 'numero': str(identificador)}
    if movimiento.transferencia_detalle_id or movimiento.transferencia_id:
        identificador = movimiento.transferencia_id or movimiento.transferencia_detalle.transferencia_id
        return {'tipo_documento': '00', 'serie': 'TR', 'numero': str(identificador)}
    if movimiento.saldo_inicial_id:
        return {'tipo_documento': '00', 'serie': 'SI', 'numero': str(movimiento.saldo_inicial_id)}
    return {'tipo_documento': '00', 'serie': 'MOV', 'numero': str(movimiento.id)}


def _cpp_historico(*, empresa_id, producto_id, fecha_inicio=None, fecha_fin=None):
    """
    CON-010: CPP global (empresa + producto) de la última valorización en el orden
    oficial anterior a fecha_inicio, o hasta fecha_fin inclusive. Nunca usa
    SaldoCppActual, que refleja operaciones posteriores al período.
    """
    qs = ValorizacionMovimiento.objects.filter(
        movimiento__empresa_id=empresa_id, movimiento__producto_id=producto_id,
    )
    if fecha_inicio is not None:
        qs = qs.filter(movimiento__fecha_movimiento__lt=fecha_inicio)
    if fecha_fin is not None:
        qs = qs.filter(movimiento__fecha_movimiento__lte=fecha_fin)
    ultima = qs.order_by(
        '-movimiento__fecha_movimiento', '-movimiento__prioridad_dia',
        '-movimiento__secuencia', '-movimiento__id',
    ).first()
    return q8(ultima.cpp_empresa if ultima else ZERO)


class _CacheProducto:
    """
    Bloque 6: los datos que dependen solo del producto (no del establecimiento) se
    calculan una vez por generación del 13.1. Antes se repetían por cada par
    (establecimiento, producto) con varias consultas cada vez. Mismos resultados.
    """

    def __init__(self, empresa_id):
        self.empresa_id = empresa_id
        self.principal = establecimiento_principal_id(empresa_id)
        self._memo = {}

    def _de(self, clave, calcular):
        if clave not in self._memo:
            self._memo[clave] = calcular()
        return self._memo[clave]

    def estado(self, producto_id, corte):
        return self._de(('estado', producto_id, corte),
                        lambda: saldos_al_corte(self.empresa_id, corte, producto_id).get(producto_id))

    def cantidad_anterior(self, producto_id, establecimiento_id, fecha_inicio):
        """Equivale a _cantidad_anterior (movimientos con fecha < fecha_inicio)."""
        estado = self.estado(producto_id, fecha_inicio - timedelta(days=1))
        return q8(estado['establecimientos'].get(establecimiento_id, ZERO)) if estado else ZERO

    def valor_establecimiento(self, producto_id, establecimiento_id, corte, *, defecto):
        estado = self.estado(producto_id, corte)
        if estado is None:
            return defecto
        valores = self._de(('valores', producto_id, corte),
                           lambda: valores_por_establecimiento(self.empresa_id, estado, self.principal))
        return valores.get(establecimiento_id, defecto)

    def cpp(self, producto_id, *, fecha_inicio=None, fecha_fin=None):
        return self._de(('cpp', producto_id, fecha_inicio, fecha_fin), lambda: _cpp_historico(
            empresa_id=self.empresa_id, producto_id=producto_id, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        ))

    def reparto(self, producto_id, hasta):
        return self._de(('reparto', producto_id, hasta), lambda: valores_establecimiento_por_movimiento(
            self.empresa_id, producto_id, hasta, principal=self.principal,
        ))

    def unidad_base(self, producto):
        return self._de(('unidad', producto.id), lambda: producto.unidades.select_related('unidad_codigo').filter(
            es_base=True,
        ).first())


def _periodo_anterior(periodo):
    return Periodo.objects.filter(
        empresa_id=periodo.empresa_id, orden__lt=periodo.orden,
    ).order_by('-orden').first()


def generar_formato_131(*, empresa_id, periodo_id, establecimiento_id=None, producto_id=None):
    periodo, establecimiento, producto = validar_filtros_formato(
        empresa_id=empresa_id,
        periodo_id=periodo_id,
        establecimiento_id=establecimiento_id,
        producto_id=producto_id,
    )
    empresa = Empresa.objects.get(pk=empresa_id)
    config = ConfigEmpresa.objects.filter(empresa_id=empresa_id).first()
    metodo_config = config.metodo_valuacion if config else 'CPP'
    metodo = 'PROMEDIO PONDERADO (CPP)' if metodo_config == 'CPP' else metodo_config

    movimientos = Movimiento.objects.filter(
        empresa_id=empresa_id,
        periodo_id=periodo.id,
        fecha_movimiento__gte=periodo.fecha_inicio,
        fecha_movimiento__lte=periodo.fecha_fin,
    ).select_related(
        'almacen__establecimiento', 'producto__tipo_existencia_codigo',
        'tipo_operacion', 'valorizacion',
        'documento_detalle__documento__tipo_comprobante',
        'nota_interna_detalle__nota_interna',
        'transferencia_detalle__transferencia',
        'movimiento_extornado__tipo_operacion',
        'movimiento_extornado__documento_detalle__documento__tipo_comprobante',
    )
    if establecimiento:
        movimientos = movimientos.filter(almacen__establecimiento_id=establecimiento.id)
    if producto:
        movimientos = movimientos.filter(producto_id=producto.id)
    movimientos = movimientos.order_by(
        'fecha_movimiento', 'prioridad_dia', 'secuencia', 'id',
    )

    agrupados = defaultdict(list)
    for movimiento in movimientos:
        agrupados[(movimiento.almacen.establecimiento_id, movimiento.producto_id)].append(movimiento)

    # Identificar productos que tienen saldo anterior en establecimientos aunque no hayan tenido movimientos en el mes
    from apps.kardex.models import StockAlmacen
    stocks_qs = StockAlmacen.objects.filter(empresa_id=empresa_id).select_related('almacen')
    if establecimiento:
        stocks_qs = stocks_qs.filter(almacen__establecimiento_id=establecimiento.id)
    if producto:
        stocks_qs = stocks_qs.filter(producto_id=producto.id)

    cache = _CacheProducto(empresa_id)
    pares_conocidos = set(agrupados.keys())
    for st in stocks_qs:
        par = (st.almacen.establecimiento_id, st.producto_id)
        if par not in pares_conocidos:
            cant_ant = cache.cantidad_anterior(st.producto_id, st.almacen.establecimiento_id, periodo.fecha_inicio)
            if cant_ant != ZERO:
                agrupados[par] = []
                pares_conocidos.add(par)

    cierre = CierrePeriodo.objects.filter(periodo_id=periodo.id, vigente=True).prefetch_related('detalles').first()
    cierre_detalles = {
        (detalle.establecimiento_id, detalle.producto_id): detalle
        for detalle in cierre.detalles.all()
    } if cierre else {}

    # CON-010: el saldo inicial valorizado coincide con el cierre vigente del período anterior si existe.
    anterior = _periodo_anterior(periodo)
    cierre_anterior = CierrePeriodo.objects.filter(
        periodo_id=anterior.id, vigente=True,
    ).prefetch_related('detalles').first() if anterior else None
    detalles_cierre_anterior = {
        (detalle.establecimiento_id, detalle.producto_id): detalle
        for detalle in cierre_anterior.detalles.all()
    } if cierre_anterior else {}

    reportes = []
    for (estab_id, prod_id), movimientos_grupo in sorted(
        agrupados.items(), key=lambda item: (
            item[1][0].almacen.establecimiento.codigo_sunat if item[1] else Establecimiento.objects.get(pk=item[0][0]).codigo_sunat,
            item[1][0].producto.codigo_interno if item[1] else Producto.objects.get(pk=item[0][1]).codigo_interno,
        ),
    ):
        if movimientos_grupo:
            prod = movimientos_grupo[0].producto
            estab = movimientos_grupo[0].almacen.establecimiento
        else:
            prod = Producto.objects.select_related('tipo_existencia_codigo').get(pk=prod_id)
            estab = Establecimiento.objects.get(pk=estab_id)

        unidad_base = cache.unidad_base(prod)
        if not unidad_base:
            raise ValidationError({'producto_id': f'El producto {prod.codigo_interno} no tiene unidad base.'})
        saldo_inicial_cantidad = cache.cantidad_anterior(prod_id, estab_id, periodo.fecha_inicio)
        saldo_fisico = saldo_inicial_cantidad
        # CON-010: CPP histórico al inicio del período (no SaldoCppActual).
        cpp_inicial = cache.cpp(prod_id, fecha_inicio=periodo.fecha_inicio)
        detalle_inicial = detalles_cierre_anterior.get((estab_id, prod_id))
        if detalle_inicial is not None and q8(detalle_inicial.saldo_cantidad) == saldo_inicial_cantidad:
            costo_total_inicial = q8(detalle_inicial.saldo_valor_pen)
        else:
            # Bloque 4: sin cierre previo, el valor del establecimiento es su parte del saldo
            # real de la empresa (cantidad × CPP con el redondeo asignado como en el cierre).
            costo_total_inicial = cache.valor_establecimiento(
                prod_id, estab_id, periodo.fecha_inicio - timedelta(days=1),
                defecto=q8(saldo_inicial_cantidad * cpp_inicial),
            )
        saldo_inicial_valorizado = {
            'cantidad': texto_decimal(saldo_inicial_cantidad),
            'costo_unitario': texto_decimal(cpp_inicial),
            'costo_total': texto_decimal(costo_total_inicial),
        }
        cpp_global = cpp_inicial
        # Bloque 5: valor del establecimiento tras cada movimiento = su parte del saldo real.
        reparto = cache.reparto(prod_id, periodo.fecha_fin) if movimientos_grupo else {}
        # QA-003: valor del establecimiento tras la fila anterior (para las filas sin reparto).
        valor_establecimiento = costo_total_inicial
        filas = []
        for movimiento in movimientos_grupo:
            valorizacion = getattr(movimiento, 'valorizacion', None)
            costo_unitario = q8(
                valorizacion.costo_unitario_pen if valorizacion and valorizacion.costo_unitario_pen is not None
                else valorizacion.cpp_empresa if valorizacion else ZERO
            )
            valor_movimiento = q8(
                valorizacion.valor_movimiento_pen if valorizacion and valorizacion.valor_movimiento_pen is not None
                else movimiento.valor_ajuste_pen
            )
            cpp_global = q8(valorizacion.cpp_empresa if valorizacion else costo_unitario)
            cpp_fila = cpp_global
            if movimiento.id in reparto:
                valor_fila = reparto[movimiento.id].get(estab_id, ZERO)
            elif (movimiento.tipo_operacion.codigo_interno == 'TRANSFERENCIA_ENTRADA' and not movimiento.es_extorno
                    and q8(saldo_fisico + movimiento.cantidad_base) != ZERO):
                # QA-003: entre la entrada (prioridad 2 del día) y la salida (prioridad 4) de una
                # transferencia las cantidades por establecimiento no suman las de la empresa y ese
                # instante no se reparte. Antes el saldo del destino se armaba con el CPP de la
                # empresa en ese instante, que puede ser anterior a un ajuste o a una compra del
                # mismo día (NC de descuento, prioridad 3): entrada 10 × 12.25 = 122.50 pero saldo
                # 10 × 12.50 = 125.00. El saldo del destino es su valor anterior + lo que entra,
                # al costo de la transferencia. No cambia el CPP global, el Kardex ni el saldo final.
                valor_fila = q8(valor_establecimiento + valor_movimiento)
                cpp_fila = q8(valor_fila / q8(saldo_fisico + movimiento.cantidad_base))
            else:
                valor_fila = None  # cantidad × CPP de la fila, cuando se conozca la cantidad
            entrada = salida = None
            if movimiento.naturaleza == 'ENTRADA':
                saldo_fisico = q8(saldo_fisico + movimiento.cantidad_base)
                entrada = {
                    'cantidad': texto_decimal(movimiento.cantidad_base),
                    'costo_unitario': texto_decimal(costo_unitario),
                    'costo_total': texto_decimal(valor_movimiento),
                }
            elif movimiento.naturaleza == 'SALIDA':
                saldo_fisico = q8(saldo_fisico - movimiento.cantidad_base)
                salida = {
                    'cantidad': texto_decimal(movimiento.cantidad_base),
                    'costo_unitario': texto_decimal(costo_unitario),
                    'costo_total': texto_decimal(valor_movimiento),
                }
            elif movimiento.naturaleza == 'AJUSTE_VALOR':
                bloque = {'cantidad': texto_decimal(ZERO), 'costo_unitario': texto_decimal(ZERO), 'costo_total': texto_decimal(abs(valor_movimiento))}
                entrada = bloque if valor_movimiento >= ZERO else None
                salida = bloque if valor_movimiento < ZERO else None

            valor_establecimiento = q8(valor_fila if valor_fila is not None else saldo_fisico * cpp_fila)
            filas.append({
                'movimiento_id': movimiento.id,
                'fecha_emision': movimiento.fecha_movimiento.isoformat(),
                'documento': _documento_sunat(movimiento),
                'tipo_operacion': movimiento.tipo_operacion.codigo_sunat or '',
                'tipo_operacion_interno': movimiento.tipo_operacion.codigo_interno,
                'es_extorno': movimiento.es_extorno,
                'movimiento_extornado_id': movimiento.movimiento_extornado_id,
                'operacion_extornada': (
                    movimiento.movimiento_extornado.tipo_operacion.codigo_interno
                    if movimiento.movimiento_extornado_id and movimiento.movimiento_extornado else None
                ),
                'entrada': entrada,
                'salida': salida,
                'saldo_final': {
                    'cantidad': texto_decimal(saldo_fisico),
                    'costo_unitario': texto_decimal(cpp_fila),
                    'costo_total': texto_decimal(valor_fila if valor_fila is not None else saldo_fisico * cpp_fila),
                },
                'orden': {
                    'prioridad_dia': movimiento.prioridad_dia,
                    'secuencia': movimiento.secuencia,
                },
            })

        # CON-010 / Bloque 4: el CPP al cierre del período es el histórico global a la fecha
        # fin; otros establecimientos pueden haberlo movido después del último movimiento
        # propio, así que no se toma el de la última fila.
        cpp_fin = cache.cpp(prod_id, fecha_fin=periodo.fecha_fin)
        if not filas and cpp_fin == cpp_inicial:
            # Bloque 3: sin movimientos y sin cambio de CPP el saldo final es exactamente el
            # inicial valorizado (no se reconstruye como cantidad × CPP).
            saldo_final_resumen = dict(saldo_inicial_valorizado)
        else:
            saldo_final_resumen = {
                'cantidad': texto_decimal(saldo_fisico),
                'costo_unitario': texto_decimal(cpp_fin),
                'costo_total': texto_decimal(saldo_fisico * cpp_fin),
            }

        microdiferencia = ZERO
        calculado = q8(Decimal(saldo_final_resumen['costo_total']))
        detalle_cierre = cierre_detalles.get((estab_id, prod_id))
        if detalle_cierre:
            oficial = q8(detalle_cierre.saldo_valor_pen)
            fuente_saldo_final = 'CIERRE'
        else:
            # Bloque 4: período sin cierre → misma regla que el cierre: la suma de los
            # establecimientos es exactamente el saldo real de la empresa.
            oficial = cache.valor_establecimiento(prod_id, estab_id, periodo.fecha_fin, defecto=calculado)
            fuente_saldo_final = 'CALCULADO'
        microdiferencia = q8(oficial - calculado)
        # El saldo final informado coincide con el saldo oficial (cierre o empresa).
        saldo_final_resumen['costo_total'] = texto_decimal(oficial)

        reportes.append({
            'cabecera': {
                'establecimiento': {'id': estab.id, 'codigo_sunat': estab.codigo_sunat, 'nombre': estab.nombre},
                'producto_id': prod.id,
                'codigo_existencia': prod.codigo_interno,
                'tipo_existencia': {
                    'codigo': prod.tipo_existencia_codigo_id,
                    'descripcion': prod.tipo_existencia_codigo.descripcion,
                },
                'descripcion_existencia': prod.descripcion,
                'unidad_medida': {
                    'codigo': unidad_base.unidad_codigo_id,
                    'descripcion': unidad_base.unidad_codigo.descripcion,
                },
                'metodo_valuacion': metodo,
            },
            'saldo_inicial': texto_decimal(saldo_inicial_cantidad),
            'saldo_inicial_valorizado': saldo_inicial_valorizado,
            'saldo_final': saldo_final_resumen,
            'movimientos': filas,
            'microdiferencia_cierre': texto_decimal(microdiferencia),
            # CIERRE: snapshot oficial; CALCULADO: reparto del saldo real de la empresa.
            'fuente_saldo_final': fuente_saldo_final,
        })

    return {
        'periodo': f'{periodo.anio:04d}-{periodo.mes:02d}',
        'periodo_id': periodo.id,
        'estado_periodo': periodo.estado,
        'empresa': {'ruc': empresa.ruc, 'razon_social': empresa.razon_social},
        'fuente_cierre': {
            'cierre_id': cierre.id,
            'version': cierre.version_calculo,
            'hash': cierre.hash_resultado,
        } if cierre else None,
        'reportes': reportes,
    }
