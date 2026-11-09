"""
Bloque 17A — reglas tributarias previas a la emisión electrónica SUNAT.

Complementa (no reemplaza) `documentos/reglas.py`:
- `reglas.py`: reglas comerciales/contables (naturaleza de las líneas, documento de origen,
  devoluciones). Se aplican al crear y confirmar; deciden Kardex, stock y CPP.
- este módulo: requisitos que exigirá la futura factura/boleta/nota electrónica (emisor,
  establecimiento, serie F/B, cliente, motivo catálogo 09/10, unidades, afectación, totales).

Solo LEE. No modifica datos, no genera XML, no firma, no envía y no mueve el Kardex.
El resultado es un estado DERIVADO (no se guarda): LISTO_PARA_EMISION o NO_PREPARADO.

Fuentes: Reglamento de Comprobantes de Pago (R.S. 007-99/SUNAT, art. 8: identificación del
adquirente en boletas mayores a S/ 700) y Anexo 8 de la R.S. 097-2012/SUNAT (catálogos 01, 03,
06, 07, 09 y 10; serie F para facturas y sus notas, B para boletas y sus notas).
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from apps.documentos.afectacion_igv import CATALOGO_07, CODIGOS_GRATUITOS, GRATUITO
from apps.inventario.documentos_identidad import (
    CODIGOS_DOCUMENTO_IDENTIDAD, RUC, SIN_RUC, es_ruc_valido, validar_documento_identidad,
)

LISTO_PARA_EMISION = 'LISTO_PARA_EMISION'
NO_PREPARADO = 'NO_PREPARADO'

# Catálogo 01 (tipo de documento) que emite el sistema.
FACTURA, BOLETA, NOTA_CREDITO, NOTA_DEBITO = '01', '03', '07', '08'
TIPOS_EMITIBLES = {FACTURA: 'Factura', BOLETA: 'Boleta de venta', NOTA_CREDITO: 'Nota de crédito',
                   NOTA_DEBITO: 'Nota de débito'}
CATALOGO_MOTIVO = {NOTA_CREDITO: '09', NOTA_DEBITO: '10'}
PREFIJO_SERIE = {FACTURA: 'F', BOLETA: 'B'}

# Catálogo 07 → afectación interna (inverso de afectacion_igv.CATALOGO_07 para las onerosas).
CODIGO_07_POR_AFECTACION = {'GRAVADO': '10', 'EXONERADO': '20', 'INAFECTO': '30', 'EXPORTACION': '40'}

# Catálogo 03 (UN/ECE Rec. 20): códigos de uso común. Uno fuera de la lista se advierte (puede
# ser válido); uno con formato imposible es un error.
CATALOGO_03_CONOCIDOS = {
    'NIU', 'ZZ', 'BX', 'PK', 'KGM', 'GRM', 'TNE', 'LTR', 'MLT', 'GLI', 'GLL', 'MTR', 'CMT', 'MTK', 'MTQ',
    'DZN', 'SET', 'PR', 'BG', 'BO', 'CA', 'CT', 'PF', 'RO', 'TU', 'HUR', 'DAY', 'MON', 'KT', 'C62', '4A',
}
FORMATO_UNIDAD = re.compile(r'^[A-Z0-9]{2,3}$')

UMBRAL_BOLETA_IDENTIFICADA = Decimal('700')   # S/: desde este importe la boleta identifica al adquirente
FORMATO_UBIGEO = re.compile(r'^(0[1-9]|1[0-9]|2[0-5])(0[1-9]|[1-9][0-9])(0[1-9]|[1-9][0-9])$')
FORMATO_ESTABLECIMIENTO = re.compile(r'^[0-9]{4}$')
MAX_CORRELATIVO = 99999999
OCHO = Decimal('0.00000001')


def q8(valor):
    return Decimal(valor or 0).quantize(OCHO, rounding=ROUND_HALF_UP)


def ubigeo_valido(valor):
    """6 dígitos INEI: departamento 01-25, provincia y distrito 01-99."""
    return bool(FORMATO_UBIGEO.match(valor or ''))


# ---- Emisor y establecimiento -------------------------------------------------------------

def validar_emisor(empresa):
    """(errores, advertencias) de los datos fiscales del emisor (la empresa)."""
    errores, advertencias = [], []
    if not es_ruc_valido(empresa.ruc):
        errores.append(f'El RUC del emisor ({empresa.ruc}) no es válido (11 dígitos con dígito verificador).')
    if not (empresa.razon_social or '').strip():
        errores.append('Falta la razón social del emisor.')
    if not (empresa.direccion or '').strip():
        errores.append('Falta el domicilio fiscal del emisor.')
    if not empresa.ubigeo:
        errores.append('Falta ubigeo del emisor.')
    elif not ubigeo_valido(empresa.ubigeo):
        errores.append(f'El ubigeo del emisor ({empresa.ubigeo}) no es válido (6 dígitos INEI).')
    for campo, etiqueta in (('departamento', 'el departamento'), ('provincia', 'la provincia'), ('distrito', 'el distrito')):
        if not (getattr(empresa, campo) or '').strip():
            errores.append(f'Falta {etiqueta} del domicilio fiscal del emisor.')
    if (empresa.codigo_pais or '') != 'PE':
        errores.append(f"El código de país del emisor debe ser PE (tiene '{empresa.codigo_pais}').")
    if empresa.estado != 'ACTIVA':
        errores.append('La empresa emisora está inactiva.')
    if not (empresa.nombre_comercial or '').strip():
        advertencias.append('El emisor no tiene nombre comercial (opcional).')
    return errores, advertencias


def establecimiento_es_principal(establecimiento):
    config = getattr(establecimiento.empresa, 'configuracion', None)
    if config is not None and config.establecimiento_principal_id:
        return config.establecimiento_principal_id == establecimiento.id
    return establecimiento.codigo_sunat == '0000'


def validar_establecimiento(establecimiento, empresa_id):
    errores, advertencias = [], []
    if establecimiento.empresa_id != empresa_id:
        return ['El establecimiento no pertenece a la empresa emisora.'], []
    nombre = f'{establecimiento.codigo_sunat} — {establecimiento.nombre}'
    if not establecimiento.activo:
        errores.append(f'El establecimiento {nombre} está inactivo.')
    if not FORMATO_ESTABLECIMIENTO.match(establecimiento.codigo_sunat or ''):
        errores.append(f"El código SUNAT del establecimiento ({establecimiento.codigo_sunat}) debe tener 4 dígitos "
                       '(0000 = domicilio fiscal).')
    if establecimiento.ubigeo and not ubigeo_valido(establecimiento.ubigeo):
        errores.append(f'El ubigeo del establecimiento {nombre} no es válido.')
    if not establecimiento_es_principal(establecimiento):
        if not (establecimiento.direccion or '').strip():
            advertencias.append(f'El establecimiento anexo {nombre} no tiene dirección.')
        if not establecimiento.ubigeo:
            advertencias.append(f'El establecimiento anexo {nombre} no tiene ubigeo.')
    return errores, advertencias


# ---- Piezas del comprobante ----------------------------------------------------------------

def codigo_catalogo_07(linea):
    """Código del catálogo 07 de la línea o None si no se puede determinar sin adivinar."""
    if linea.codigo_afectacion_igv:
        return linea.codigo_afectacion_igv if linea.codigo_afectacion_igv in CATALOGO_07 else None
    afectacion = linea.afectacion_igv or ('GRATUITO' if linea.es_bonificacion else 'GRAVADO')
    return CODIGO_07_POR_AFECTACION.get(afectacion)


def unidad_de_linea(linea):
    """Código de unidad de la línea: la presentación elegida o, si no hay, la unidad base del producto."""
    if linea.producto_unidad_id:
        return linea.producto_unidad.unidad_codigo_id
    if linea.producto_id:
        base = next((u for u in linea.producto.unidades.all() if u.es_base), None)
        return base.unidad_codigo_id if base else None
    return None


def tipo_base(documento):
    """Factura/boleta a la que pertenece el comprobante (la del origen si es nota)."""
    codigo = documento.tipo_comprobante.codigo_sunat
    if codigo in (NOTA_CREDITO, NOTA_DEBITO):
        origen = documento.documento_origen
        return origen.tipo_comprobante.codigo_sunat if origen is not None else None
    return codigo


def total_en_soles(documento):
    total = q8(documento.total)
    if documento.moneda_codigo_id == 'PEN':
        return total
    if documento.monto_tc:
        return q8(total * documento.monto_tc)
    return None


def _validar_serie(documento, errores, advertencias):
    codigo = documento.tipo_comprobante.codigo_sunat
    serie = documento.serie_comprobante
    base = tipo_base(documento)
    prefijo = PREFIJO_SERIE.get(base)
    texto_serie = documento.serie_normalizada or ''
    if prefijo and not re.fullmatch(rf'{prefijo}[A-Z0-9]{{3}}', texto_serie):
        que = TIPOS_EMITIBLES[codigo].lower()
        sobre = '' if codigo == base else f' de una {TIPOS_EMITIBLES[base].lower()}'
        errores.append(f"La serie '{texto_serie}' no es compatible: la {que}{sobre} usa una serie de 4 caracteres "
                       f"que empieza con {prefijo} (p. ej. {prefijo}001).")
    if serie is None:
        errores.append('El comprobante no usa una serie configurada del establecimiento (número manual). '
                       'Para la emisión electrónica el correlativo lo asigna el sistema.')
        return None
    if serie.empresa_id != documento.empresa_id:
        errores.append('La serie no pertenece a la empresa emisora.')
        return None
    if serie.tipo_comprobante_id != documento.tipo_comprobante_id:
        errores.append(f'La serie {serie.serie} está configurada para otro tipo de comprobante.')
    if not serie.activo:
        advertencias.append(f'La serie {serie.serie} está desactivada (el número ya asignado se conserva).')
    numero = (documento.numero or documento.numero_normalizado or '').strip()
    if not numero.isdigit() or not 1 <= int(numero) <= MAX_CORRELATIVO:
        errores.append(f"El número '{numero}' no es un correlativo válido (1 a {MAX_CORRELATIVO}).")
    return serie.establecimiento


def _validar_cliente(documento, errores, advertencias):
    base = tipo_base(documento)
    tercero = documento.tercero
    if base == FACTURA:
        if tercero is None:
            errores.append('La factura requiere cliente identificado con RUC.')
        elif tercero.tipo_documento != RUC or not es_ruc_valido(tercero.numero_documento):
            errores.append(f'La factura requiere cliente con RUC válido (el cliente tiene {tercero.tipo_documento}-'
                           f'{tercero.numero_documento}).')
    elif base == BOLETA:
        total_pen = total_en_soles(documento)
        if tercero is None:
            if total_pen is None:
                errores.append('Boleta en moneda extranjera sin tipo de cambio: no se puede verificar si requiere '
                               'identificar al cliente.')
            elif total_pen >= UMBRAL_BOLETA_IDENTIFICADA:
                errores.append(f'La boleta de S/ {total_pen:.2f} requiere identificar al cliente (desde S/ '
                               f'{UMBRAL_BOLETA_IDENTIFICADA:.2f}).')
            else:
                advertencias.append('Boleta a consumidor final sin identificación (permitido por debajo de S/ 700).')
            return
        if tercero.tipo_documento == SIN_RUC and total_pen is not None and total_pen < UMBRAL_BOLETA_IDENTIFICADA:
            return  # consumidor final registrado sin documento
        _tipo, _num, error = validar_documento_identidad(tercero.tipo_documento, tercero.numero_documento)
        if error:
            errores.append(f'Documento de identidad del cliente no válido: {error}')
    if tercero is not None:
        if tercero.empresa_id != documento.empresa_id:
            errores.append('El cliente no pertenece a la empresa emisora.')
        if not (tercero.razon_social or '').strip():
            errores.append('El cliente no tiene razón social / nombre.')
        if tercero.tipo_documento not in CODIGOS_DOCUMENTO_IDENTIDAD:
            errores.append(f"El tipo de documento del cliente ('{tercero.tipo_documento}') no es del catálogo 06.")


def _validar_lineas_y_totales(documento, errores, advertencias):
    lineas = list(documento.detalles.select_related('producto', 'producto_unidad', 'tipo_operacion')
                  .prefetch_related('producto__unidades').order_by('linea'))
    if not lineas:
        errores.append('El comprobante no tiene líneas.')
        return []
    subtotal = igv = Decimal('0')
    for linea in lineas:
        n = linea.linea
        cantidad, precio = q8(linea.cantidad_original), q8(linea.precio_unitario)
        if cantidad <= 0:
            errores.append(f'Línea {n}: la cantidad debe ser mayor a 0.')
        if precio < 0:
            errores.append(f'Línea {n}: el precio no puede ser negativo.')
        descripcion = (linea.descripcion_original or (linea.producto.descripcion if linea.producto else '') or '').strip()
        if not descripcion:
            errores.append(f'Línea {n}: falta la descripción del bien o servicio.')
        unidad = unidad_de_linea(linea)
        if not unidad:
            errores.append(f'Línea {n}: falta la unidad de medida.')
        elif not FORMATO_UNIDAD.match(unidad):
            errores.append(f"Línea {n}: la unidad '{unidad}' no tiene formato del catálogo 03 (UN/ECE).")
        elif unidad not in CATALOGO_03_CONOCIDOS:
            advertencias.append(f"Línea {n}: verifique que la unidad '{unidad}' exista en el catálogo 03.")
        codigo07 = codigo_catalogo_07(linea)
        gratuita = (linea.afectacion_igv or '') == GRATUITO or linea.es_bonificacion
        if codigo07 is None:
            if gratuita:
                errores.append(f'Línea {n}: operación gratuita sin código del catálogo 07 (11-16, 21 o 31-36); '
                               'selecciónelo en la línea del comprobante.')
            else:
                errores.append(f'Línea {n}: no se puede determinar el código del catálogo 07.')
        elif gratuita and codigo07 not in CODIGOS_GRATUITOS:
            errores.append(f'Línea {n}: el código {codigo07} del catálogo 07 no es de operación gratuita.')
        elif codigo07 == '17':
            errores.append(f'Línea {n}: IVAP (catálogo 07, código 17) no está soportado.')
        subtotal += precio * cantidad
        igv += q8(linea.igv)
    if q8(subtotal) != q8(documento.subtotal):
        errores.append(f'El subtotal ({q8(documento.subtotal)}) no coincide con la suma de las líneas ({q8(subtotal)}).')
    if q8(igv) != q8(documento.igv):
        errores.append(f'El IGV ({q8(documento.igv)}) no coincide con la suma de las líneas ({q8(igv)}).')
    if q8(documento.subtotal) + q8(documento.igv) != q8(documento.total):
        errores.append('El total no es igual a subtotal + IGV.')
    if q8(documento.total) <= 0:
        advertencias.append('El comprobante tiene total 0 (solo válido si toda la operación es gratuita).')
    return lineas


def _validar_nota(documento, lineas, errores, advertencias):
    codigo = documento.tipo_comprobante.codigo_sunat
    origen = documento.documento_origen
    if origen is None:
        errores.append('La nota requiere documento de origen.')
    else:
        if origen.empresa_id != documento.empresa_id:
            errores.append('El documento de origen pertenece a otra empresa.')
        elif origen.clase != 'VENTA' or origen.tipo_comprobante.codigo_sunat not in (FACTURA, BOLETA):
            errores.append('El documento de origen debe ser una factura o boleta de venta.')
        elif origen.estado != 'CONFIRMADO':
            errores.append(f'El documento de origen está {origen.estado}.')
        else:
            # Bloque 23: no basta CONFIRMADO internamente; SUNAT debe haber aceptado el origen.
            from django.conf import settings
            if 'apps.emision_electronica' in settings.INSTALLED_APPS:
                from apps.emision_electronica.coherencia import error_origen_nota
                error = error_origen_nota(origen)
                if error:
                    errores.append(error)
        if origen.empresa_id == documento.empresa_id:
            if origen.tercero_id != documento.tercero_id:
                errores.append('La nota debe tener el mismo cliente que el documento de origen.')
            if origen.moneda_codigo_id != documento.moneda_codigo_id:
                errores.append('La nota debe tener la misma moneda que el documento de origen.')
    motivo = documento.motivo_nota
    catalogo = CATALOGO_MOTIVO[codigo]
    if motivo is None:
        errores.append(f'Falta el motivo de la nota (catálogo {catalogo}).')
        return
    if motivo.catalogo != catalogo:
        errores.append(f'El motivo {motivo.codigo} no es del catálogo {catalogo}.')
        return
    if not motivo.activo:
        errores.append(f'El motivo {motivo.codigo} ({motivo.descripcion}) no está habilitado.')
    if codigo != NOTA_CREDITO or origen is None:
        return
    # Coherencia motivo ↔ líneas: solo advertencias (el efecto contable lo deciden las líneas).
    devoluciones = [x for x in lineas if x.tipo_operacion.codigo_interno == 'DEVOLUCION_VENTA']
    if motivo.codigo in ('06', '07') and not devoluciones:
        advertencias.append(f'El motivo {motivo.codigo} ({motivo.descripcion}) indica devolución, pero ninguna '
                            'línea registra devolución física.')
    if motivo.codigo in ('04', '05', '09') and devoluciones:
        advertencias.append(f'El motivo {motivo.codigo} ({motivo.descripcion}) es un ajuste de valor, pero hay '
                            'líneas de devolución física.')
    if motivo.codigo in ('01', '02', '06') and q8(documento.total) != q8(origen.total):
        advertencias.append(f'El motivo {motivo.codigo} ({motivo.descripcion}) suele ser por el total del '
                            f'comprobante de origen ({q8(origen.total)}); la nota es por {q8(documento.total)}.')


# ---- Servicio central -----------------------------------------------------------------------

def validar_para_emision_electronica(documento, *, hoy=None):
    """
    {'listo', 'estado', 'errores', 'advertencias', 'tipo_comprobante'} del documento.
    No escribe nada. `estado` es LISTO_PARA_EMISION o NO_PREPARADO (derivado).
    """
    from django.utils import timezone
    hoy = hoy or timezone.localdate()
    errores, advertencias = [], []
    codigo = documento.tipo_comprobante.codigo_sunat

    if documento.clase != 'VENTA':
        errores.append('Solo los comprobantes de venta se emiten electrónicamente (las compras las emite el proveedor).')
    if codigo not in TIPOS_EMITIBLES:
        errores.append(f'El tipo de comprobante {codigo} no se emite electrónicamente '
                       '(solo 01 factura, 03 boleta, 07 nota de crédito y 08 nota de débito).')
    if documento.estado == 'BORRADOR':
        errores.append('El comprobante está en BORRADOR: debe estar CONFIRMADO.')
    elif documento.estado == 'ANULADO':
        errores.append('El comprobante está ANULADO.')
    if documento.origen_captura != 'MANUAL':
        errores.append(f'El comprobante se capturó desde {documento.origen_captura}: ya fue emitido por otro '
                       'sistema y no se vuelve a emitir.')
    if errores and (documento.clase != 'VENTA' or codigo not in TIPOS_EMITIBLES):
        return _resultado(documento, errores, advertencias)

    empresa = documento.empresa
    e, a = validar_emisor(empresa)
    errores += e
    advertencias += a
    if documento.ruc_emisor != empresa.ruc:
        errores.append('El RUC emisor del comprobante no es el de la empresa.')

    establecimiento = _validar_serie(documento, errores, advertencias)
    if establecimiento is not None:
        e, a = validar_establecimiento(establecimiento, documento.empresa_id)
        errores += e
        advertencias += a

    if documento.moneda_codigo_id not in ('PEN', 'USD'):
        errores.append(f'Moneda {documento.moneda_codigo_id} no soportada para la emisión (PEN o USD).')
    elif documento.moneda_codigo_id != 'PEN' and not documento.monto_tc:
        advertencias.append('Comprobante en moneda extranjera sin tipo de cambio registrado.')
    if documento.fecha_emision > hoy:
        errores.append('La fecha de emisión es futura.')

    _validar_cliente(documento, errores, advertencias)
    lineas = _validar_lineas_y_totales(documento, errores, advertencias)
    if codigo in (NOTA_CREDITO, NOTA_DEBITO):
        _validar_nota(documento, lineas, errores, advertencias)
    elif documento.motivo_nota_id:
        errores.append('Solo las notas de crédito o débito llevan motivo de nota.')
    return _resultado(documento, errores, advertencias)


def _resultado(documento, errores, advertencias):
    listo = not errores
    return {
        'documento_id': documento.id,
        'tipo_comprobante': documento.tipo_comprobante.codigo_sunat,
        'listo': listo,
        'estado': LISTO_PARA_EMISION if listo else NO_PREPARADO,
        'errores': errores,
        'advertencias': advertencias,
    }


def resolver_motivo_nota(codigo, tipo_comprobante):
    """
    MotivoNota del catálogo que corresponde al tipo de nota (09 en NC, 10 en ND) o None si no
    se envió. Lanza ValidationError si no corresponde. No cambia ninguna regla contable.
    """
    from rest_framework.exceptions import ValidationError
    from apps.catalogos.models import MotivoNota
    codigo = (codigo or '').strip()
    if not codigo:
        return None
    tipo = tipo_comprobante.codigo_sunat
    if tipo not in CATALOGO_MOTIVO:
        raise ValidationError({'motivo_nota': 'Solo las notas de crédito o débito llevan motivo.'})
    motivo = MotivoNota.objects.filter(catalogo=CATALOGO_MOTIVO[tipo], codigo=codigo.zfill(2)).first()
    if motivo is None:
        raise ValidationError({'motivo_nota': f"El motivo '{codigo}' no existe en el catálogo {CATALOGO_MOTIVO[tipo]}."})
    error = validar_motivo_para_tipo(motivo, tipo_comprobante)
    if error:
        raise ValidationError({'motivo_nota': error})
    return motivo


def validar_motivo_para_tipo(motivo, tipo_comprobante):
    """Error (str) si el motivo no corresponde al tipo de nota, o None. Para creación y edición."""
    codigo = tipo_comprobante.codigo_sunat
    if codigo not in CATALOGO_MOTIVO:
        return 'Solo las notas de crédito o débito llevan motivo.'
    catalogo = CATALOGO_MOTIVO[codigo]
    if motivo.catalogo != catalogo:
        return f'El motivo {motivo.codigo} es del catálogo {motivo.catalogo}; la nota requiere el catálogo {catalogo}.'
    if not motivo.activo:
        return f'El motivo {motivo.codigo} ({motivo.descripcion}) no está habilitado.'
    return None
