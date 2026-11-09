"""
Reglas de negocio centralizadas de documentos comerciales (CON-007).

La misma validación se ejecuta al CREAR el documento (servicio) y nuevamente al
CONFIRMARLO (motor Kardex) dentro de la transacción y con el origen bloqueado.

Matriz clase × comprobante → naturalezas permitidas por línea:

| Documento                 | ENTRADA | SALIDA | AJUSTE_VALOR                      |
|---------------------------|---------|--------|-----------------------------------|
| Compra (factura/boleta)   | sí      | no     | no                                |
| Venta (factura/boleta)    | no      | sí     | no                                |
| NC de compra              | no      | sí (devolución al proveedor) | sí (descuento: resta valor) |
| ND de compra              | no      | no     | sí (cargo: suma valor)            |
| NC de venta               | sí (devolución del cliente) | no | solo si NO afecta Kardex     |
| ND de venta               | no      | no     | solo si NO afecta Kardex          |

Interpretación conservadora (documentada en el reporte del Bloque 2): un
descuento o cargo sobre una VENTA no modifica el costo del inventario, por eso
su ajuste de valor solo se acepta con afecta_kardex=False.

Contexto comercial (Bloque 12), se valida ANTES de la matriz y sale del catálogo:
- Solo operaciones comerciales: `es_interna=False` y `origen_requerido` DOCUMENTO o
  MOV_ORIGEN. Las de notas internas, transferencias, saldo inicial, motor y extornos
  (NOTA_INTERNA, TRANSFERENCIA, SALDO_INICIAL, MOTOR, MOV_EXTORNADO) tienen su propio módulo.
- Movimiento físico (ENTRADA/SALIDA): en factura/boleta es la operación del documento
  (origen DOCUMENTO: COMPRA, BONIFICACION, VENTA); en una nota es una devolución (origen
  MOV_ORIGEN: DEVOLUCION_COMPRA, DEVOLUCION_VENTA), que además exige detalle_origen.
- Ajuste de valor: origen DOCUMENTO, con la matriz de arriba.
Es la misma regla que ya aplicaba la captura XML (clasificacion_captura.OPERACION_POR_CASO).
"""
from decimal import Decimal

from django.db.models import Sum
from rest_framework.exceptions import ValidationError

NATURALEZAS_FISICAS = ('ENTRADA', 'SALIDA')
ORIGENES_COMERCIALES = ('DOCUMENTO', 'MOV_ORIGEN')


def _validar_contexto_comercial(*, tipo_comprobante, tipo_operacion, nombre, linea_num):
    codigo = tipo_operacion.codigo_interno
    if tipo_operacion.es_interna or tipo_operacion.origen_requerido not in ORIGENES_COMERCIALES:
        raise ValidationError({
            'detalles': (
                f"Línea {linea_num}: la operación '{codigo}' es de uso interno "
                f"(origen {tipo_operacion.origen_requerido}) y no puede usarse en {nombre}. "
                'Regístrela en su módulo (notas internas, transferencias o saldos iniciales).'
            )
        })
    if tipo_operacion.naturaleza not in NATURALEZAS_FISICAS:
        return
    origen_esperado = 'MOV_ORIGEN' if tipo_comprobante.es_nota else 'DOCUMENTO'
    if tipo_operacion.origen_requerido != origen_esperado:
        detalle = (
            'en una nota el movimiento físico es una devolución: use la operación de devolución'
            if tipo_comprobante.es_nota
            else 'una devolución solo se registra con una Nota de Crédito vinculada al comprobante de origen'
        )
        raise ValidationError({
            'detalles': f"Línea {linea_num}: la operación '{codigo}' no es válida para {nombre} ({detalle})."
        })


def _regla_linea(clase, tipo_comprobante):
    efecto = tipo_comprobante.efecto_nota if tipo_comprobante.es_nota else 'NINGUNO'
    return {
        ('COMPRA', 'NINGUNO'): {'ENTRADA': 'siempre'},
        ('VENTA', 'NINGUNO'): {'SALIDA': 'siempre'},
        ('COMPRA', 'CREDITO'): {'SALIDA': 'siempre', 'AJUSTE_VALOR': 'siempre'},
        ('COMPRA', 'DEBITO'): {'AJUSTE_VALOR': 'siempre'},
        ('VENTA', 'CREDITO'): {'ENTRADA': 'siempre', 'AJUSTE_VALOR': 'sin_kardex'},
        ('VENTA', 'DEBITO'): {'AJUSTE_VALOR': 'sin_kardex'},
    }.get((clase, efecto))


def _nombre_documento(clase, tipo_comprobante):
    if not tipo_comprobante.es_nota:
        return f'un comprobante de {clase.lower()}'
    tipo = 'Nota de Crédito' if tipo_comprobante.efecto_nota == 'CREDITO' else 'Nota de Débito'
    return f'una {tipo} de {clase.lower()}'


def validar_naturaleza_linea(*, clase, tipo_comprobante, tipo_operacion, linea_num):
    if tipo_comprobante.es_nota and tipo_comprobante.efecto_nota not in ('CREDITO', 'DEBITO'):
        raise ValidationError({'tipo_comprobante': 'La nota no tiene un efecto (CRÉDITO o DÉBITO) configurado.'})
    regla = _regla_linea(clase, tipo_comprobante) or {}
    condicion = regla.get(tipo_operacion.naturaleza)
    nombre = _nombre_documento(clase, tipo_comprobante)
    if condicion is None:
        # Primero la naturaleza (mensaje de siempre: COMPRA + VENTA, etc.).
        permitidas = ', '.join(sorted(regla)) or 'ninguna'
        raise ValidationError({
            'detalles': (
                f"Línea {linea_num}: la operación '{tipo_operacion.codigo_interno}' "
                f"(naturaleza {tipo_operacion.naturaleza}) no es válida para {nombre}. "
                f"Naturalezas permitidas: {permitidas}."
            )
        })
    # Bloque 12: con la naturaleza correcta, además debe ser una operación comercial del flujo
    # de este comprobante (antes COMPRA + AJUSTE_INGRESO o + SALDO_INICIAL se aceptaban).
    _validar_contexto_comercial(
        tipo_comprobante=tipo_comprobante, tipo_operacion=tipo_operacion, nombre=nombre, linea_num=linea_num,
    )
    if condicion == 'sin_kardex' and tipo_operacion.afecta_kardex:
        raise ValidationError({
            'detalles': (
                f"Línea {linea_num}: en {nombre} un ajuste de valor no puede afectar el Kardex "
                "(no modifica el costo del inventario). Use una operación que no afecte Kardex."
            )
        })


def validar_documento_origen(*, empresa_id, clase, tipo_comprobante, tercero_id, ruc_emisor,
                             moneda_codigo, fecha_emision, origen):
    """Valida la cabecera de una nota contra su documento de origen."""
    if not tipo_comprobante.es_nota:
        if origen is not None:
            raise ValidationError({'documento_origen': 'Solo las Notas de Crédito o Débito admiten documento de origen.'})
        return
    if origen is None:
        raise ValidationError({
            'documento_origen': 'Las Notas de Crédito o Débito deben estar vinculadas a un documento de origen.'
        })
    if origen.empresa_id != empresa_id:
        raise ValidationError({'documento_origen': 'El documento de origen no existe o no pertenece a la empresa activa.'})
    if origen.tipo_comprobante.es_nota:
        raise ValidationError({'documento_origen': 'El documento de origen no puede ser otra nota.'})
    if origen.estado != 'CONFIRMADO':
        raise ValidationError({
            'documento_origen': (
                f'El documento de origen está en estado {origen.estado}. '
                'Solo se admiten notas sobre documentos CONFIRMADOS.'
            )
        })
    if origen.clase != clase:
        raise ValidationError({
            'documento_origen': f'La nota es de {clase} y el documento de origen es de {origen.clase}.'
        })
    if origen.tercero_id != tercero_id:
        raise ValidationError({'tercero': 'La nota debe emitirse al mismo tercero del documento de origen.'})
    if clase == 'COMPRA' and origen.ruc_emisor != ruc_emisor:
        raise ValidationError({'ruc_emisor': 'La nota de compra debe tener el mismo RUC emisor del documento de origen.'})
    if origen.moneda_codigo_id != moneda_codigo:
        raise ValidationError({
            'moneda_codigo': (
                f'La nota está en {moneda_codigo} y el documento de origen en {origen.moneda_codigo_id}. '
                'Deben usar la misma moneda.'
            )
        })
    if fecha_emision < origen.fecha_emision:
        raise ValidationError({
            'fecha_emision': 'La fecha de la nota no puede ser anterior a la del documento de origen.'
        })


def validar_linea_nota(*, tipo_comprobante, tipo_operacion, producto_id, detalle_origen, origen, linea_num):
    """Valida el vínculo de una línea de nota con la línea del documento de origen."""
    if not tipo_comprobante.es_nota:
        if detalle_origen is not None:
            raise ValidationError({
                'detalles': f'Línea {linea_num}: El detalle de origen solo se admite en Notas de Crédito o Débito.'
            })
        return
    es_fisica = tipo_operacion.naturaleza in NATURALEZAS_FISICAS and tipo_operacion.afecta_kardex
    if es_fisica and detalle_origen is None:
        raise ValidationError({
            'detalles': (
                f'Línea {linea_num}: una devolución con movimiento físico debe indicar la línea '
                'del documento de origen (detalle_origen).'
            )
        })
    if detalle_origen is None:
        return
    if origen is None or detalle_origen.documento_id != origen.id:
        raise ValidationError({
            'detalles': f'Línea {linea_num}: la línea de origen no pertenece al documento de origen de la nota.'
        })
    if producto_id is None or detalle_origen.producto_id != producto_id:
        raise ValidationError({
            'detalles': f'Línea {linea_num}: el producto no coincide con el de la línea de origen.'
        })


def cantidad_ya_devuelta(detalle_origen_id, *, excluir_documento_id=None) -> Decimal:
    """Cantidad base ya devuelta por notas CONFIRMADAS con movimiento físico."""
    from apps.documentos.models import DocumentoDetalle
    qs = DocumentoDetalle.objects.filter(
        detalle_origen_id=detalle_origen_id,
        documento__estado='CONFIRMADO',
        documento__tipo_comprobante__es_nota=True,
        tipo_operacion__naturaleza__in=NATURALEZAS_FISICAS,
        afecta_kardex_aplicado=True,
    )
    if excluir_documento_id is not None:
        qs = qs.exclude(documento_id=excluir_documento_id)
    return qs.aggregate(total=Sum('cantidad_base'))['total'] or Decimal('0')


def validar_cantidades_devolucion(lineas, *, excluir_documento_id=None):
    """
    lineas: iterable de (linea_num, detalle_origen, tipo_operacion, cantidad_base).
    La suma de lo nuevo + lo ya devuelto no puede superar la cantidad original.
    """
    acumulado = {}
    for linea_num, detalle_origen, tipo_operacion, cantidad_base in lineas:
        if detalle_origen is None or tipo_operacion.naturaleza not in NATURALEZAS_FISICAS:
            continue
        clave = detalle_origen.id
        acumulado.setdefault(clave, [detalle_origen, Decimal('0'), []])
        acumulado[clave][1] += cantidad_base or Decimal('0')
        acumulado[clave][2].append(linea_num)
    for detalle_origen, nueva, lineas_num in acumulado.values():
        original = detalle_origen.cantidad_base or Decimal('0')
        devuelta = cantidad_ya_devuelta(detalle_origen.id, excluir_documento_id=excluir_documento_id)
        disponible = original - devuelta
        if nueva > disponible:
            raise ValidationError({
                'detalles': (
                    f"Línea {', '.join(str(n) for n in lineas_num)}: se intenta devolver {nueva.normalize():f} "
                    f"y solo quedan {disponible.normalize():f} disponibles de la línea de origen #{detalle_origen.linea} "
                    f"(original {original.normalize():f}, ya devuelto {devuelta.normalize():f})."
                )
            })
