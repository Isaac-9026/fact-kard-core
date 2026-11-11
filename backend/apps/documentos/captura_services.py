import base64
import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)

from apps.documentos.uploads import nombre_seguro
from apps.documentos.afectacion_igv import (
    TOLERANCIA_IGV, igv_esperado, resolver_afectacion, tasa_igv, validar_igv_linea,
)
from apps.auditoria.services import registrar_auditoria
from apps.catalogos.models import Moneda, TipoComprobante, TipoOperacion
from apps.documentos.clasificacion_captura import clasificar_comprobante
from apps.documentos.models import Documento, DocumentoCaptura, DocumentoDetalle, CapturaCampo
from apps.empresas.models import Empresa
from apps.empresas.periodos import parsear_fecha_calendario, periodo_abierto_para_fecha
from apps.inventario.homologacion import homologar_linea, tercero_por_documento, valores_captura
from apps.inventario.models import Almacen
from apps.kardex.models import Incidencia

DECIMAL_CERO = Decimal('0.00000000')
DECIMAL_UNO = Decimal('1.00000000')
Q8 = Decimal('0.00000001')
Q4 = Decimal('0.0001')


def calcular_hash_sha256(content: bytes) -> str:
    """Calcula el hash SHA-256 de los bytes de un archivo."""
    return hashlib.sha256(content).hexdigest()


def _strip_namespaces(root: ET.Element) -> None:
    """Elimina los prefijos de namespaces de todas las etiquetas XML para facilitar el recorrido."""
    for elem in root.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]


def _find_text(element: ET.Element, tag_name: str, default: Optional[str] = None) -> Optional[str]:
    """Busca el primer elemento con tag_name y retorna su texto limpio."""
    found = element.find(f".//{tag_name}")
    if found is not None and found.text:
        return found.text.strip()
    return default


def parsear_xml_ubl(content: bytes) -> Dict[str, Any]:
    """
    Parsea de forma segura un XML UBL 2.1 de factura (01), boleta (03) o nota de crédito (07)
    según las especificaciones técnicas de SUNAT.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValidationError({'archivo': f'El archivo XML no tiene un formato válido: {str(e)}'})

    _strip_namespaces(root)

    root_tag = root.tag
    is_credit_note = 'CreditNote' in root_tag
    is_debit_note = 'DebitNote' in root_tag

    # 1. Tipo de comprobante
    tipo_comp = _find_text(root, 'InvoiceTypeCode')
    if not tipo_comp:
        if is_credit_note:
            tipo_comp = '07'
        elif is_debit_note:
            tipo_comp = '08'
        else:
            tipo_comp = '01'

    # 2. Serie y número (ej. F001-00001234 o F001-1234)
    id_doc = _find_text(root, 'ID') or ''
    serie = ''
    numero = ''
    if '-' in id_doc:
        partes = id_doc.split('-', 1)
        serie = partes[0].strip().upper()
        numero = partes[1].strip()
    else:
        serie = id_doc[:4].upper()
        numero = id_doc[4:] if len(id_doc) > 4 else id_doc

    # 2.1 Documento de referencia (para notas de crédito / débito)
    doc_modificado = (
        _find_text(root, 'BillingReference/InvoiceDocumentReference/ID')
        or _find_text(root, 'InvoiceDocumentReference/ID')
        or _find_text(root, 'DiscrepancyResponse/ReferenceID')
        or ''
    )

    # 3. Fecha de emisión (CON-001): se conserva literal. Si falta o es inválida queda
    #    tal cual para que el borrador la rechace; nunca se reemplaza por "hoy".
    fecha_str = (_find_text(root, 'IssueDate') or '').strip()
    try:
        fecha_emision_txt = datetime.strptime(fecha_str, '%Y-%m-%d').date().strftime('%Y-%m-%d')
    except ValueError:
        fecha_emision_txt = fecha_str

    # 4. Moneda
    moneda_str = _find_text(root, 'DocumentCurrencyCode') or 'PEN'

    # 5. Emisor (Proveedor)
    ruc_emisor = ''
    razon_social_emisor = ''
    supplier = root.find('.//AccountingSupplierParty')
    if supplier is not None:
        # RUC
        party_id = _find_text(supplier, 'ID')
        if not party_id or len(party_id) != 11:
            party_id = _find_text(supplier, 'CompanyID')
        ruc_emisor = party_id or ''

        # Razón Social
        legal_name = _find_text(supplier, 'RegistrationName')
        if not legal_name:
            legal_name = _find_text(supplier, 'Name')
        razon_social_emisor = legal_name or ''

    # 6. Adquiriente (Cliente / Empresa receptora)
    ruc_cliente = ''
    razon_social_cliente = ''
    customer = root.find('.//AccountingCustomerParty')
    if customer is not None:
        ruc_cliente = _find_text(customer, 'ID') or _find_text(customer, 'CompanyID') or ''
        razon_social_cliente = _find_text(customer, 'RegistrationName') or _find_text(customer, 'Name') or ''

    # 6.1 Motivo de la nota (Catálogos 09/10 SUNAT): decide devolución vs ajuste de valor.
    motivo_nota = _find_text(root, 'DiscrepancyResponse/ResponseCode') or ''

    # 7. Totales monetarios
    subtotal_str = _find_text(root, 'LineExtensionAmount') or '0.00'
    igv_str = '0.00'
    tax_total = root.find('.//TaxTotal')
    if tax_total is not None:
        igv_str = _find_text(tax_total, 'TaxAmount') or '0.00'
    total_str = _find_text(root, 'PayableAmount') or _find_text(root, 'LineExtensionAmount') or '0.00'

    try:
        subtotal = Decimal(subtotal_str).quantize(Q8, rounding=ROUND_HALF_UP)
    except Exception:
        subtotal = DECIMAL_CERO

    try:
        igv = Decimal(igv_str).quantize(Q8, rounding=ROUND_HALF_UP)
    except Exception:
        igv = DECIMAL_CERO

    try:
        total = Decimal(total_str).quantize(Q8, rounding=ROUND_HALF_UP)
    except Exception:
        total = subtotal + igv

    # 8. Líneas de Detalle
    line_tag = 'CreditNoteLine' if is_credit_note else ('DebitNoteLine' if is_debit_note else 'InvoiceLine')
    lines = root.findall(f'.//{line_tag}')
    detalles = []

    for index, line in enumerate(lines, start=1):
        # Cantidad y unidad
        qty_elem = line.find('.//InvoicedQuantity')
        if qty_elem is None:
            qty_elem = line.find('.//CreditedQuantity')
        if qty_elem is None:
            qty_elem = line.find('.//DebitedQuantity')

        cant_str = qty_elem.text.strip() if (qty_elem is not None and qty_elem.text) else '1.0'
        unit_code = qty_elem.get('unitCode', 'NIU') if qty_elem is not None else 'NIU'

        # Código externo y descripción del ítem
        item = line.find('.//Item')
        codigo_externo = ''
        descripcion = ''
        if item is not None:
            # QA-002: el código del proveedor es SellersItemIdentification/ID; antes se tomaba el
            # primer <ID> del ítem (podía ser BuyersItemIdentification o StandardItemIdentification).
            sellers = item.find('.//SellersItemIdentification')
            sellers_id = _find_text(sellers, 'ID') if sellers is not None else None
            codigo_externo = sellers_id or _find_text(item, 'ID') or ''
            descripcion = _find_text(item, 'Description') or ''

        # Precio unitario
        price = _find_text(line, 'PriceAmount')
        if not price:
            alt_price = line.find('.//PricingReference')
            if alt_price is not None:
                price = _find_text(alt_price, 'PriceAmount')

        # Subtotal de la línea
        line_ext = _find_text(line, 'LineExtensionAmount')

        try:
            cant_dec = Decimal(cant_str).quantize(Q8, rounding=ROUND_HALF_UP)
        except Exception:
            cant_dec = DECIMAL_UNO

        try:
            precio_dec = Decimal(price or '0.00').quantize(Q8, rounding=ROUND_HALF_UP)
        except Exception:
            precio_dec = DECIMAL_CERO

        try:
            val_total_dec = Decimal(line_ext or str(cant_dec * precio_dec)).quantize(Q8, rounding=ROUND_HALF_UP)
        except Exception:
            val_total_dec = (cant_dec * precio_dec).quantize(Q8, rounding=ROUND_HALF_UP)

        # Bloque 3: IGV y afectación (Catálogo 07) de la línea, tal como vienen en el XML.
        igv_linea_txt = None
        codigo_afectacion = ''
        tax_linea = line.find('TaxTotal')
        if tax_linea is not None:
            igv_linea_txt = _find_text(tax_linea, 'TaxAmount')
            codigo_afectacion = (_find_text(tax_linea, 'TaxExemptionReasonCode') or '').strip()
        try:
            igv_linea_dec = Decimal(igv_linea_txt).quantize(Q8, rounding=ROUND_HALF_UP) if igv_linea_txt else None
        except Exception:
            igv_linea_dec = None

        detalles.append({
            'numero_linea': index,
            'codigo_externo': codigo_externo,
            'descripcion': descripcion,
            'unidad_medida': unit_code,
            'cantidad': cant_dec,
            'precio_unitario': precio_dec,
            'valor_total': val_total_dec,
            'igv': igv_linea_dec,
            'codigo_afectacion_igv': codigo_afectacion,
        })

    return {
        'tipo': 'XML',
        'cabecera': {
            'tipo_comprobante': tipo_comp,
            'serie': serie,
            'numero': numero,
            'serie_numero': id_doc or f"{serie}-{numero}",
            'fecha_emision': fecha_emision_txt,
            'moneda': moneda_str,
            'ruc_emisor': ruc_emisor,
            'razon_social_emisor': razon_social_emisor,
            'ruc_cliente': ruc_cliente,
            'razon_social_cliente': razon_social_cliente,
            'subtotal': str(subtotal),
            'igv': str(igv),
            'total': str(total),
            'doc_modificado': doc_modificado,
            'motivo_nota': motivo_nota,
        },
        'detalles': detalles,
        'confianza_global': Decimal('100.0000'),
    }


MIME_TYPES_OCR = {
    '.pdf': 'application/pdf',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}


def _extraer_texto_pdf_nativo(content: bytes) -> str:
    """
    Intenta extraer texto plano de un documento PDF de forma nativa sin
    dependencias pesadas de sistema operativo (cero Poppler / Tesseract).
    """
    if not content or not content.startswith(b'%PDF'):
        return ''

    # 1. Intentar con pypdf si estuviera instalado
    try:
        import io
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(io.BytesIO(content))
        textos_pag = [p.extract_text() or '' for p in reader.pages]
        texto_unido = '\n'.join(textos_pag).strip()
        if texto_unido:
            return texto_unido
    except Exception:
        pass

    # 2. Extracción nativa de streams de texto PDF (Tj / TJ / FlateDecode)
    textos: List[str] = []
    stream_regex = re.compile(rb'stream[\r\n]+(.*?)[\r\n]+endstream', re.DOTALL)
    for m in stream_regex.finditer(content):
        raw_stream = m.group(1)
        try:
            decomp = zlib.decompress(raw_stream)
        except Exception:
            decomp = raw_stream

        # Buscar cadenas (Texto) Tj
        for s in re.finditer(rb'\((.*?)\)\s*Tj', decomp):
            try:
                textos.append(s.group(1).decode('latin-1', errors='ignore'))
            except Exception:
                pass
        # Buscar cadenas [(T) 10 (exto)] TJ
        for arr in re.finditer(rb'\[(.*?)\]\s*TJ', decomp):
            for p in re.findall(rb'\((.*?)\)', arr.group(1)):
                try:
                    textos.append(p.decode('latin-1', errors='ignore'))
                except Exception:
                    pass

    if textos:
        return ' '.join(textos)

    # 3. Fallback de decodificación directa
    try:
        return content.decode('utf-8', errors='ignore')
    except Exception:
        return ''


def _extraer_ocr_local(texto: str) -> Dict[str, Any]:
    """
    Extracción mediante expresiones regulares para texto plano o comprobantes
    con layout legible, garantizando fidelidad contable y tests 100% deterministas.
    """
    texto = texto or ''

    # RUC (11 dígitos, empieza en 10 o 20). El primero es el emisor; el siguiente
    # distinto, el receptor. Sin dato no se inventa: queda vacío y con confianza 0.
    rucs = list(dict.fromkeys(re.findall(r'\b(10\d{9}|20\d{9})\b', texto)))
    ruc_emisor = rucs[0] if rucs else ''
    conf_ruc = Decimal('95.0000') if rucs else Decimal('0.0000')
    ruc_cliente = rucs[1] if len(rucs) > 1 else ''
    conf_ruc_cliente = Decimal('80.0000') if ruc_cliente else Decimal('0.0000')

    # Tipo Comprobante (Bloque 5: sin palabra clave no se supone factura)
    tipo_comp, conf_tipo = '', Decimal('0.0000')
    if re.search(r'\bNOTA\s+DE\s+CR[EÉ]DITO\b', texto, re.IGNORECASE):
        tipo_comp, conf_tipo = '07', Decimal('90.0000')
    elif re.search(r'\bNOTA\s+DE\s+D[EÉ]BITO\b', texto, re.IGNORECASE):
        tipo_comp, conf_tipo = '08', Decimal('90.0000')
    elif re.search(r'\bBOLETA\b', texto, re.IGNORECASE):
        tipo_comp, conf_tipo = '03', Decimal('90.0000')
    elif re.search(r'\bFACTURA\b', texto, re.IGNORECASE):
        tipo_comp, conf_tipo = '01', Decimal('90.0000')

    # Serie y Número (ej. F001-1234 o E001-5678)
    serie_match = re.search(r'\b([FEB][0-9A-Z]{3})[- ]?([0-9]{1,8})\b', texto)
    if serie_match:
        serie = serie_match.group(1).upper()
        numero = serie_match.group(2)
        conf_serie_num = Decimal('92.0000')
    else:
        # Bloque 5: antes se inventaba F001-00000001; ahora queda para corrección humana.
        serie, numero = '', ''
        conf_serie_num = Decimal('0.0000')

    # Fecha (YYYY-MM-DD o DD/MM/YYYY)
    fecha_match = re.search(r'\b(\d{4}[-/]\d{2}[-/]\d{2})\b', texto)
    if fecha_match:
        fecha_emision = fecha_match.group(1).replace('/', '-')
        conf_fecha = Decimal('90.0000')
    else:
        fecha_alt = re.search(r'\b(\d{2})[/.-](\d{2})[/.-](\d{4})\b', texto)
        if fecha_alt:
            fecha_emision = f"{fecha_alt.group(3)}-{fecha_alt.group(2)}-{fecha_alt.group(1)}"
            conf_fecha = Decimal('88.0000')
        else:
            # CON-001: sin fecha detectada no se inventa "hoy"; requiere corrección humana.
            fecha_emision = ''
            conf_fecha = Decimal('0.0000')

    # Moneda
    if re.search(r'\b(USD|D[OÓ]LARES?|\$)\b', texto, re.IGNORECASE):
        moneda = 'USD'
        conf_moneda = Decimal('94.0000')
    elif re.search(r'S/|\bSOLES\b|\bPEN\b', texto, re.IGNORECASE):
        moneda = 'PEN'
        conf_moneda = Decimal('92.0000')
    else:
        moneda = ''  # Bloque 5: sin evidencia no se supone PEN
        conf_moneda = Decimal('0.0000')

    # Totales e IGV (Bloque 4): solo lo que el texto evidencia. Antes se asumía
    # subtotal = total / 1.18 (gravado 18 %) y, sin total, se inventaba 118.00.
    def _monto(patron):
        m = re.search(patron + r'[:\s]*(?:S/\.?|\$)?\s*([0-9,]+\.[0-9]{2})\b', texto, re.IGNORECASE)
        return Decimal(m.group(1).replace(',', '')).quantize(Q8, rounding=ROUND_HALF_UP) if m else None

    total_dec = _monto(r'(?<!SUB\s)(?<!SUB-)(?<!SUB)\bTOTAL(?:\s+A\s+PAGAR)?')
    conf_total = Decimal('88.0000') if total_dec is not None else Decimal('0.0000')
    igv_explicito = _monto(r'\bI\.?G\.?V\.?(?:\s*\(?\s*\d{1,2}(?:\.\d+)?\s*%\s*\)?)?')
    subtotal_explicito = _monto(r'\b(?:OP(?:ERACI[OÓ]N(?:ES)?)?\.?\s*GRAVADAS?|SUB\s*-?\s*TOTAL|VALOR\s+(?:DE\s+)?VENTA)')
    hay_exonerada = bool(re.search(r'\bEXONERAD[OA]S?\b', texto, re.IGNORECASE))
    hay_inafecta = bool(re.search(r'\bINAFECT[OA]S?\b', texto, re.IGNORECASE))

    afectacion_ocr = ''  # sin evidencia: pendiente de clasificación (revisión manual)
    if igv_explicito is not None and igv_explicito > DECIMAL_CERO:
        afectacion_ocr = 'GRAVADO'
        igv_dec = igv_explicito
        if subtotal_explicito is not None:
            subtotal_dec = subtotal_explicito
        elif total_dec is not None:
            subtotal_dec = (total_dec - igv_dec).quantize(Q8, rounding=ROUND_HALF_UP)
        else:
            subtotal_dec = None
    elif not igv_explicito and hay_exonerada != hay_inafecta:
        afectacion_ocr = 'EXONERADO' if hay_exonerada else 'INAFECTO'
        igv_dec = DECIMAL_CERO
        subtotal_dec = subtotal_explicito if subtotal_explicito is not None else total_dec
    else:
        igv_dec = None
        subtotal_dec = subtotal_explicito if subtotal_explicito is not None else None
    conf_afectacion = Decimal('85.0000') if afectacion_ocr else Decimal('0.0000')

    def _texto(valor):
        return str(valor) if valor is not None else ''

    # Razón Social Emisor
    rz_match = re.search(r'\b(?:SE[NÑ]OR(?:ES)?|EMISOR|PROVEEDOR|RAZ[OÓ]N\s+SOCIAL)[:\s]+([^\n\r]+)', texto, re.IGNORECASE)
    razon_social = rz_match.group(1).strip() if rz_match else ''
    conf_rz = Decimal('85.0000') if rz_match else Decimal('0.0000')

    # Líneas (Bloque 5): "cantidad [código] descripción precio_unitario importe", aceptada
    # solo si cantidad × precio = importe (± 0.01). Si las líneas no suman el subtotal
    # leído, no se usan. Sin líneas válidas queda una línea vacía para revisión manual.
    detalles = []
    patron_linea = re.compile(
        r'^\s*(?P<cant>\d+(?:\.\d+)?)\s+(?:(?P<cod>(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{1,19})\s+)?'
        r'(?P<desc>[^\d\s].*?)\s+(?P<pu>\d[\d,]*\.\d{2,8})\s+(?P<imp>\d[\d,]*\.\d{2})\s*$',
        re.MULTILINE,
    )
    for m in patron_linea.finditer(texto):
        cant = Decimal(m.group('cant'))
        pu = Decimal(m.group('pu').replace(',', ''))
        imp = Decimal(m.group('imp').replace(',', ''))
        if cant <= DECIMAL_CERO or abs(cant * pu - imp) > Decimal('0.01'):
            continue
        detalles.append({'codigo_externo': m.group('cod') or '', 'descripcion': m.group('desc').strip(),
                         'cantidad': cant.quantize(Q8), 'precio_unitario': pu.quantize(Q8),
                         'valor_total': imp.quantize(Q8)})
    if detalles:
        suma = sum((d['valor_total'] for d in detalles), DECIMAL_CERO)
        if subtotal_dec is not None and abs(suma - subtotal_dec) > Decimal('0.01'):
            detalles = []  # no cuadran con el subtotal: ambiguo
        elif subtotal_dec is None:
            subtotal_dec = suma
    if detalles:
        for d in detalles:
            d.update({
                'unidad_medida': 'NIU', 'confianza': Decimal('80.0000'),
                # IGV por línea solo cuando hay una única línea y el IGV es explícito.
                'igv': _texto(igv_dec) if len(detalles) == 1 or afectacion_ocr in ('EXONERADO', 'INAFECTO') else '',
                'afectacion_igv': afectacion_ocr,
                'confianzas': {'igv': conf_afectacion, 'afectacion_igv': conf_afectacion},
            })
    else:
        detalles = [{
            'codigo_externo': '', 'descripcion': '', 'unidad_medida': 'NIU',
            'cantidad': Decimal('1.00000000'),
            'precio_unitario': subtotal_dec if subtotal_dec is not None else DECIMAL_CERO,
            'valor_total': subtotal_dec if subtotal_dec is not None else DECIMAL_CERO,
            'igv': _texto(igv_dec), 'afectacion_igv': afectacion_ocr,
            'confianza': Decimal('0.0000'),
            'confianzas': {'igv': conf_afectacion, 'afectacion_igv': conf_afectacion},
        }]
    for numero_linea, d in enumerate(detalles, start=1):
        d['numero_linea'] = numero_linea

    return {
        'tipo': 'OCR',
        'cabecera': {
            'tipo_comprobante': (tipo_comp, conf_tipo),
            'serie': (serie, conf_serie_num),
            'numero': (numero, conf_serie_num),
            'serie_numero': (f"{serie}-{numero}", conf_serie_num),
            'fecha_emision': (fecha_emision, conf_fecha),
            'moneda': (moneda, conf_moneda),
            'ruc_emisor': (ruc_emisor, conf_ruc),
            'ruc_cliente': (ruc_cliente, conf_ruc_cliente),
            'razon_social_emisor': (razon_social, conf_rz),
            'subtotal': (_texto(subtotal_dec), Decimal('85.0000') if subtotal_dec is not None else Decimal('0.0000')),
            'igv': (_texto(igv_dec), conf_afectacion),
            'total': (_texto(total_dec), conf_total),
        },
        'detalles': detalles,
        'confianza_global': Decimal('84.0000'),
        'alertas': [],
    }


def _extraer_ocr_gemini(
    content: bytes,
    filename: str,
    mime_type: str,
    api_key: str,
    model: str = 'gemini-3.5-flash-lite',
) -> Dict[str, Any]:
    """
    Extracción multimodal de comprobantes peruanos (SUNAT) mediante Gemini 2.5 Flash.
    Utiliza HTTPS puro vía urllib.request (cero dependencias de SO, cero binarios).
    Convierte todo importe y cantidad a Decimal exacto con ROUND_HALF_UP.
    """
    b64_content = base64.b64encode(content).decode('ascii')
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    prompt = (
        "Eres un Senior Contable peruano y extractor experto de comprobantes de pago autorizados "
        "por la SUNAT (Facturas, Boletas de Venta, Notas de Crédito, Notas de Débito).\n"
        "Analiza detalladamente el comprobante adjunto y extrae todos los datos estructurados en "
        "un único objeto JSON estricto con la siguiente estructura exacta:\n"
        "{\n"
        '  "ruc_emisor": "RUC del proveedor/emisor (11 dígitos numéricos que inician en 10 o 20)",\n'
        '  "razon_social_emisor": "Nombre comercial o razón social completa del emisor",\n'
        '  "ruc_cliente": "RUC o DNI del receptor/cliente si existe (o cadena vacía)",\n'
        '  "razon_social_cliente": "Razón social o nombre del cliente si existe (o cadena vacía)",\n'
        '  "tipo_comprobante": "Código SUNAT de 2 dígitos: 01 (Factura), 03 (Boleta), 07 (Nota de Crédito), 08 (Nota de Débito)",\n'
        '  "serie": "Serie del comprobante, ej. F001, E001, B001, FC01, etc.",\n'
        '  "numero": "Número correlativo del comprobante sin serie, ej. 450, 123456",\n'
        '  "fecha_emision": "Fecha de emisión en formato estricto YYYY-MM-DD",\n'
        '  "moneda": "Código de moneda: PEN (para Soles S/) o USD (para Dólares $)",\n'
        '  "subtotal": "Base imponible u operación gravada como string decimal con 2 o más decimales, ej. 100.00",\n'
        '  "igv": "Monto del IGV 18% como string decimal, ej. 18.00 (o 0.00 si es exonerado o inafecto)",\n'
        '  "total": "Importe total a pagar como string decimal, ej. 118.00",\n'
        '  "afectacion_igv": "GRAVADO, EXONERADO o INAFECTO según aplique",\n'
        '  "items": [\n'
        "    {\n"
        '      "codigo": "Código de producto o SKU si figura, o cadena vacía",\n'
        '      "descripcion": "Descripción del bien o servicio",\n'
        '      "unidad_medida": "Código de unidad de medida SUNAT (ej. NIU, KGM, ZZ, BX, etc., o NIU por defecto)",\n'
        '      "cantidad": "Cantidad como string decimal, ej. 2.00",\n'
        '      "valor_unitario": "Valor unitario sin IGV como string decimal",\n'
        '      "precio_unitario": "Precio unitario con IGV como string decimal",\n'
        '      "importe_total": "Importe o valor total de la línea como string decimal"\n'
        "    }\n"
        "  ],\n"
        '  "confianza": 95\n'
        "}\n\n"
        "Reglas estrictas:\n"
        "1. No inventes RUCs, series o números que no estén en el documento.\n"
        "2. No devuelvas números de punto flotante en el JSON: todos los importes y cantidades deben ser strings con punto decimal (ej. \"150.00\").\n"
        "3. No agregues explicaciones ni bloques de markdown (```json), entrega únicamente el JSON puro."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": b64_content,
                        }
                    },
                    {
                        "text": prompt,
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        resp_bytes = resp.read()
        resp_data = json.loads(resp_bytes.decode('utf-8'))

    candidates = resp_data.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini API no retornó candidatos de respuesta válidos.")

    parts = candidates[0].get("content", {}).get("parts", [])
    raw_text = "".join(p.get("text", "") for p in parts).strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    parsed = json.loads(raw_text)

    def _dec(val: Any) -> Optional[Decimal]:
        if val is None or val == '':
            return None
        try:
            limpio = str(val).replace(',', '').strip()
            return Decimal(limpio).quantize(Q8, rounding=ROUND_HALF_UP)
        except Exception:
            return None

    def _txt(val: Optional[Decimal]) -> str:
        return str(val) if val is not None else ''

    # RUCs
    ruc_emisor = str(parsed.get('ruc_emisor') or '').strip()
    if ruc_emisor and not re.match(r'^(10|20)\d{9}$', ruc_emisor):
        m_ruc = re.search(r'\b(10\d{9}|20\d{9})\b', ruc_emisor)
        ruc_emisor = m_ruc.group(1) if m_ruc else ''
    conf_ruc = Decimal('98.0000') if ruc_emisor else Decimal('0.0000')

    ruc_cliente = str(parsed.get('ruc_cliente') or '').strip()
    if ruc_cliente and not re.match(r'^\d{8,11}$', ruc_cliente):
        m_cli = re.search(r'\b(\d{8,11})\b', ruc_cliente)
        ruc_cliente = m_cli.group(1) if m_cli else ''
    conf_ruc_cliente = Decimal('92.0000') if ruc_cliente else Decimal('0.0000')

    # Tipo Comprobante
    tipo_comp = str(parsed.get('tipo_comprobante') or '').strip()
    if tipo_comp not in ('01', '03', '07', '08'):
        tipo_upper = tipo_comp.upper()
        if 'NOTA' in tipo_upper and 'CR' in tipo_upper:
            tipo_comp = '07'
        elif 'NOTA' in tipo_upper and 'D' in tipo_upper:
            tipo_comp = '08'
        elif 'BOLETA' in tipo_upper:
            tipo_comp = '03'
        elif 'FACTURA' in tipo_upper:
            tipo_comp = '01'
        else:
            tipo_comp = ''
    conf_tipo = Decimal('98.0000') if tipo_comp else Decimal('0.0000')

    # Serie y Número
    serie = str(parsed.get('serie') or '').strip().upper()
    numero = str(parsed.get('numero') or '').strip().lstrip('0') or '0'
    if not serie or not re.match(r'^[FEB0-9][A-Z0-9]{1,3}$', serie):
        m_sn = re.match(r'^([FEB][0-9A-Z]{3})[- ]?([0-9]{1,8})$', f"{serie}-{numero}")
        if m_sn:
            serie, numero = m_sn.group(1), m_sn.group(2)
    conf_serie_num = Decimal('98.0000') if serie and numero and numero != '0' else Decimal('0.0000')
    if not conf_serie_num:
        serie, numero = (serie, numero) if (serie or numero) else ('', '')

    # Fecha
    fecha_emision = str(parsed.get('fecha_emision') or '').strip()
    if fecha_emision:
        m_f = re.search(r'\b(\d{4}[-/]\d{2}[-/]\d{2})\b', fecha_emision)
        if m_f:
            fecha_emision = m_f.group(1).replace('/', '-')
        else:
            m_alt = re.search(r'\b(\d{2})[/.-](\d{2})[/.-](\d{4})\b', fecha_emision)
            fecha_emision = f"{m_alt.group(3)}-{m_alt.group(2)}-{m_alt.group(1)}" if m_alt else ''
    conf_fecha = Decimal('96.0000') if fecha_emision else Decimal('0.0000')

    # Moneda
    moneda_raw = str(parsed.get('moneda') or '').strip().upper()
    if 'USD' in moneda_raw or 'DOLAR' in moneda_raw or '$' in moneda_raw:
        moneda = 'USD'
    elif 'PEN' in moneda_raw or 'SOL' in moneda_raw or 'S/' in moneda_raw:
        moneda = 'PEN'
    else:
        moneda = ''
    conf_moneda = Decimal('96.0000') if moneda else Decimal('0.0000')

    # Razón Social Emisor
    razon_social = str(parsed.get('razon_social_emisor') or '').strip()
    conf_rz = Decimal('94.0000') if razon_social else Decimal('0.0000')

    # Importes
    total_dec = _dec(parsed.get('total'))
    conf_total = Decimal('96.0000') if total_dec is not None else Decimal('0.0000')

    igv_dec = _dec(parsed.get('igv'))
    subtotal_dec = _dec(parsed.get('subtotal'))

    afectacion = str(parsed.get('afectacion_igv') or '').strip().upper()
    if not afectacion:
        if igv_dec is not None and igv_dec > DECIMAL_CERO:
            afectacion = 'GRAVADO'
        elif igv_dec is not None and igv_dec == DECIMAL_CERO:
            afectacion = 'EXONERADO'

    if subtotal_dec is None and total_dec is not None and igv_dec is not None:
        subtotal_dec = (total_dec - igv_dec).quantize(Q8, rounding=ROUND_HALF_UP)

    conf_subtotal = Decimal('94.0000') if subtotal_dec is not None else Decimal('0.0000')
    conf_afectacion = Decimal('94.0000') if afectacion else Decimal('0.0000')

    # Ítems / Detalles
    raw_items = parsed.get('items') or []
    detalles: List[Dict[str, Any]] = []
    for item in raw_items:
        cant = _dec(item.get('cantidad')) or DECIMAL_UNO
        pu = _dec(item.get('precio_unitario')) or _dec(item.get('valor_unitario')) or DECIMAL_CERO
        imp = _dec(item.get('importe_total'))
        if imp is None and cant and pu:
            imp = (cant * pu).quantize(Q8, rounding=ROUND_HALF_UP)
        elif imp is None:
            imp = DECIMAL_CERO

        cod = str(item.get('codigo') or item.get('codigo_externo') or '').strip()
        desc = str(item.get('descripcion') or '').strip()
        um = str(item.get('unidad_medida') or 'NIU').strip().upper() or 'NIU'

        detalles.append({
            'codigo_externo': cod,
            'descripcion': desc,
            'unidad_medida': um,
            'cantidad': cant.quantize(Q8),
            'precio_unitario': pu.quantize(Q8),
            'valor_total': imp.quantize(Q8),
            'igv': _txt(igv_dec) if len(raw_items) == 1 else '',
            'afectacion_igv': afectacion,
            'confianza': Decimal('95.0000'),
            'confianzas': {'igv': conf_afectacion, 'afectacion_igv': conf_afectacion},
        })

    if detalles:
        suma_items = sum((d['valor_total'] for d in detalles), DECIMAL_CERO)
        if subtotal_dec is None:
            subtotal_dec = suma_items
            conf_subtotal = Decimal('94.0000')
    else:
        detalles = [{
            'codigo_externo': '',
            'descripcion': '',
            'unidad_medida': 'NIU',
            'cantidad': DECIMAL_UNO,
            'precio_unitario': subtotal_dec if subtotal_dec is not None else DECIMAL_CERO,
            'valor_total': subtotal_dec if subtotal_dec is not None else DECIMAL_CERO,
            'igv': _txt(igv_dec),
            'afectacion_igv': afectacion,
            'confianza': Decimal('0.0000'),
            'confianzas': {'igv': conf_afectacion, 'afectacion_igv': conf_afectacion},
        }]

    for idx, d in enumerate(detalles, start=1):
        d['numero_linea'] = idx

    serie_numero_str = f"{serie}-{numero}" if (serie and numero) else ''

    return {
        'tipo': 'OCR',
        'cabecera': {
            'tipo_comprobante': (tipo_comp, conf_tipo),
            'serie': (serie, conf_serie_num),
            'numero': (numero, conf_serie_num),
            'serie_numero': (serie_numero_str, conf_serie_num),
            'fecha_emision': (fecha_emision, conf_fecha),
            'moneda': (moneda, conf_moneda),
            'ruc_emisor': (ruc_emisor, conf_ruc),
            'ruc_cliente': (ruc_cliente, conf_ruc_cliente),
            'razon_social_emisor': (razon_social, conf_rz),
            'subtotal': (_txt(subtotal_dec), conf_subtotal),
            'igv': (_txt(igv_dec), conf_afectacion),
            'total': (_txt(total_dec), conf_total),
        },
        'detalles': detalles,
        'confianza_global': Decimal('95.0000'),
        'alertas': [],
    }


def extraer_ocr_basico(content: bytes, filename: str, texto_ocr: Optional[str] = None) -> Dict[str, Any]:
    """
    Extracción OCR para comprobantes en PDF, Imagen (.jpg, .jpeg, .png, .webp) o Escáner.
    Arquitectura en cascada de 3 niveles:
      - Nivel 1: Texto explícito provisto (tests) o extracción nativa de PDF con alta confianza.
      - Nivel 2: Extracción multimodal con Gemini 2.5 Flash si GEMINI_API_KEY está configurada.
      - Nivel 3: Fallback local determinista con expresiones regulares (offline / sin API key).
    """
    # Nivel 1: Si texto_ocr fue provisto explícitamente (ej. tests unitarios), usar parser local
    if texto_ocr is not None and texto_ocr.strip():
        return _extraer_ocr_local(texto_ocr)

    nombre_bajo = (filename or '').lower()
    ext = '.' + nombre_bajo.rsplit('.', 1)[-1] if '.' in nombre_bajo else ''

    # Nivel 1 (continuación): Si es PDF, intentar extracción nativa de texto plano
    if ext == '.pdf' and content:
        texto_nativo = _extraer_texto_pdf_nativo(content)
        if texto_nativo.strip():
            res_local = _extraer_ocr_local(texto_nativo)
            cab = res_local.get('cabecera', {})
            ruc_val, ruc_conf = cab.get('ruc_emisor', ('', Decimal('0')))
            serie_val, serie_conf = cab.get('serie', ('', Decimal('0')))
            num_val, num_conf = cab.get('numero', ('', Decimal('0')))
            tot_val, tot_conf = cab.get('total', ('', Decimal('0')))
            # Confianza alta: RUC emisor, Serie/Número y Total detectados
            if (ruc_val and ruc_conf >= Decimal('90.0000') and
                serie_val and num_val and serie_conf >= Decimal('90.0000') and
                tot_val and tot_conf >= Decimal('85.0000')):
                return res_local

    # Nivel 2: Extracción Multimodal con Gemini 2.5 Flash
    api_key = (
        getattr(settings, 'GEMINI_API_KEY', '') or
        os.environ.get('GEMINI_API_KEY', '')
    ).strip()
    model = (
        getattr(settings, 'GEMINI_MODEL', '') or
        os.environ.get('GEMINI_MODEL', '') or
        'gemini-3.5-flash-lite'
    ).strip()

    mime_type = MIME_TYPES_OCR.get(ext)
    if api_key and mime_type and content:
        try:
            return _extraer_ocr_gemini(
                content=content,
                filename=filename,
                mime_type=mime_type,
                api_key=api_key,
                model=model,
            )
        except Exception as exc:
            logger.warning(
                "Fallo en llamada a Gemini (%s): %s. Procediendo a Nivel 3 (fallback local).",
                type(exc).__name__, exc,
            )
            # Proceder a Nivel 3 registrando la alerta en el resultado
            res_fallback = _extraer_ocr_local(content.decode('utf-8', errors='ignore') if content else '')
            res_fallback.setdefault('alertas', []).append(
                f"Fallo en extracción multimodal Gemini ({type(exc).__name__}): {exc}"
            )
            return res_fallback

    # Nivel 3: Fallback Local (Sin API Key, texto plano o modo test)
    texto_fallback = ''
    if content:
        try:
            texto_fallback = content.decode('utf-8', errors='ignore')
        except Exception:
            texto_fallback = ''
    return _extraer_ocr_local(texto_fallback)


@transaction.atomic
def procesar_subida_captura(
    *,
    empresa_id: int,
    usuario,
    archivo,
    tipo: str,
    texto_ocr: Optional[str] = None,
    nombre_archivo: Optional[str] = None,
) -> Tuple[DocumentoCaptura, bool]:
    """
    Procesa un archivo XML o PDF/Imagen/Escáner:
    1. Calcula el hash SHA-256 para evitar reprocesar archivos idénticos.
    2. Crea el registro en DocumentoCaptura.
    3. Extrae campos y puebla CapturaCampo con su seccion, numero_linea y nivel de confianza.
    Retorna (captura, fue_creado_nuevo).
    """
    content = archivo.read()
    hash_sha256 = calcular_hash_sha256(content)

    # Verificar si ya existe idéntico en la empresa
    existente = DocumentoCaptura.objects.filter(
        empresa_id=empresa_id,
        hash_sha256=hash_sha256,
    ).first()

    if existente is not None:
        return existente, False

    captura = DocumentoCaptura.objects.create(
        empresa_id=empresa_id,
        tipo=tipo.upper(),
        # Bloque 6: nombre saneado (sin rutas); el archivo aún no se almacena en disco.
        ruta_archivo=f"uploads/{tipo.lower()}/{nombre_archivo or nombre_seguro(archivo.name)}",
        hash_sha256=hash_sha256,
        estado_proceso='PROCESADO',
        subido_por=usuario,
    )

    if tipo.upper() == 'XML':
        datos = parsear_xml_ubl(content)
        # Poblar cabecera (confianza 100% para XML electrónico estructurado)
        conf_xml = Decimal('100.0000')
        for nombre, valor in datos['cabecera'].items():
            CapturaCampo.objects.create(
                documento_captura=captura,
                seccion='CABECERA',
                numero_linea=None,
                nombre_campo=nombre,
                valor_extraido=str(valor) if valor is not None else '',
                confianza=conf_xml,
            )

        # Poblar detalle
        for item in datos['detalles']:
            num_linea = item['numero_linea']
            for campo_nombre in ('codigo_externo', 'descripcion', 'unidad_medida', 'cantidad', 'precio_unitario',
                                 'valor_total', 'igv', 'codigo_afectacion_igv'):
                val = item.get(campo_nombre)
                CapturaCampo.objects.create(
                    documento_captura=captura,
                    seccion='DETALLE',
                    numero_linea=num_linea,
                    nombre_campo=campo_nombre,
                    valor_extraido=str(val) if val is not None else '',
                    confianza=conf_xml,
                )

    else:
        # OCR para PDF, IMAGEN o ESCANER
        datos = extraer_ocr_basico(content, archivo.name, texto_ocr)
        for nombre, tupla in datos['cabecera'].items():
            valor, conf = tupla
            CapturaCampo.objects.create(
                documento_captura=captura,
                seccion='CABECERA',
                numero_linea=None,
                nombre_campo=nombre,
                valor_extraido=str(valor) if valor is not None else '',
                confianza=conf,
            )

        for item in datos['detalles']:
            num_linea = item['numero_linea']
            conf_det = item.get('confianza', Decimal('80.0000'))
            for campo_nombre in ('codigo_externo', 'descripcion', 'unidad_medida', 'cantidad', 'precio_unitario',
                                 'valor_total', 'igv', 'afectacion_igv'):
                val = item.get(campo_nombre)
                CapturaCampo.objects.create(
                    documento_captura=captura,
                    seccion='DETALLE',
                    numero_linea=num_linea,
                    nombre_campo=campo_nombre,
                    valor_extraido=str(val) if val is not None else '',
                    confianza=item.get('confianzas', {}).get(campo_nombre, conf_det),
                )

    registrar_auditoria(
        empresa_id=empresa_id,
        usuario_id=usuario.id,
        accion='SUBIR_CAPTURA_DOCUMENTO',
        entidad='DOCUMENTO_CAPTURA',
        registro_id=captura.id,
        valor_anterior=None,
        valor_nuevo={'tipo': captura.tipo, 'hash_sha256': hash_sha256, 'archivo': archivo.name},
    )

    return captura, True


@transaction.atomic
def corregir_campo_captura(
    *,
    captura_id: int,
    campo_id: int,
    valor_corregido: str,
    empresa_id: int,
    usuario,
) -> CapturaCampo:
    """Permite al usuario humano corregir el valor de un campo extraído."""
    campo = CapturaCampo.objects.select_for_update().filter(
        pk=campo_id,
        documento_captura_id=captura_id,
        documento_captura__empresa_id=empresa_id,
    ).first()

    if campo is None:
        raise ValidationError({'campo_id': 'Campo de captura no encontrado para esta empresa.'})

    val_ant = campo.valor_corregido or campo.valor_extraido
    campo.valor_corregido = valor_corregido
    campo.corregido_por = usuario
    campo.save(update_fields=['valor_corregido', 'corregido_por'])

    registrar_auditoria(
        empresa_id=empresa_id,
        usuario_id=usuario.id,
        accion='CORREGIR_CAMPO_CAPTURA',
        entidad='CAPTURA_CAMPO',
        registro_id=campo.id,
        valor_anterior={'valor': val_ant},
        valor_nuevo={'valor_corregido': valor_corregido, 'campo': campo.nombre_campo},
    )
    return campo


@transaction.atomic
def generar_borrador_desde_captura(
    *,
    captura_id: int,
    empresa_id: int,
    usuario,
    almacen_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Convierte los campos de CapturaCampo en un Documento y DocumentoDetalle en estado estricto:
    estado = 'BORRADOR' y estado_revision = 'PENDIENTE'.
    REGLA INQUEBRANTABLE: Jamás confirma ni mueve stock en Kardex automáticamente.
    Si algún ítem no tiene equivalencia, genera Incidencia 'PRODUCTO_SIN_HOMOLOGAR'.
    """
    captura = DocumentoCaptura.objects.select_for_update().filter(
        pk=captura_id,
        empresa_id=empresa_id,
    ).first()

    if captura is None:
        raise ValidationError({'captura_id': 'Captura no encontrada para esta empresa.'})

    if captura.documento_id is not None:
        raise ValidationError({
            'documento': f'Esta captura ya generó el documento borrador #{captura.documento_id}.'
        })

    campos = captura.campos.all()
    if not campos.exists():
        raise ValidationError({'captura': 'La captura no contiene campos extraídos para generar un comprobante.'})

    # Valores efectivos (valor_corregido si existe, sino valor_extraido): misma lectura que la
    # vista previa de homologación (QA2-001).
    cabecera, detalles = valores_captura(captura)

    # 1. Clasificación (Bloque 3): COMPRA/VENTA y tipo de operación según RUC
    #    emisor/receptor, tipo de comprobante y motivo de la nota. Sin adivinar.
    empresa = Empresa.objects.get(pk=empresa_id)
    clasificacion = clasificar_comprobante(cabecera=cabecera, ruc_empresa=empresa.ruc)
    clase = clasificacion['clase']
    ruc_emisor = ''.join(ch for ch in cabecera.get('ruc_emisor', '') if ch.isdigit())

    tipo_comp = TipoComprobante.objects.filter(codigo_sunat=clasificacion['tipo_comprobante'], activo=True).first()
    if tipo_comp is None:
        raise ValidationError({
            'tipo_comprobante': f"El tipo de comprobante {clasificacion['tipo_comprobante']} no está registrado en el catálogo."
        })
    tipo_op = TipoOperacion.objects.filter(codigo_interno=clasificacion['codigo_operacion'], activo=True).first()
    if tipo_op is None:
        raise ValidationError({
            'tipo_operacion': (
                f"Falta el tipo de operación '{clasificacion['codigo_operacion']}' en el catálogo "
                '(ejecute seed_catalogos_sunat). No se usará otro tipo en su lugar.'
            )
        })

    # 2. Tercero: proveedor (compra) o cliente (venta).
    doc_tercero = clasificacion['contraparte_documento']
    tercero = tercero_por_documento(
        empresa_id=empresa_id, documento=doc_tercero, crear=True,
        nombre=clasificacion['contraparte_nombre'] or '', clase=clase,
    )
    if tercero is None and clase == 'COMPRA':
        raise ValidationError({'ruc_emisor': 'El RUC del proveedor no es válido.'})
    # Bloque 16: mismas reglas comerciales que el registro manual (rol del tercero, factura con RUC).
    from apps.documentos.services import validar_tercero_comercial
    validar_tercero_comercial(clase=clase, tipo_comprobante=tipo_comp, tercero=tercero)

    # 3. Serie y Número normalizados con función centralizada de documentos (A-06)
    from apps.documentos.services import normalizar_numero, normalizar_serie, validar_duplicado_documento
    serie_raw = cabecera.get('serie', '').strip()
    num_raw = cabecera.get('numero', '').strip()
    if not serie_raw or not num_raw:
        # Bloque 5: sin serie/número no se inventan (antes F001-1); revisión manual.
        raise ValidationError({'serie': 'El comprobante no indica serie y número. Corríjalos antes de generar el borrador.'})
    serie_norm = normalizar_serie(serie_raw)
    num_norm = normalizar_numero(num_raw)

    # Validar duplicados contra la clave lógica oficial de la empresa (A-06)
    validar_duplicado_documento(
        empresa_id=empresa_id,
        ruc_emisor=ruc_emisor,
        tipo_comprobante_id=tipo_comp.id,
        serie_normalizada=serie_norm,
        numero_normalizado=num_norm,
    )

    # 3.1 Documento de origen para notas (NC / ND)
    documento_origen = None
    if tipo_comp.es_nota:
        ref_doc = cabecera.get('doc_modificado') or cabecera.get('documento_modificado')
        if ref_doc:
            ref_serie = ''
            ref_num = ''
            if '-' in ref_doc:
                partes_ref = ref_doc.split('-', 1)
                ref_serie = normalizar_serie(partes_ref[0])
                ref_num = normalizar_numero(partes_ref[1])
            else:
                ref_serie = normalizar_serie(ref_doc[:4])
                ref_num = normalizar_numero(ref_doc[4:])
            documento_origen = Documento.objects.filter(
                empresa_id=empresa_id,
                clase=clase,
                ruc_emisor=ruc_emisor,
                serie_normalizada=ref_serie,
                numero_normalizado=ref_num,
            ).exclude(tipo_comprobante__es_nota=True).order_by('id').first()

    # 4. Fecha de emisión (CON-001): debe ser válida; nunca se reemplaza por "hoy".
    fecha_emision = parsear_fecha_calendario(cabecera.get('fecha_emision'), campo='fecha_emision')

    # 5. Período (CON-001): solo el período ABIERTO que contiene exactamente la fecha.
    #    Sin fallback al "último período abierto".
    periodo = periodo_abierto_para_fecha(empresa_id=empresa_id, fecha=fecha_emision, campo='fecha_emision')

    # 6. Moneda y Tipo de Cambio (CON-006): no se asume PEN ni se inventa un TC.
    from apps.documentos.services import MONEDAS_SOPORTADAS, resolver_tipo_cambio_usd
    moneda_cod = (cabecera.get('moneda') or '').strip().upper()
    if not moneda_cod:
        raise ValidationError({'moneda': 'El comprobante no indica la moneda. Corríjala antes de generar el borrador.'})
    if moneda_cod not in MONEDAS_SOPORTADAS:
        raise ValidationError({
            'moneda': f"La moneda '{moneda_cod}' del comprobante no está soportada para valorizar (solo PEN o USD)."
        })
    moneda = Moneda.objects.filter(codigo=moneda_cod).first()
    if not moneda:
        raise ValidationError({'moneda': f"La moneda '{moneda_cod}' no está registrada en el sistema."})

    tipo_cambio = None
    fecha_tc = None
    monto_tc = None
    fuente_tc = None
    if moneda.codigo == 'USD':
        # Si no hay TC aplicable se rechaza el borrador completo (rollback de esta
        # transacción); la captura y sus campos se conservan para reintentar luego.
        tc = resolver_tipo_cambio_usd(fecha_emision)
        tipo_cambio = tc
        fecha_tc = tc.fecha_publicacion
        monto_tc = tc.venta
        fuente_tc = tc.fuente

    # 7. Totales
    def parse_dec(val: str, default: Decimal = DECIMAL_CERO) -> Decimal:
        try:
            return Decimal(val.replace(',', '')).quantize(Q8, rounding=ROUND_HALF_UP)
        except Exception:
            return default

    subtotal = parse_dec(cabecera.get('subtotal', '0'))
    igv = parse_dec(cabecera.get('igv', '0'))
    total = parse_dec(cabecera.get('total', '0'))
    if total == DECIMAL_CERO:
        total = subtotal + igv

    # 8. Almacén destino por defecto
    almacen = None
    if almacen_id:
        almacen = Almacen.objects.filter(pk=almacen_id, empresa_id=empresa_id, activo=True).first()
    if not almacen:
        almacen = Almacen.objects.filter(empresa_id=empresa_id, activo=True).first()
    if not almacen:
        raise ValidationError({'almacen': 'La empresa no cuenta con un almacén activo disponible.'})

    # 9. Tipo de operación: ya resuelto por la clasificación (sin tipos "parecidos").

    # 10. Crear Documento en BORRADOR estricto
    documento = Documento.objects.create(
        empresa_id=empresa_id,
        clase=clase,
        periodo=periodo,
        tercero=tercero,
        ruc_emisor=ruc_emisor,
        tipo_comprobante=tipo_comp,
        serie=serie_raw,
        serie_normalizada=serie_norm,
        numero=num_raw,
        numero_normalizado=num_norm,
        fecha_emision=fecha_emision,
        moneda_codigo=moneda,
        tipo_cambio=tipo_cambio,
        fecha_tc=fecha_tc,
        monto_tc=monto_tc,
        fuente_tc=fuente_tc,
        subtotal=subtotal,
        igv=igv,
        total=total,
        documento_origen=documento_origen,
        origen_captura=captura.tipo,
        estado='BORRADOR',
        estado_revision='PENDIENTE',
        creado_por=usuario,
    )

    incidencias_creadas: List[Dict[str, Any]] = []

    if tipo_comp.es_nota and not documento_origen:
        inc_origen = Incidencia.objects.create(
            empresa_id=empresa_id,
            periodo=periodo,
            documento=documento,
            producto=None,
            tipo='DOCUMENTO_ORIGEN_PENDIENTE',
            severidad='ADVERTENCIA',
            bloquea_cierre=True,
            estado='PENDIENTE',
            descripcion=(
                f"La Nota {serie_norm}-{num_norm} ({clase}) "
                f"{'de ' + tercero.razon_social + ' ' if tercero else ''}"
                f"no tiene un comprobante de origen identificable ({cabecera.get('doc_modificado') or 'sin referencia'}). "
                "Regístrela manualmente o registre primero el documento de origen."
            ),
            detalle={'captura_id': captura.id, 'referencia': cabecera.get('doc_modificado', '')},
        )
        incidencias_creadas.append({
            'incidencia_id': inc_origen.id,
            'tipo': 'DOCUMENTO_ORIGEN_PENDIENTE',
        })

    from apps.documentos.services import obtener_porcentaje_credito_fiscal
    porcentaje_cf = obtener_porcentaje_credito_fiscal(empresa_id, periodo)
    tasa = tasa_igv(empresa_id, fecha_emision)  # Bloque 5: tasa vigente en la fecha del comprobante
    # Bloque 4: evidencia a nivel de documento. Si el IGV total del comprobante es la tasa
    # aplicada a TODO el subtotal, todas sus líneas son gravadas.
    documento_gravado = (
        igv > DECIMAL_CERO and subtotal > DECIMAL_CERO
        and abs(igv - igv_esperado(subtotal, tasa)) <= TOLERANCIA_IGV
    )

    # 11. Crear Líneas de DocumentoDetalle
    for index, (linea_num, line_fields) in enumerate(sorted(detalles.items()), start=1):
        cod_ext = (line_fields.get('codigo_externo') or '').strip()
        desc_ext = (line_fields.get('descripcion') or '').strip()
        if not cod_ext and not desc_ext:
            raise ValidationError({'descripcion': (
                f'Línea {index}: sin código ni descripción del bien (no se inventa un ítem). '
                'Corrija los campos de la línea antes de generar el borrador.'
            )})
        und_ext = (line_fields.get('unidad_medida') or 'NIU').strip()

        cant = parse_dec(line_fields.get('cantidad', '1.0'), default=DECIMAL_UNO)
        precio = parse_dec(line_fields.get('precio_unitario', '0.0'), default=DECIMAL_CERO)
        val_linea = parse_dec(line_fields.get('valor_total', str(cant * precio)), default=cant * precio)

        # Homologación con la regla canónica (apps.inventario.homologacion): la misma que la
        # vista previa de la captura. Compra: equivalencia del proveedor; venta: código interno.
        resultado = homologar_linea(
            empresa_id=empresa_id, clase=clase, tercero=tercero, codigo=cod_ext, descripcion=desc_ext, unidad=und_ext,
        )
        motivo_homologacion = resultado['motivo']
        tiene_homologacion = resultado['estado'] == 'HOMOLOGADA'
        prod = resultado['producto']
        prod_und = resultado['producto_unidad']
        factor = resultado['factor'] if tiene_homologacion else DECIMAL_UNO
        cant_base = (cant * factor).quantize(Q8, rounding=ROUND_HALF_UP) if tiene_homologacion else cant

        # Bloque 3: afectación e IGV de la línea. XML: los del comprobante, validados igual
        # que en el registro manual. OCR (sin esos datos): gravado al 18 %, como antes.
        codigo_afectacion = (line_fields.get('codigo_afectacion_igv') or '').strip() or None
        afectacion_indicada = (line_fields.get('afectacion_igv') or '').strip().upper() or None
        if 'igv' in line_fields and (line_fields.get('igv') or '').strip():
            igv_linea = parse_dec(line_fields['igv'])
        else:
            igv_linea = None
        # Bloque 4: la afectación nunca se supone. Sin código/afectación indicados, solo un
        # IGV > 0 en el comprobante evidencia una línea gravada; si no, revisión manual.
        if afectacion_indicada is None and codigo_afectacion is None:
            if (igv_linea is not None and igv_linea > DECIMAL_CERO) or (igv_linea is None and documento_gravado):
                afectacion_indicada = 'GRAVADO'
            else:
                raise ValidationError({'afectacion_igv': (
                    f"Línea {index}: el comprobante no permite determinar la afectación del IGV "
                    '(gravado, exonerado, inafecto, exportación o gratuito). Corrija el campo '
                    "'afectacion_igv' o 'codigo_afectacion_igv' de la línea y vuelva a generar el borrador."
                )})
        afectacion_igv, codigo_afectacion = resolver_afectacion(
            afectacion=afectacion_indicada, codigo=codigo_afectacion, es_bonificacion=False, linea_num=index,
        )
        if igv_linea is None and afectacion_igv == 'GRAVADO' and not documento_gravado:
            # Bloque 5: el IGV de la línea solo se calcula si el IGV del documento es la tasa
            # sobre todo el subtotal; si no (líneas mixtas o IGV no leído), revisión manual.
            raise ValidationError({'igv': (
                f"Línea {index}: gravada sin IGV de línea y el IGV del comprobante no corresponde a todo el "
                "subtotal. Indique el campo 'igv' de la línea y vuelva a generar el borrador."
            )})
        if igv_linea is None:
            igv_linea = (val_linea * tasa).quantize(Q8, rounding=ROUND_HALF_UP) if afectacion_igv == 'GRAVADO' else DECIMAL_CERO
        validar_igv_linea(igv=igv_linea, base=val_linea, afectacion=afectacion_igv, linea_num=index, tasa=tasa)

        # Cálculo de Costo Unitario PEN (C-04: factor de empaque, moneda USD e IGV no recuperable)
        valor_linea_calc = cant * precio
        porcentaje_no_recup = (Decimal('100.0000') - porcentaje_cf) / Decimal('100.0000')
        igv_no_recuperable = igv_linea * porcentaje_no_recup
        costo_linea_doc = valor_linea_calc + igv_no_recuperable

        if moneda.codigo == 'USD':
            costo_linea_pen = costo_linea_doc * monto_tc
        else:
            costo_linea_pen = costo_linea_doc

        if clase != 'COMPRA':
            # Venta: el costo lo asigna el motor (CPP o costo del movimiento origen),
            # nunca el precio de venta del comprobante.
            costo_unitario_pen = None
        elif cant_base > DECIMAL_CERO:
            costo_unitario_pen = (costo_linea_pen / cant_base).quantize(Q8, rounding=ROUND_HALF_UP)
        else:
            costo_unitario_pen = DECIMAL_CERO

        # Devolución física: vincular la línea del documento de origen cuando es inequívoca.
        detalle_origen = None
        if documento_origen is not None and prod is not None and tipo_op.naturaleza in ('ENTRADA', 'SALIDA'):
            candidatas = list(documento_origen.detalles.filter(producto=prod)[:2])
            if len(candidatas) == 1:
                detalle_origen = candidatas[0]

        det = DocumentoDetalle.objects.create(
            documento=documento,
            linea=index,
            producto=prod,
            producto_unidad=prod_und,
            almacen=almacen,
            tipo_operacion=tipo_op,
            afecta_kardex_aplicado=tipo_op.afecta_kardex,
            equivalencia=resultado["equivalencia"],
            descripcion_original=desc_ext or (prod.descripcion if prod else f'Ítem {index}'),
            cantidad_original=cant,
            factor_conversion=factor,
            cantidad_base=cant_base,
            precio_unitario=precio,
            igv=igv_linea,
            porcentaje_credito_fiscal_aplicado=porcentaje_cf,
            costo_unitario_pen=costo_unitario_pen,
            es_bonificacion=False,
            afectacion_igv=afectacion_igv,
            codigo_afectacion_igv=codigo_afectacion,
            detalle_origen=detalle_origen,
        )

        if (tipo_comp.es_nota and documento_origen is not None and prod is not None
                and tipo_op.naturaleza in ('ENTRADA', 'SALIDA') and detalle_origen is None):
            inc_det = Incidencia.objects.create(
                empresa_id=empresa_id, periodo=periodo, documento=documento, documento_detalle=det,
                producto=prod, tipo='DETALLE_ORIGEN_PENDIENTE', severidad='ADVERTENCIA',
                bloquea_cierre=True, estado='PENDIENTE',
                descripcion=(
                    f'Línea #{det.linea}: no se pudo identificar de forma única la línea del documento de origen '
                    f'{documento_origen.serie_normalizada}-{documento_origen.numero_normalizado} para '
                    f'{prod.codigo_interno}. Regístrela manualmente.'
                ),
                detalle={'documento_id': documento.id, 'documento_origen_id': documento_origen.id},
            )
            incidencias_creadas.append({'incidencia_id': inc_det.id, 'tipo': 'DETALLE_ORIGEN_PENDIENTE', 'linea': det.linea})

        if not tiene_homologacion:
            # Regla: Registrar Incidencia bloqueante 'PRODUCTO_SIN_HOMOLOGAR'
            inc = Incidencia.objects.create(
                empresa_id=empresa_id,
                periodo=periodo,
                documento=documento,
                documento_detalle=det,
                producto=None,
                tipo='PRODUCTO_SIN_HOMOLOGAR',
                severidad='ADVERTENCIA',
                bloquea_cierre=True,
                estado='PENDIENTE',
                descripcion=(
                    f"Línea #{det.linea} ({cod_ext or desc_ext}) "
                    f"{'del proveedor ' + tercero.razon_social + ' ' if clase == 'COMPRA' and tercero else ''}"
                    f"no cuenta con equivalencia confirmada en ProductoEquivalencia"
                    f"{' (' + motivo_homologacion + ')' if motivo_homologacion.startswith('existe') else ''}."
                ),
                detalle={
                    'documento_id': documento.id,
                    'documento_detalle_id': det.id,
                    'linea': det.linea,
                    'tercero_id': tercero.id if tercero else None,
                    'codigo_externo': cod_ext,
                    'descripcion_externa': desc_ext,
                    'unidad_externa': und_ext,
                    'cantidad': str(cant),
                    'precio_unitario': str(precio),
                },
            )
            incidencias_creadas.append({
                'incidencia_id': inc.id,
                'linea': det.linea,
                'codigo_externo': cod_ext,
                'descripcion': desc_ext,
            })

    # Vincular captura con el documento y actualizar estado
    captura.documento = documento
    captura.estado_proceso = 'BORRADOR_GENERADO'
    captura.save(update_fields=['documento', 'estado_proceso'])

    registrar_auditoria(
        empresa_id=empresa_id,
        usuario_id=usuario.id,
        accion='GENERAR_BORRADOR_DESDE_CAPTURA',
        entidad='DOCUMENTO',
        registro_id=documento.id,
        valor_anterior=None,
        valor_nuevo={
            'captura_id': captura.id,
            'estado': documento.estado,
            'lineas_totales': len(detalles),
            'lineas_sin_homologar': len(incidencias_creadas),
        },
    )

    return {
        'documento_id': documento.id,
        'clase': documento.clase,
        'tipo_operacion': tipo_op.codigo_interno,
        'serie_numero': f"{documento.serie_normalizada}-{documento.numero_normalizado}",
        'estado': documento.estado,
        'estado_revision': documento.estado_revision,
        'total_lineas': len(detalles),
        'lineas_sin_homologar': len(incidencias_creadas),
        'incidencias': incidencias_creadas,
        'mensaje': 'Comprobante borrador generado exitosamente en estado BORRADOR y PENDIENTE.',
    }
