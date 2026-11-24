"""
Importación Excel "Entradas y salidas" — paso 2: grabar.

Vuelve a analizar los archivos desde cero (nunca confía en la previsualización del cliente) y, si
no hay errores ni conflictos, crea cada comprobante por el flujo normal crear → revisar →
confirmar, en orden de fecha, todo o nada, dentro de un lote anulable.
"""
import hashlib
import io
import time

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import registrar_auditoria
from apps.catalogos.models import TipoOperacion
from apps.documentos.afectacion_igv import GRAVADO, SIN_IGV, igv_esperado, tasa_igv
from apps.documentos.importacion_kardex_excel import CERO, _analizar
from apps.documentos.models import DocumentoDetalle, ImportacionArchivo, ImportacionLote
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


def confirmar_importacion_kardex(*, empresa_id, usuario, archivos, almacen_id=None, proveedores=None) -> dict:
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
            f'El lote tiene {resumen["nuevos"]} comprobantes nuevos y el máximo es {resumen["limite_lote"]}. '
            'Divídalo por meses.'
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
            with modo_lote_kardex(empresa_id=empresa_id, usuario_id=usuario.id):
                for clave, lineas in ctx['ordenados']:
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
                    except ValidationError as exc:
                        raise ValidationError({
                            'importacion': f'No se grabó nada. El comprobante {_etiqueta(lineas)} fue rechazado: {_mensaje(exc)}',
                        })
        except ValidationError as exc:
            if isinstance(exc.detail, dict) and 'importacion' in exc.detail:
                raise
            raise ValidationError({'importacion': f'No se grabó nada. Al recalcular el Kardex: {_mensaje(exc)}'})

        segundos = round(time.monotonic() - inicio, 2)
        lote.resumen = {**resumen, 'grabados': len(creados), 'segundos': segundos}
        lote.save(update_fields=['resumen'])
        registrar_auditoria(
            empresa_id=empresa_id, usuario_id=usuario.id, accion='IMPORTAR', entidad='IMPORTACION_LOTE',
            registro_id=lote.id,
            valor_nuevo={
                'formato': lote.formato, 'archivos': [n for n, _, _ in contenidos], 'comprobantes': len(creados),
                'almacen': almacen.codigo,
            },
            motivo='Importación masiva de comprobantes por Excel',
        )

    return {
        'lote': lote.id,
        'comprobantes': len(creados),
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


def _liberar_numero(documento, lote_id):
    """
    El número de un comprobante anulado sigue ocupando la clave única del sistema. Para poder
    volver a importar el mismo Excel después de anular el lote, el comprobante anulado conserva
    su serie y número originales (campos `serie` y `numero`) y solo su clave normalizada recibe
    la marca del lote anulado.
    """
    marca = f'~A{lote_id}'
    documento.numero_normalizado = f'{documento.numero_normalizado}{marca}'[:50]
    documento.save(update_fields=['numero_normalizado'])


def anular_lote_importacion(*, empresa_id, lote_id, usuario, motivo) -> dict:
    """
    Anula un lote completo o nada: primero valida que todos sus comprobantes se puedan anular
    (período abierto, sin pagos, sin notas fuera del lote) y luego anula del más reciente al más
    antiguo con la anulación normal, que revierte el Kardex. No se borra nada.
    """
    from django.utils import timezone
    from apps.documentos.models import Documento, PagoDocumento

    motivo = (motivo or '').strip()
    if len(motivo) < 5:
        raise ValidationError({'motivo': 'Indique el motivo de la anulación (mínimo 5 caracteres).'})

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
        if problemas:
            raise ValidationError({'lote': problemas})

        # Se anula en el orden inverso exacto al que se grabaron (que ya respetaba fecha, stock y
        # notas después de su origen): así cada salida se revierte antes que la entrada que la cubría.
        documentos.sort(key=lambda d: d.id, reverse=True)
        from apps.documentos.services import anular_documento
        try:
            with modo_lote_kardex(empresa_id=empresa_id, usuario_id=usuario.id):
                for documento in documentos:
                    try:
                        anular_documento(documento.id, empresa_id, usuario.id, f'Anulación del lote de importación {lote.id}: {motivo}')
                    except ValidationError as exc:
                        raise ValidationError({'lote': (
                            f'No se anuló nada. El comprobante {documento.serie_normalizada}-{documento.numero_normalizado} '
                            f'no se pudo anular: {_mensaje(exc)}'
                        )})
        except ValidationError as exc:
            if isinstance(exc.detail, dict) and 'lote' in exc.detail:
                raise
            raise ValidationError({'lote': f'No se anuló nada. Al recalcular el Kardex: {_mensaje(exc)}'})

        for documento in Documento.objects.filter(importacion_lote=lote):
            _liberar_numero(documento, lote.id)

        lote.estado = 'ANULADO'
        lote.anulado_por = usuario
        lote.anulado_en = timezone.now()
        lote.motivo_anulacion = motivo[:500]
        lote.save(update_fields=['estado', 'anulado_por', 'anulado_en', 'motivo_anulacion'])
        registrar_auditoria(
            empresa_id=empresa_id, usuario_id=usuario.id, accion='ANULAR', entidad='IMPORTACION_LOTE',
            registro_id=lote.id, valor_anterior={'estado': 'CONFIRMADO'},
            valor_nuevo={'estado': 'ANULADO', 'comprobantes': len(documentos)}, motivo=motivo,
        )
    return {'lote': lote.id, 'estado': lote.estado, 'comprobantes_anulados': len(documentos)}
