"""
Importación Excel — paso 4: diferencias entre el costo que traía el Excel y el costo que calculó el Kardex.

Por cada línea importada se compara el costo unitario del Excel (convertido a soles con el tipo de
cambio del comprobante si vino en dólares) contra el costo unitario del movimiento valorizado por el
sistema. Todo en Decimal; la pantalla recibe los montos ya calculados como texto.
"""
import io
from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

CERO = Decimal('0')
TOLERANCIA_REDONDEO = Decimal('0.01')   # verde: diferencia unitaria hasta S/ 0.01
UMBRAL_AMBAR_PCT = Decimal('5')          # ámbar: hasta 5 % del costo del Excel; más es rojo
NIVELES = ('VERDE', 'AMBAR', 'ROJO')
ETIQUETA_NIVEL = {'VERDE': 'OK', 'AMBAR': 'Error A · diferencia menor', 'ROJO': 'Error B · diferencia crítica'}

U4 = Decimal('0.0001')
U2 = Decimal('0.01')


def clasificar(costo_excel, costo_sistema):
    """Devuelve (nivel, porcentaje, motivo). costo_excel ya en soles; None o 0 = sin costo en el Excel."""
    if costo_sistema is None:
        return 'ROJO', None, 'El Kardex no tiene costo calculado para esta línea.'
    if not costo_excel:
        return 'ROJO', None, 'La línea vino con costo 0 en el Excel.'
    diferencia = abs(costo_sistema - costo_excel)
    porcentaje = diferencia * 100 / abs(costo_excel)
    if diferencia <= TOLERANCIA_REDONDEO:
        return 'VERDE', porcentaje, ''
    if porcentaje <= UMBRAL_AMBAR_PCT:
        return 'AMBAR', porcentaje, ''
    return 'ROJO', porcentaje, f'Diferencia mayor al {UMBRAL_AMBAR_PCT} %.'


def _operacion(documento):
    if documento.tipo_comprobante.codigo_sunat == '07':
        return 'Devolución'
    return 'Compra' if documento.clase == 'COMPRA' else 'Venta'


def _texto(valor, unidad):
    return None if valor is None else str(valor.quantize(unidad))


def _lineas_lote(empresa_id, lote):
    from django.db.models import Q
    from apps.documentos.models import DocumentoDetalle
    from apps.kardex.models import Movimiento

    # Las líneas del lote: las de sus comprobantes y las que agregó a comprobantes de otro lote
    # («Completar comprobante»); no las que otro lote agregó a los suyos.
    detalles = list(
        DocumentoDetalle.objects.filter(documento__empresa_id=empresa_id)
        .filter(Q(importacion_lote=lote) | Q(importacion_lote__isnull=True, documento__importacion_lote=lote))
        .select_related('documento__tipo_comprobante', 'documento__tipo_cambio', 'producto')
        .order_by('documento__fecha_emision', 'documento_id', 'linea')
    )
    valorizacion = {
        m.documento_detalle_id: getattr(m, 'valorizacion', None)
        for m in Movimiento.objects.filter(documento_detalle__in=detalles, movimiento_extornado__isnull=True)
        .select_related('valorizacion')
    }
    lineas = []
    for d in detalles:
        doc = d.documento
        tasa = Decimal('1')
        if doc.moneda_codigo_id != 'PEN' and doc.tipo_cambio and doc.tipo_cambio.venta:
            tasa = doc.tipo_cambio.venta
        cantidad = d.cantidad_original or CERO
        cu_excel = d.costo_unitario_importado * tasa if d.costo_unitario_importado is not None else None
        if d.costo_total_importado is not None:
            total_excel = d.costo_total_importado * tasa
        else:
            total_excel = (cu_excel or CERO) * cantidad
        val = valorizacion.get(d.id)
        cu_sistema = val.costo_unitario_pen if val else None
        total_sistema = val.valor_movimiento_pen if val else None
        if total_sistema is not None:
            total_sistema = abs(total_sistema)
        nivel, porcentaje, motivo = clasificar(cu_excel, cu_sistema)
        diferencia_total = (total_sistema - total_excel) if total_sistema is not None else None
        lineas.append({
            'detalle_id': d.id,
            'documento_id': doc.id,
            'fecha': doc.fecha_emision,
            'comprobante': f'{doc.serie}-{doc.numero}',
            'operacion': _operacion(doc),
            'producto_id': d.producto_id,
            'producto_codigo': d.producto.codigo_interno,
            'producto': d.producto.descripcion,
            'cantidad': cantidad,
            'costo_unitario_excel': cu_excel,
            'costo_unitario_sistema': cu_sistema,
            'diferencia_unitaria': (cu_sistema - (cu_excel or CERO)) if cu_sistema is not None else None,
            'porcentaje': porcentaje,
            'costo_total_excel': total_excel,
            'costo_total_sistema': total_sistema,
            'diferencia_total': diferencia_total,
            'nivel': nivel,
            'motivo': motivo,
        })
    return lineas


def _resumen(lineas):
    neta = sum((l['diferencia_total'] for l in lineas if l['diferencia_total'] is not None), CERO)
    absoluta = sum((abs(l['diferencia_total']) for l in lineas if l['diferencia_total'] is not None), CERO)
    return {
        'lineas': len(lineas),
        **{n.lower(): sum(1 for l in lineas if l['nivel'] == n) for n in NIVELES},
        'valor_excel': sum((l['costo_total_excel'] for l in lineas), CERO),
        'valor_sistema': sum((l['costo_total_sistema'] for l in lineas if l['costo_total_sistema'] is not None), CERO),
        'diferencia_neta': neta,
        'diferencia_absoluta': absoluta,
    }


def diferencias_lote(empresa_id, lote_id, producto_id=None, nivel=None):
    """Datos crudos (Decimal) del cuadro de diferencias de un lote, con filtros opcionales."""
    from apps.documentos.models import ImportacionLote

    lote = ImportacionLote.objects.filter(empresa_id=empresa_id, pk=lote_id).select_related('almacen').first()
    if lote is None:
        raise NotFound('El lote no existe en esta empresa.')
    if lote.estado != 'CONFIRMADO':
        # Al anular, los extornos recalculan el Kardex: los costos ya no corresponden a la importación.
        raise ValidationError({'lote': 'El lote está anulado: su efecto en el Kardex se revirtió y no hay costos que comparar.'})
    if nivel and nivel not in NIVELES:
        raise ValidationError({'nivel': 'Use VERDE, AMBAR o ROJO.'})
    if producto_id not in (None, ''):
        try:
            producto_id = int(producto_id)
        except (TypeError, ValueError):
            raise ValidationError({'producto': 'Producto inválido.'})
    else:
        producto_id = None

    todas = _lineas_lote(empresa_id, lote)
    productos = {}
    for l in todas:
        productos.setdefault(l['producto_id'], {'id': l['producto_id'], 'codigo': l['producto_codigo'], 'descripcion': l['producto']})
    lineas = [
        l for l in todas
        if (producto_id is None or l['producto_id'] == producto_id) and (not nivel or l['nivel'] == nivel)
    ]
    return {
        'lote': lote,
        'lineas': lineas,
        'resumen': _resumen(lineas),
        'productos': sorted(productos.values(), key=lambda p: p['codigo']),
    }


def diferencias_lote_json(empresa_id, lote_id, producto_id=None, nivel=None):
    datos = diferencias_lote(empresa_id, lote_id, producto_id, nivel)
    r = datos['resumen']
    return {
        'lote': {'id': datos['lote'].id, 'estado': datos['lote'].estado},
        'umbrales': {'tolerancia': str(TOLERANCIA_REDONDEO), 'ambar_pct': str(UMBRAL_AMBAR_PCT)},
        'productos': datos['productos'],
        'resumen': {
            'lineas': r['lineas'], 'verde': r['verde'], 'ambar': r['ambar'], 'rojo': r['rojo'],
            'valor_excel': _texto(r['valor_excel'], U2), 'valor_sistema': _texto(r['valor_sistema'], U2),
            'diferencia_neta': _texto(r['diferencia_neta'], U2), 'diferencia_absoluta': _texto(r['diferencia_absoluta'], U2),
        },
        'lineas': [{
            **{k: l[k] for k in ('detalle_id', 'documento_id', 'comprobante', 'operacion', 'producto_id', 'producto_codigo', 'producto', 'nivel', 'motivo')},
            'fecha': l['fecha'].isoformat(),
            'cantidad': f"{l['cantidad'].normalize():f}" if l['cantidad'] else '0',
            'costo_unitario_excel': _texto(l['costo_unitario_excel'], U4),
            'costo_unitario_sistema': _texto(l['costo_unitario_sistema'], U4),
            'diferencia_unitaria': _texto(l['diferencia_unitaria'], U4),
            'porcentaje': _texto(l['porcentaje'], U2),
            'costo_total_excel': _texto(l['costo_total_excel'], U2),
            'costo_total_sistema': _texto(l['costo_total_sistema'], U2),
            'diferencia_total': _texto(l['diferencia_total'], U2),
        } for l in datos['lineas']],
    }


def exportar_diferencias_excel(empresa_id, lote_id, producto_id=None, nivel=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    from apps.reportes.excel_seguro import neutralizar_formulas

    datos = diferencias_lote(empresa_id, lote_id, producto_id, nivel)
    lote, r = datos['lote'], datos['resumen']
    colores = {'VERDE': 'D1FAE5', 'AMBAR': 'FEF3C7', 'ROJO': 'FEE2E2'}
    negrita = Font(bold=True)

    libro = Workbook()
    hoja = libro.active
    hoja.title = 'Diferencias'
    hoja.append([f'Diferencias de costo · Lote de importación #{lote.id}'])
    hoja['A1'].font = Font(bold=True, size=13)
    hoja.append([f'Almacén {lote.almacen.codigo} · Estado {lote.estado} · Generado {timezone.localtime():%d/%m/%Y %H:%M}'])
    filtro = []
    if producto_id:
        p = next((p for p in datos['productos'] if p['id'] == int(producto_id)), None)
        filtro.append(f"Producto {p['codigo'] if p else producto_id}")
    if nivel:
        filtro.append(f'Nivel {ETIQUETA_NIVEL[nivel]}')
    hoja.append(['Filtro: ' + (' · '.join(filtro) if filtro else 'todas las líneas')])
    hoja.append([f'Verde: diferencia unitaria ≤ S/ {TOLERANCIA_REDONDEO}. Ámbar: ≤ {UMBRAL_AMBAR_PCT} %. '
                 f'Rojo: más de {UMBRAL_AMBAR_PCT} % o sin costo en el Excel.'])
    hoja.append([])
    for etiqueta, valor in (
        ('Líneas', r['lineas']), ('Verde (OK)', r['verde']), ('Ámbar (Error A)', r['ambar']), ('Rojo (Error B)', r['rojo']),
        ('Valor según Excel (S/)', r['valor_excel']), ('Valor según Kardex (S/)', r['valor_sistema']),
        ('Diferencia neta (S/)', r['diferencia_neta']), ('Diferencia absoluta (S/)', r['diferencia_absoluta']),
    ):
        hoja.append([etiqueta, valor])
        hoja.cell(hoja.max_row, 1).font = negrita
        if isinstance(valor, Decimal):
            hoja.cell(hoja.max_row, 2).number_format = '#,##0.00'
    hoja.append([])

    encabezado = ['Fecha', 'Comprobante', 'Operación', 'Código', 'Producto', 'Cantidad',
                  'C. unit. Excel', 'C. unit. Kardex', 'Dif. unit.', 'Dif. %',
                  'C. total Excel', 'C. total Kardex', 'Dif. total', 'Nivel', 'Observación']
    hoja.append(encabezado)
    fila_encabezado = hoja.max_row
    for celda in hoja[fila_encabezado]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor='17365D')
        celda.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    for l in datos['lineas']:
        hoja.append([
            l['fecha'], l['comprobante'], l['operacion'], l['producto_codigo'], l['producto'], l['cantidad'],
            l['costo_unitario_excel'], l['costo_unitario_sistema'], l['diferencia_unitaria'],
            l['porcentaje'] / 100 if l['porcentaje'] is not None else None,
            l['costo_total_excel'], l['costo_total_sistema'], l['diferencia_total'],
            ETIQUETA_NIVEL[l['nivel']], l['motivo'],
        ])
        n = hoja.max_row
        hoja.cell(n, 1).number_format = 'DD/MM/YYYY'
        for col in (7, 8, 9):
            hoja.cell(n, col).number_format = '#,##0.0000'
        hoja.cell(n, 10).number_format = '0.00%'
        for col in (11, 12, 13):
            hoja.cell(n, col).number_format = '#,##0.00'
        hoja.cell(n, 14).fill = PatternFill('solid', fgColor=colores[l['nivel']])
    for col, ancho in zip('ABCDEFGHIJKLMNO', (11, 16, 12, 12, 34, 10, 13, 13, 11, 9, 13, 13, 12, 26, 40)):
        hoja.column_dimensions[col].width = ancho
    hoja.freeze_panes = hoja.cell(fila_encabezado + 1, 1)
    if datos['lineas']:
        hoja.auto_filter.ref = f'A{fila_encabezado}:O{hoja.max_row}'

    neutralizar_formulas(libro)
    salida = io.BytesIO()
    libro.save(salida)
    salida.seek(0)
    return salida
