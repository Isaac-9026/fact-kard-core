"""
Clasificación de comprobantes capturados (XML/OCR) — Bloque 3.

La clase (COMPRA/VENTA) y el tipo de operación se deciden SOLO con datos reales
del comprobante; si no alcanzan para decidir con seguridad, se rechaza con un
mensaje claro para registro manual. Nunca se elige un tipo "parecido".

Fuentes: Tabla 10 (tipo de comprobante) y Catálogos 09/10 de SUNAT (motivo de la
nota de crédito / débito electrónica), R.S. 245-2017/SUNAT, Anexo E.
"""
from rest_framework.exceptions import ValidationError

TIPOS_SOPORTADOS = {'01': 'FACTURA', '03': 'BOLETA', '07': 'NOTA DE CREDITO', '08': 'NOTA DE DEBITO'}

# Catálogo 09 — Nota de crédito
NC_DEVOLUCION = {'06': 'Devolución total', '07': 'Devolución por ítem'}
NC_VALOR = {'04': 'Descuento global', '05': 'Descuento por ítem', '09': 'Disminución en el valor'}
NC_NO_DETERMINABLE = {
    '01': 'Anulación de la operación', '02': 'Anulación por error en el RUC',
    '03': 'Corrección por error en la descripción', '08': 'Bonificación', '10': 'Otros conceptos',
}
# Catálogo 10 — Nota de débito
ND_VALOR = {'02': 'Aumento en el valor'}
ND_NO_COSTO = {'01': 'Intereses por mora', '03': 'Penalidades / otros conceptos'}

# (clase, tipo_comprobante, grupo de motivo) → codigo_interno del tipo de operación
OPERACION_POR_CASO = {
    ('COMPRA', '01', None): 'COMPRA',
    ('COMPRA', '03', None): 'COMPRA',
    ('VENTA', '01', None): 'VENTA',
    ('VENTA', '03', None): 'VENTA',
    ('COMPRA', '07', 'DEVOLUCION'): 'DEVOLUCION_COMPRA',
    ('COMPRA', '07', 'VALOR'): 'NC_DESCUENTO_COMPRA',
    ('VENTA', '07', 'DEVOLUCION'): 'DEVOLUCION_VENTA',
    ('VENTA', '07', 'VALOR'): 'NC_VENTA_SIN_DEVOLUCION',
    ('COMPRA', '08', 'VALOR'): 'ND_CARGO_COMPRA',
    ('VENTA', '08', 'VALOR'): 'ND_CARGO_VENTA',
    ('VENTA', '08', 'NO_COSTO'): 'ND_CARGO_VENTA',  # en venta ninguna ND toca el Kardex
}


def _solo_digitos(valor):
    return ''.join(ch for ch in (valor or '') if ch.isdigit())


def clasificar_comprobante(*, cabecera, ruc_empresa):
    """
    Devuelve {'clase', 'tipo_comprobante', 'codigo_operacion', 'motivo',
    'contraparte_documento', 'contraparte_nombre'} o lanza ValidationError.
    """
    tipo = (cabecera.get('tipo_comprobante') or '').strip()
    if tipo not in TIPOS_SOPORTADOS:
        raise ValidationError({
            'tipo_comprobante': (
                f"Tipo de comprobante '{tipo or '(vacío)'}' no reconocido para captura. "
                'Solo se admiten 01 Factura, 03 Boleta, 07 Nota de crédito y 08 Nota de débito.'
            )
        })

    ruc_emisor = _solo_digitos(cabecera.get('ruc_emisor'))
    receptor = _solo_digitos(cabecera.get('ruc_cliente'))
    if not ruc_emisor:
        raise ValidationError({'ruc_emisor': 'El comprobante no indica el RUC del emisor.'})
    es_emisor = ruc_emisor == ruc_empresa
    es_receptor = receptor == ruc_empresa
    if es_emisor and es_receptor:
        raise ValidationError({'ruc_cliente': 'El emisor y el receptor son la misma empresa; registre el documento manualmente.'})
    if es_emisor:
        clase, contraparte = 'VENTA', receptor
        nombre = (cabecera.get('razon_social_cliente') or '').strip()
    elif es_receptor:
        clase, contraparte = 'COMPRA', ruc_emisor
        nombre = (cabecera.get('razon_social_emisor') or '').strip()
    else:
        raise ValidationError({
            'ruc_cliente': (
                f'El comprobante no corresponde a la empresa activa (RUC {ruc_empresa}): '
                f"emisor {ruc_emisor}, receptor {receptor or '(no indicado)'}."
            )
        })

    motivo = (cabecera.get('motivo_nota') or '').strip()
    grupo = None
    if tipo == '07':
        if motivo in NC_DEVOLUCION:
            grupo = 'DEVOLUCION'
        elif motivo in NC_VALOR:
            grupo = 'VALOR'
        else:
            descripcion = NC_NO_DETERMINABLE.get(motivo, 'motivo no indicado o desconocido')
            raise ValidationError({
                'motivo_nota': (
                    f"Nota de crédito con motivo '{motivo or '-'}' ({descripcion}): no se puede determinar "
                    'si hubo devolución física o solo ajuste de valor. Regístrela manualmente.'
                )
            })
    elif tipo == '08':
        if motivo in ND_VALOR:
            grupo = 'VALOR'
        elif clase == 'VENTA' and motivo in ND_NO_COSTO:
            grupo = 'NO_COSTO'
        else:
            descripcion = ND_NO_COSTO.get(motivo, 'motivo no indicado o desconocido')
            raise ValidationError({
                'motivo_nota': (
                    f"Nota de débito de compra con motivo '{motivo or '-'}' ({descripcion}): no corresponde "
                    'a un mayor costo del inventario. Regístrela manualmente.'
                )
            })

    codigo = OPERACION_POR_CASO.get((clase, tipo, grupo))
    if codigo is None:  # defensa: la tabla cubre todos los casos aceptados arriba
        raise ValidationError({'tipo_comprobante': 'Combinación de comprobante no soportada para captura.'})
    return {
        'clase': clase, 'tipo_comprobante': tipo, 'codigo_operacion': codigo, 'motivo': motivo or None,
        'contraparte_documento': contraparte, 'contraparte_nombre': nombre,
    }
