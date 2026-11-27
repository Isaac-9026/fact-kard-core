"""
Importación Excel "Entradas y salidas" — paso 2: grabar.

Vuelve a analizar los archivos desde cero (nunca confía en la previsualización del cliente) y, si
no hay errores ni conflictos, crea cada comprobante por el flujo normal crear → revisar →
confirmar, en orden de fecha, todo o nada, dentro de un lote anulable.

«Completar comprobante»: a un comprobante importado antes que le falta un producto del Excel se le
agregan solo esas líneas (con su movimiento de Kardex), marcadas con el lote que las agregó. Al
anular ese lote se extornan y quedan revertidas solo esas líneas.
"""
import hashlib
import io
import time
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import registrar_auditoria
from apps.catalogos.models import TipoOperacion
from apps.documentos.afectacion_igv import GRAVADO, SIN_IGV, igv_esperado, tasa_igv
from apps.documentos.importacion_kardex_excel import CERO, _analizar, comparar_con_registrado
from apps.documentos.models import Documento, DocumentoDetalle, ImportacionArchivo, ImportacionLote
from apps.documentos.services import confirmar_documento_validacion, crear_documento, revisar_documento
from apps.inventario.documentos_identidad import SIN_RUC
from apps.inventario.models import Almacen, Tercero
from apps.kardex.services import modo_lote_kardex

OPERACION_INTERNA = {'01': 'VENTA', '02': 'COMPRA', '05': 'DEVOLUCION_VENTA', '06': 'DEVOLUCION_COMPRA'}
VARIOS_NUMERO = '00000000'
VARIOS_NOMBRE = 'VARIOS (IMPORTACIÓN)'


def _leer_bytes(archivos):
    contenidos = []
    for nombre, archivo in archivos:
        if hasattr(archivo, 'seek'):
            archivo.seek(0)
        datos = archivo.read() if hasattr(archivo, 'read') else bytes(archivo)
        contenidos.append((nombre, datos, hashlib.sha256(datos).hexdigest()))
    return contenidos


def _almacen(empresa_id, almacen_id):
    almacenes = Almacen.objects.filter(empresa_id=empresa_id, activo=True)
    if almacen_id:
        almacen = almacenes.filter(pk=almacen_id).first()
        if not almacen:
            raise ValidationError({'almacen': 'El almacén no existe, está inactivo o no pertenece a la empresa.'})
        return almacen
    lista = list(almacenes[:2])
    if len(lista) != 1:
        raise ValidationError({'almacen': 'Elija el almacén al que entran y salen los movimientos importados.'})
    return lista[0]


class _Terceros:
    """Busca o registra proveedores y clientes por RUC/DNI; el genérico VARIOS solo para facturas."""

    def __init__(self, empresa_id):
        self.empresa_id = empresa_id
        self.cache = {}

    def por_documento(self, numero, razon_social, rol):
        from apps.documentos.importacion_kardex_excel import _tipo_identidad
        tipo = _tipo_identidad(numero)
        clave = (tipo, numero)
        tercero = self.cache.get(clave) or Tercero.objects.filter(
            empresa_id=self.empresa_id, tipo_documento=tipo, numero_documento=numero,
        ).first()
        if tercero is None:
            tercero = Tercero.objects.create(
                empresa_id=self.empresa_id, tipo_documento=tipo, numero_documento=numero,
                razon_social=(razon_social or f'{rol.upper()} {numero}')[:200],
                es_proveedor=rol == 'proveedor', es_cliente=rol == 'cliente',
            )
        campo = 'es_proveedor' if rol == 'proveedor' else 'es_cliente'
        if not getattr(tercero, campo):
            setattr(tercero, campo, True)
            tercero.save(update_fields=[campo])
        self.cache[clave] = tercero
        return tercero

    def varios(self):
        clave = (SIN_RUC, VARIOS_NUMERO)
        if clave not in self.cache:
            tercero, _ = Tercero.objects.get_or_create(
                empresa_id=self.empresa_id, tipo_documento=SIN_RUC, numero_documento=VARIOS_NUMERO,
                defaults={'razon_social': VARIOS_NOMBRE, 'es_cliente': True},
            )
            if not tercero.es_cliente:
                tercero.es_cliente = True
                tercero.save(update_fields=['es_cliente'])
            self.cache[clave] = tercero
        return self.cache[clave]


def _etiqueta(lineas):
    p = lineas[0]
    return f'{p.serie}-{p.numero} ({p.fecha:%d/%m/%Y})'


OCHO = Decimal('0.00000001')


def _nombre(documento):
    return f'{documento.serie_normalizada}-{documento.numero_normalizado}'


def _completar_comprobante(*, empresa_id, usuario, lote, existente_id, lineas, ctx, almacen, tipos_operacion):
    """
    Agrega a un comprobante ya confirmado solo las líneas que le faltan. Revalida todo con el
    comprobante bloqueado (puede haber cambiado desde la previsualización) y aplica un movimiento de
    Kardex por línea nueva, igual que la confirmación normal. Devuelve las líneas creadas.
    """
    from apps.documentos.afectacion_igv import resolver_afectacion, validar_igv_linea
    from apps.documentos.reglas import validar_naturaleza_linea
    from apps.documentos.services import base_imponible_linea, obtener_porcentaje_credito_fiscal
    from apps.empresas.models import Periodo
    from apps.empresas.periodos import validar_fecha_en_periodo_abierto
    from apps.kardex.services import aplicar_movimiento

    documento = (
        Documento.objects.select_for_update(of=('self',))
        .select_related('periodo', 'tipo_comprobante', 'tercero', 'importacion_lote')
        .get(pk=existente_id, empresa_id=empresa_id)
    )
    plan = comparar_con_registrado(documento, lineas, ctx['productos'])
    if plan['estado'] != 'COMPLETAR':
        raise ValidationError({'detalles': plan['mensaje']})
    periodo = Periodo.objects.select_for_update().get(pk=documento.periodo_id, empresa_id=empresa_id)
    validar_fecha_en_periodo_abierto(empresa_id=empresa_id, periodo=periodo, fecha=documento.fecha_emision)
    if documento.moneda_codigo_id == 'USD' and not (documento.monto_tc and documento.monto_tc > CERO):
        raise ValidationError({'tipo_cambio': 'El comprobante está en USD y no tiene un tipo de cambio válido.'})

    porcentaje_cf = obtener_porcentaje_credito_fiscal(empresa_id, periodo)
    tasa = tasa_igv(empresa_id, documento.fecha_emision)
    siguiente = (documento.detalles.order_by('-linea').values_list('linea', flat=True).first() or 0) + 1
    subtotal = documento.subtotal or CERO
    igv_total = documento.igv or CERO
    creadas = []
    for l in plan['agregar']:
        producto = ctx['productos'][l.codigo]
        unidad = producto.unidades.get(es_base=True)
        tipo_op = tipos_operacion[OPERACION_INTERNA[l.operacion]]
        validar_naturaleza_linea(clase=documento.clase, tipo_comprobante=documento.tipo_comprobante,
                                 tipo_operacion=tipo_op, linea_num=siguiente)
        precio = l.costo_unitario if l.operacion == '02' else (l.precio_unitario if l.precio_unitario is not None else CERO)
        afectacion, codigo_afectacion = resolver_afectacion(
            afectacion=producto.afectacion_igv_defecto or GRAVADO, codigo=None, es_bonificacion=False, linea_num=siguiente,
        )
        igv = igv_esperado(precio * l.cantidad, tasa) if afectacion == GRAVADO else CERO
        validar_igv_linea(igv=igv, afectacion=afectacion, linea_num=siguiente, tasa=tasa, base=base_imponible_linea(
            precio_unitario=precio, cantidad_original=l.cantidad, naturaleza=tipo_op.naturaleza,
        ))
        factor = unidad.factor_a_base
        cantidad_base = (l.cantidad * factor).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP).quantize(OCHO)
        costo_pen = None
        if documento.clase == 'COMPRA':
            costo_doc = precio * l.cantidad + igv * (Decimal('100') - porcentaje_cf) / Decimal('100')
            if documento.moneda_codigo_id == 'USD':
                costo_doc *= documento.monto_tc
            costo_pen = (costo_doc / cantidad_base).quantize(OCHO, rounding=ROUND_HALF_UP) if cantidad_base > CERO else CERO
        detalle = DocumentoDetalle.objects.create(
            documento=documento, linea=siguiente, producto=producto, producto_unidad=unidad, almacen=almacen,
            tipo_operacion=tipo_op, afecta_kardex_aplicado=tipo_op.afecta_kardex, cantidad_original=l.cantidad,
            factor_conversion=factor, cantidad_base=cantidad_base, precio_unitario=precio, igv=igv,
            porcentaje_credito_fiscal_aplicado=porcentaje_cf, costo_unitario_pen=costo_pen,
            afectacion_igv=afectacion, codigo_afectacion_igv=codigo_afectacion,
            costo_unitario_importado=l.costo_unitario, costo_total_importado=l.costo_total,
            importacion_lote=lote,
        )
        if detalle.afecta_kardex_aplicado:
            aplicar_movimiento(
                empresa_id=empresa_id, producto_id=producto.id, almacen_id=almacen.id, periodo=documento.periodo,
                tipo_operacion=tipo_op, fecha=documento.fecha_emision, cantidad=cantidad_base,
                usuario_id=usuario.id, costo_unitario=costo_pen, documento_detalle=detalle,
            )
        subtotal += precio * l.cantidad
        igv_total += igv
        registrar_auditoria(
            empresa_id=empresa_id, usuario_id=usuario.id, accion='COMPLETAR', entidad='DOCUMENTO_DETALLE',
            registro_id=detalle.id,
            valor_nuevo={
                'documento': documento.id, 'comprobante': _nombre(documento), 'linea': detalle.linea,
                'producto': producto.codigo_interno, 'cantidad': format(l.cantidad, 'f'),
                'costo_unitario': format(l.costo_unitario, 'f'), 'lote': lote.id,
                'lote_original': documento.importacion_lote_id,
            },
            motivo=f'Línea agregada por el lote de importación {lote.id} (fila {l.fila} de "{l.archivo}")',
        )
        creadas.append(detalle)
        siguiente += 1
    antes = {'subtotal': str(documento.subtotal), 'igv': str(documento.igv), 'total': str(documento.total)}
    documento.subtotal = subtotal.quantize(OCHO, rounding=ROUND_HALF_UP)
    documento.igv = igv_total.quantize(OCHO, rounding=ROUND_HALF_UP)
    documento.total = (subtotal + igv_total).quantize(OCHO, rounding=ROUND_HALF_UP)
    documento.save(update_fields=['subtotal', 'igv', 'total'])
    registrar_auditoria(
        empresa_id=empresa_id, usuario_id=usuario.id, accion='COMPLETAR', entidad='DOCUMENTO', registro_id=documento.id,
        valor_anterior=antes,
        valor_nuevo={'subtotal': str(documento.subtotal), 'igv': str(documento.igv), 'total': str(documento.total),
                     'lote': lote.id, 'lineas': [d.linea for d in creadas]},
        motivo=f'Comprobante completado por el lote de importación {lote.id}',
    )
    return creadas


def confirmar_importacion_kardex(*, empresa_id, usuario, archivos, almacen_id=None, proveedores=None, on_progreso=None) -> dict:
    if on_progreso:
        on_progreso('ANALIZANDO', 'Leyendo y validando archivos Excel...', 0, 1)
    contenidos = _leer_bytes(archivos)
    repetidos = ImportacionArchivo.objects.filter(
        empresa_id=empresa_id, sha256__in=[h for _, _, h in contenidos], lote__estado='CONFIRMADO',
    ).select_related('lote')
    if repetidos:
        detalle = ', '.join(f'"{a.nombre}" (lote {a.lote_id})' for a in repetidos)
        raise ValidationError({'archivos': f'Estos archivos ya fueron importados: {detalle}. Anule ese lote si necesita volver a subirlos.'})

    almacen = _almacen(empresa_id, almacen_id)
    resultado, ctx = _analizar(
        empresa_id=empresa_id, archivos=[(n, io.BytesIO(d)) for n, d, _ in contenidos], proveedores=proveedores,
    )
    resumen = resultado['resumen']
    if resumen['excede_limite']:
        raise ValidationError({'importacion': (
            f'El lote tiene {resumen["nuevos"] + resumen["completar"]} comprobantes por grabar y el máximo es '
            f'{resumen["limite_lote"]}. Divídalo por meses.'
        )})
    if not resumen['puede_confirmar']:
        raise ValidationError({
            'importacion': (
                'No se puede confirmar: hay comprobantes con error o en conflicto, o no hay nada nuevo. '
                'Revise la previsualización.'
            ),
            'resumen': resumen,
        })

    tipos_operacion = {t.codigo_interno: t for t in TipoOperacion.objects.filter(codigo_interno__in=OPERACION_INTERNA.values())}
    faltan = set(OPERACION_INTERNA.values()) - set(tipos_operacion)
    if faltan:
        raise ValidationError({'importacion': f'Faltan tipos de operación en el catálogo: {", ".join(sorted(faltan))}.'})

    from apps.documentos.importacion_kardex_excel import _periodo_de
    inicio = time.monotonic()
    creados = {}
    completados = {}
    terceros = _Terceros(empresa_id)
    tasas = {}
    unidades = {}

    with transaction.atomic():
        lote = ImportacionLote.objects.create(
            empresa_id=empresa_id, formato='ENTRADAS_SALIDAS', almacen=almacen, creado_por=usuario,
            resumen={'estado': 'procesando'},
        )
        ImportacionArchivo.objects.bulk_create([
            ImportacionArchivo(
                lote=lote, empresa_id=empresa_id, nombre=n[:255], sha256=h,
                filas=sum(1 for f in resultado['filas'] if f['archivo'] == n),
            )
            for n, _, h in contenidos
        ])

        try:
            por_procesar = sum(1 for c, _ in ctx['ordenados'] if ctx['estados'][c] in ('NUEVO', 'COMPLETAR'))
            procesados = 0
            if on_progreso and por_procesar:
                on_progreso('GRABANDO_COMPROBANTES', f'Grabando comprobantes (0/{por_procesar})...', 0, por_procesar)
            with modo_lote_kardex(empresa_id=empresa_id, usuario_id=usuario.id):
                for clave, lineas in ctx['ordenados']:
                    if ctx['estados'][clave] == 'COMPLETAR':
                        try:
                            completados[clave] = _completar_comprobante(
                                empresa_id=empresa_id, usuario=usuario, lote=lote,
                                existente_id=ctx['existentes'][clave].id, lineas=lineas, ctx=ctx,
                                almacen=almacen, tipos_operacion=tipos_operacion,
                            )
                        except ValidationError as exc:
                            raise ValidationError({
                                'importacion': f'No se grabó nada. No se pudo completar {_etiqueta(lineas)}: {_mensaje(exc)}',
                            })
                        procesados += 1
                        if on_progreso:
                            on_progreso(
                                'GRABANDO_COMPROBANTES',
                                f'Grabando comprobantes ({procesados}/{por_procesar})...',
                                procesados, por_procesar,
                            )
                        continue
                    if ctx['estados'][clave] != 'NUEVO':
                        continue
                    primera = lineas[0]
                    try:
                        documento_origen = None
                        origen = ctx['origenes'].get(clave)
                        if origen and origen['fuente'] == 'EXCEL':
                            documento_origen = creados.get(origen['_clave']) or ctx['existentes'].get(origen['_clave'])

                        detalles = []
                        for i, l in enumerate(lineas):
                            producto = ctx['productos'][l.codigo]
                            if producto.id not in unidades:
                                unidades[producto.id] = producto.unidades.get(es_base=True)
                            detalle_origen = None
                            if l.origen and l.origen[0] == 'EXCEL' and l.origen[1] in creados:
                                detalle_origen = DocumentoDetalle.objects.get(documento=creados[l.origen[1]], linea=l.origen[2] + 1)
                            elif l.origen and l.origen[0] == 'EXCEL':
                                # El origen ya estaba registrado (YA_EXISTE): se usa su línea del mismo producto y cantidad.
                                detalle_origen = DocumentoDetalle.objects.filter(
                                    documento=ctx['existentes'][l.origen[1]], producto=producto, cantidad_original=l.cantidad,
                                    revertida_en__isnull=True,
                                ).select_related('documento').first()
                            elif l.origen and l.origen[0] == 'SISTEMA':
                                detalle_origen = DocumentoDetalle.objects.select_related('documento').get(pk=l.origen[1])
                            if detalle_origen and documento_origen is None:
                                documento_origen = detalle_origen.documento

                            if l.operacion == '02':
                                precio = l.costo_unitario
                            elif l.operacion == '01':
                                precio = l.precio_unitario if l.precio_unitario is not None else CERO
                            else:
                                precio = detalle_origen.precio_unitario if detalle_origen else CERO
                            afectacion = producto.afectacion_igv_defecto or GRAVADO
                            if l.fecha not in tasas:
                                tasas[l.fecha] = tasa_igv(empresa_id, l.fecha)
                            base = precio * l.cantidad
                            igv = igv_esperado(base, tasas[l.fecha]) if afectacion == GRAVADO else CERO
                            if afectacion in SIN_IGV:
                                igv = CERO
                            detalles.append({
                                'producto': producto, 'producto_unidad': unidades[producto.id], 'almacen': almacen,
                                'tipo_operacion': tipos_operacion[OPERACION_INTERNA[l.operacion]],
                                'cantidad_original': l.cantidad, 'precio_unitario': precio, 'igv': igv,
                                'afectacion_igv': afectacion, 'detalle_origen': detalle_origen,
                                'linea': i + 1,
                            })

                        if documento_origen is not None:
                            tercero = documento_origen.tercero
                        elif primera.ruc:
                            tercero = terceros.por_documento(
                                primera.ruc, primera.razon_social, 'proveedor' if primera.clase == 'COMPRA' else 'cliente',
                            )
                        elif primera.clase == 'VENTA' and primera.tipo == '01':
                            tercero = terceros.varios()
                        else:
                            tercero = None

                        cabecera = {
                            'clase': primera.clase,
                            'periodo': _periodo_de(ctx['periodos'], primera.fecha),
                            'tercero': tercero,
                            'tipo_comprobante': ctx['tipos'][primera.tipo],
                            'serie': primera.serie,
                            'numero': primera.numero,
                            'fecha_emision': primera.fecha,
                            'moneda_codigo': primera.moneda,
                            'documento_origen': documento_origen,
                            'origen_captura': 'IMPORTACION',
                            'importacion_lote': lote,
                            'condicion_pago': 'CONTADO',
                        }
                        if primera.clase == 'COMPRA':
                            cabecera['ruc_emisor'] = primera.ruc
                        documento = crear_documento(
                            empresa_id=empresa_id, usuario_id=usuario.id, datos_cabecera=cabecera, detalles_datos=detalles,
                        )
                        for i, l in enumerate(lineas):
                            DocumentoDetalle.objects.filter(documento=documento, linea=i + 1).update(
                                costo_unitario_importado=l.costo_unitario, costo_total_importado=l.costo_total,
                            )
                        revisar_documento(documento.id, empresa_id, usuario.id, 'REVISADO', motivo=f'Importación Excel, lote {lote.id}')
                        confirmar_documento_validacion(documento_id=documento.id, empresa_id=empresa_id, usuario_id=usuario.id)
                        documento.refresh_from_db()
                        creados[clave] = documento
                        procesados += 1
                        if on_progreso:
                            on_progreso(
                                'GRABANDO_COMPROBANTES',
                                f'Grabando comprobantes ({procesados}/{por_procesar})...',
                                procesados, por_procesar,
                            )
                    except ValidationError as exc:
                        raise ValidationError({
                            'importacion': f'No se grabó nada. El comprobante {_etiqueta(lineas)} fue rechazado: {_mensaje(exc)}',
                        })
                if on_progreso and por_procesar:
                    on_progreso('RECALCULANDO_KARDEX', 'Validando y recalculando saldos de Kardex...', por_procesar, por_procesar)
        except ValidationError as exc:
            if isinstance(exc.detail, dict) and 'importacion' in exc.detail:
                raise
            raise ValidationError({'importacion': f'No se grabó nada. Al recalcular el Kardex: {_mensaje(exc)}'})

        segundos = round(time.monotonic() - inicio, 2)
        lineas_agregadas = sum(len(v) for v in completados.values())
        lote.resumen = {
            **resumen, 'grabados': len(creados), 'completados': len(completados),
            'lineas_agregadas': lineas_agregadas, 'segundos': segundos,
            'comprobantes_completados': [
                {'comprobante': _nombre(v[0].documento), 'documento': v[0].documento_id, 'lineas': [d.linea for d in v]}
                for v in completados.values()
            ],
        }
        lote.save(update_fields=['resumen'])
        registrar_auditoria(
            empresa_id=empresa_id, usuario_id=usuario.id, accion='IMPORTAR', entidad='IMPORTACION_LOTE',
            registro_id=lote.id,
            valor_nuevo={
                'formato': lote.formato, 'archivos': [n for n, _, _ in contenidos], 'comprobantes': len(creados),
                'completados': len(completados), 'lineas_agregadas': lineas_agregadas, 'almacen': almacen.codigo,
            },
            motivo='Importación masiva de comprobantes por Excel',
        )

    return {
        'lote': lote.id,
        'comprobantes': len(creados),
        'completados': len(completados),
        'lineas_agregadas': lineas_agregadas,
        'omitidos': resumen['ya_existen'],
        'segundos': segundos,
        'resumen': lote.resumen,
    }


def _mensaje(exc):
    detalle = exc.detail
    if isinstance(detalle, dict):
        partes = []
        for campo, valor in detalle.items():
            valores = valor if isinstance(valor, list) else [valor]
            partes.append(f'{campo}: {" ".join(str(v) for v in valores)}')
        return '; '.join(partes)
    if isinstance(detalle, list):
        return ' '.join(str(v) for v in detalle)
    return str(detalle)


def _revertir_lineas(*, empresa_id, usuario, lote, motivo):
    """
    Revierte las líneas que el lote agregó a comprobantes de otros lotes: extorna sus movimientos
    (los originales no se tocan: son inalterables), resta sus importes de los totales y las marca
    revertidas. Las demás líneas del comprobante y sus movimientos quedan intactos.
    """
    from django.utils import timezone
    from apps.kardex.models import Movimiento
    from apps.kardex.services import ZERO, aplicar_movimiento, tipo_operacion_extorno

    lineas = list(
        DocumentoDetalle.objects.filter(importacion_lote=lote, revertida_en__isnull=True)
        .select_related('documento').order_by('-documento_id', '-linea')
    )
    por_documento = {}
    for d in lineas:
        por_documento.setdefault(d.documento_id, []).append(d)
    ahora = timezone.now()
    for documento_id, detalles in por_documento.items():
        documento = Documento.objects.select_for_update(of=('self',)).select_related('periodo').get(pk=documento_id)
        for detalle in detalles:
            originales = Movimiento.objects.filter(
                empresa_id=empresa_id, documento_detalle=detalle, es_extorno=False, extornos__isnull=True,
            ).select_related('valorizacion')
            for original in originales:
                tipo = tipo_operacion_extorno('SALIDA' if original.naturaleza == 'ENTRADA' else 'ENTRADA')
                aplicar_movimiento(
                    empresa_id=empresa_id, producto_id=original.producto_id, almacen_id=original.almacen_id,
                    periodo=documento.periodo, tipo_operacion=tipo, fecha=documento.fecha_emision,
                    cantidad=original.cantidad_base, usuario_id=usuario.id,
                    costo_unitario=original.valorizacion.costo_unitario_pen, valor_ajuste=None,
                    es_extorno=True, movimiento_extornado=original,
                )
            detalle.revertida_en = ahora
            detalle.save(update_fields=['revertida_en'])
            registrar_auditoria(
                empresa_id=empresa_id, usuario_id=usuario.id, accion='REVERTIR', entidad='DOCUMENTO_DETALLE',
                registro_id=detalle.id, valor_anterior={'estado': 'VIGENTE'},
                valor_nuevo={'estado': 'REVERTIDA', 'documento': documento.id, 'comprobante': _nombre(documento),
                             'linea': detalle.linea, 'lote': lote.id},
                motivo=f'Anulación del lote de importación {lote.id}: {motivo}',
            )
        if documento.estado == 'CONFIRMADO':
            antes = {'subtotal': str(documento.subtotal), 'igv': str(documento.igv), 'total': str(documento.total)}
            subtotal = sum(((d.precio_unitario or ZERO) * (d.cantidad_original or ZERO) for d in detalles), ZERO)
            igv = sum((d.igv or ZERO for d in detalles), ZERO)
            documento.subtotal = ((documento.subtotal or ZERO) - subtotal).quantize(OCHO, rounding=ROUND_HALF_UP)
            documento.igv = ((documento.igv or ZERO) - igv).quantize(OCHO, rounding=ROUND_HALF_UP)
            documento.total = (documento.subtotal + documento.igv).quantize(OCHO, rounding=ROUND_HALF_UP)
            documento.save(update_fields=['subtotal', 'igv', 'total'])
            registrar_auditoria(
                empresa_id=empresa_id, usuario_id=usuario.id, accion='REVERTIR', entidad='DOCUMENTO',
                registro_id=documento.id, valor_anterior=antes,
                valor_nuevo={'subtotal': str(documento.subtotal), 'igv': str(documento.igv), 'total': str(documento.total),
                             'lote': lote.id, 'lineas_revertidas': [d.linea for d in detalles]},
                motivo=f'Anulación del lote de importación {lote.id}: {motivo}',
            )
    return lineas


def anular_lote_importacion(*, empresa_id, lote_id, usuario, motivo, on_progreso=None) -> dict:
    """
    Anula un lote completo o nada: primero valida que todos sus comprobantes se puedan anular
    (período abierto, sin pagos, sin notas fuera del lote, sin líneas vigentes agregadas por otro
    lote) y luego anula del más reciente al más antiguo con la anulación normal, que revierte el
    Kardex. Las líneas que el lote agregó a comprobantes de otros lotes se revierten solas.
    No se borra nada.
    """
    from django.utils import timezone
    from apps.documentos.models import Documento, PagoDocumento

    motivo = (motivo or '').strip()
    if len(motivo) < 5:
        raise ValidationError({'motivo': 'Indique el motivo de la anulación (mínimo 5 caracteres).'})

    if on_progreso:
        on_progreso('VALIDANDO_ANULACION', 'Validando comprobantes y dependencias del lote...', 0, 1)

    with transaction.atomic():
        lote = ImportacionLote.objects.select_for_update().filter(pk=lote_id, empresa_id=empresa_id).first()
        if lote is None:
            raise ValidationError({'lote': 'El lote no existe o no pertenece a la empresa activa.'})
        if lote.estado == 'ANULADO':
            raise ValidationError({'lote': 'El lote ya está anulado.'})

        documentos = list(
            Documento.objects.filter(importacion_lote=lote, empresa_id=empresa_id, estado='CONFIRMADO')
            .select_related('periodo').order_by('-id')
        )
        ids = {d.id for d in documentos}
        problemas = []
        cerrados = sorted({f'{d.periodo.anio}-{d.periodo.mes:02d}' for d in documentos if d.periodo.estado == 'CERRADO'})
        if cerrados:
            problemas.append(f'Hay comprobantes en períodos cerrados ({", ".join(cerrados)}). Reabra el período antes de anular.')
        pagos = PagoDocumento.objects.filter(documento_id__in=ids, empresa_id=empresa_id, estado='VIGENTE').count()
        if pagos:
            problemas.append(f'Hay {pagos} pago(s) vigente(s) sobre comprobantes del lote. Anúlelos primero.')
        externas = (
            Documento.objects.filter(empresa_id=empresa_id, documento_origen_id__in=ids, estado='CONFIRMADO')
            .exclude(id__in=ids).values_list('serie_normalizada', 'numero_normalizado')
        )
        if externas:
            listado = ', '.join(f'{s}-{n}' for s, n in externas[:10])
            problemas.append(f'Hay notas fuera del lote que dependen de sus comprobantes: {listado}. Anúlelas primero.')

        # Líneas que OTRO lote agregó a los comprobantes de este: ese lote se anula primero.
        ajenas = {}
        for d in (DocumentoDetalle.objects.filter(documento_id__in=ids, revertida_en__isnull=True, importacion_lote__isnull=False)
                  .exclude(importacion_lote=lote).select_related('documento').order_by('importacion_lote_id', 'documento_id')):
            ajenas.setdefault(d.importacion_lote_id, set()).add(_nombre(d.documento))
        for otro, comprobantes in ajenas.items():
            listado = ', '.join(sorted(comprobantes)[:10])
            problemas.append(
                f'El lote {otro} agregó líneas a comprobantes de este lote ({listado}). '
                f'Anule primero el lote {otro}.'
            )

        # Líneas que ESTE lote agregó a comprobantes de otros lotes: se revierten solas.
        agregadas = list(
            DocumentoDetalle.objects.filter(importacion_lote=lote, revertida_en__isnull=True)
            .exclude(documento_id__in=ids).select_related('documento__periodo')
        )
        docs_completados = {d.documento_id: d.documento for d in agregadas}
        cerrados = sorted({
            f'{d.periodo.anio}-{d.periodo.mes:02d}' for d in docs_completados.values()
            if d.estado == 'CONFIRMADO' and d.periodo.estado == 'CERRADO'
        })
        if cerrados:
            problemas.append(f'El lote completó comprobantes en períodos cerrados ({", ".join(cerrados)}). Reabra el período antes de anular.')
        con_pagos = sorted({
            _nombre(d) for d in docs_completados.values()
            if d.estado == 'CONFIRMADO' and d.pagos.filter(estado='VIGENTE').exists()
        })
        if con_pagos:
            problemas.append(f'Los comprobantes completados por el lote tienen pagos vigentes ({", ".join(con_pagos[:10])}). Anúlelos primero.')
        dependientes = (
            DocumentoDetalle.objects.filter(detalle_origen__in=[d.id for d in agregadas], documento__estado='CONFIRMADO')
            .exclude(documento_id__in=ids).values_list('documento__serie_normalizada', 'documento__numero_normalizado')
        )
        if dependientes:
            listado = ', '.join(sorted({f'{s}-{n}' for s, n in dependientes})[:10])
            problemas.append(f'Hay notas fuera del lote que devuelven líneas agregadas por el lote: {listado}. Anúlelas primero.')
        if problemas:
            raise ValidationError({'lote': problemas})

        # Se anula en el orden inverso exacto al que se grabaron (que ya respetaba fecha, stock y
        # notas después de su origen): así cada salida se revierte antes que la entrada que la cubría.
        documentos.sort(key=lambda d: d.id, reverse=True)
        from apps.documentos.services import anular_documento
        try:
            total_docs = len(documentos)
            if on_progreso and total_docs:
                on_progreso('ANULANDO_COMPROBANTES', f'Anulando comprobantes (0/{total_docs})...', 0, total_docs)
            with modo_lote_kardex(empresa_id=empresa_id, usuario_id=usuario.id):
                for idx, documento in enumerate(documentos, start=1):
                    try:
                        anular_documento(documento.id, empresa_id, usuario.id, f'Anulación del lote de importación {lote.id}: {motivo}')
                    except ValidationError as exc:
                        raise ValidationError({'lote': (
                            f'No se anuló nada. El comprobante {documento.serie_normalizada}-{documento.numero_normalizado} '
                            f'no se pudo anular: {_mensaje(exc)}'
                        )})
                    if on_progreso:
                        on_progreso('ANULANDO_COMPROBANTES', f'Anulando comprobantes ({idx}/{total_docs})...', idx, total_docs)
                if on_progreso:
                    on_progreso('RECALCULANDO_KARDEX', 'Revirtiendo líneas y recalculando saldos de Kardex...', total_docs, total_docs or 1)
                revertidas = _revertir_lineas(empresa_id=empresa_id, usuario=usuario, lote=lote, motivo=motivo)
        except ValidationError as exc:
            if isinstance(exc.detail, dict) and 'lote' in exc.detail:
                raise
            raise ValidationError({'lote': f'No se anuló nada. Al recalcular el Kardex: {_mensaje(exc)}'})

        lote.estado = 'ANULADO'
        lote.anulado_por = usuario
        lote.anulado_en = timezone.now()
        lote.motivo_anulacion = motivo[:500]
        lote.save(update_fields=['estado', 'anulado_por', 'anulado_en', 'motivo_anulacion'])
        registrar_auditoria(
            empresa_id=empresa_id, usuario_id=usuario.id, accion='ANULAR', entidad='IMPORTACION_LOTE',
            registro_id=lote.id, valor_anterior={'estado': 'CONFIRMADO'},
            valor_nuevo={'estado': 'ANULADO', 'comprobantes': len(documentos), 'lineas_revertidas': len(revertidas)},
            motivo=motivo,
        )
    return {
        'lote': lote.id, 'estado': lote.estado, 'comprobantes_anulados': len(documentos),
        'lineas_revertidas': len(revertidas),
        'comprobantes_revertidos': sorted({_nombre(d.documento) for d in revertidas}),
    }
