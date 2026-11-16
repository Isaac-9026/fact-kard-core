"""Excel del reporte de Costo de venta (mismos números que la pantalla; no recalcula nada)."""
import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.reportes.costo_ventas import CLAVES_COMPRA, CLAVES_DESGLOSE, generar_costo_ventas
from apps.reportes.excel_seguro import neutralizar_formulas

AZUL = '17365D'
AZUL_CLARO = 'D9EAF7'
VERDE = 'E2F0D9'
BORDE = Border(*(Side(style='thin', color='A6A6A6'),) * 4)
FMT_CANT = '#,##0.00######'
FMT_MONTO = '#,##0.00'

ETIQUETAS_COMPRA = {
    'compras': 'Compras', 'bonificaciones': 'Bonificaciones recibidas',
    'devoluciones': 'Devoluciones a proveedor', 'notas_credito_debito': 'Notas de crédito / débito de compra',
}
ETIQUETAS_DESGLOSE = {
    'ventas': 'Mercadería vendida', 'devoluciones_venta': 'Devoluciones de clientes',
    'mermas_desmedros': 'Mermas y desmedros', 'consumo_retiros': 'Consumo interno y retiros',
    'ajustes': 'Ajustes de inventario', 'transferencias': 'Transferencias entre almacenes', 'otros': 'Otros',
}


def nombre_archivo_costo_ventas(reporte):
    ruc = ''.join(c for c in str(reporte['empresa']['ruc'] or '') if c.isalnum())[:20]
    desde, hasta = reporte['periodo_desde']['etiqueta'], reporte['periodo_hasta']['etiqueta']
    rango = desde if desde == hasta else f'{desde}_a_{hasta}'
    return '_'.join(['Costo_de_venta', rango] + ([ruc] if ruc else [])) + '.xlsx'


def _num(valor):
    return Decimal(valor) if valor not in (None, '') else None


def _celda(hoja, fila, col, valor, fmt=None, negrita=False, relleno=None):
    celda = hoja.cell(fila, col, valor)
    if fmt:
        celda.number_format = fmt
    if negrita:
        celda.font = Font(bold=True)
    if relleno:
        celda.fill = PatternFill('solid', fgColor=relleno)
    celda.border = BORDE
    return celda


def _encabezado(hoja, reporte, titulo):
    hoja['A1'] = titulo
    hoja['A1'].font = Font(bold=True, size=14, color=AZUL)
    hoja['A2'] = f"{reporte['empresa']['razon_social']} — RUC {reporte['empresa']['ruc']}"
    desde, hasta = reporte['periodo_desde']['etiqueta'], reporte['periodo_hasta']['etiqueta']
    hoja['A3'] = f"Período: {desde}" + ('' if desde == hasta else f' a {hasta}') + \
        f"  ({reporte['fecha_inicio']} al {reporte['fecha_fin']}) — Importes en soles (PEN)"
    hoja['A4'] = reporte['formula']
    hoja['A4'].font = Font(italic=True)


def _hoja_resumen(hoja, reporte):
    _encabezado(hoja, reporte, 'COSTO DE VENTA')
    t = reporte['totales']
    filas = [
        ('Saldo inicial', t['saldo_inicial']['valor'], False),
        ('+ Compras netas', t['compras']['valor'], False),
        *[(f'      {ETIQUETAS_COMPRA[k]}', t['compras_detalle'][k], False) for k in CLAVES_COMPRA],
        ('− Saldo final', t['saldo_final']['valor'], False),
        ('= COSTO DE VENTA', t['costo_venta']['valor'], True),
    ]
    fila = 6
    for etiqueta, valor, total in filas:
        _celda(hoja, fila, 1, etiqueta, negrita=total, relleno=AZUL_CLARO if total else None)
        _celda(hoja, fila, 2, _num(valor), FMT_MONTO, negrita=total, relleno=AZUL_CLARO if total else None)
        fila += 1
    fila += 1
    _celda(hoja, fila, 1, 'Desglose informativo del costo de venta', negrita=True, relleno=VERDE)
    _celda(hoja, fila, 2, None, relleno=VERDE)
    fila += 1
    for k in CLAVES_DESGLOSE:
        _celda(hoja, fila, 1, ETIQUETAS_DESGLOSE[k])
        _celda(hoja, fila, 2, _num(t['desglose'][k]), FMT_MONTO)
        fila += 1
    _celda(hoja, fila, 1, 'Diferencia (debe ser 0)', negrita=True)
    _celda(hoja, fila, 2, _num(t['diferencia']), FMT_MONTO, negrita=True)
    hoja.column_dimensions['A'].width = 44
    hoja.column_dimensions['B'].width = 18


def _hoja_productos(hoja, reporte):
    _encabezado(hoja, reporte, 'COSTO DE VENTA POR PRODUCTO')
    grupos = [('Saldo inicial', 'saldo_inicial'), ('+ Compras', 'compras'),
              ('− Saldo final', 'saldo_final'), ('= Costo de venta', 'costo_venta')]
    fila = 6
    for col, titulo in enumerate(('Código', 'Producto', 'Unidad'), start=1):
        hoja.merge_cells(start_row=fila, start_column=col, end_row=fila + 1, end_column=col)
        _celda(hoja, fila, col, titulo, negrita=True, relleno=AZUL_CLARO)
        _celda(hoja, fila + 1, col, None, relleno=AZUL_CLARO)
    col = 4
    for titulo, _ in grupos:
        hoja.merge_cells(start_row=fila, start_column=col, end_row=fila, end_column=col + 2)
        _celda(hoja, fila, col, titulo, negrita=True, relleno=AZUL_CLARO).alignment = Alignment(horizontal='center')
        for i, sub in enumerate(('Unid.', 'P.U.', 'Total')):
            _celda(hoja, fila + 1, col + i, sub, negrita=True, relleno=AZUL_CLARO)
        col += 3
    for i, k in enumerate(CLAVES_DESGLOSE):
        _celda(hoja, fila, col + i, 'Desglose (S/)' if i == 0 else None, negrita=True, relleno=VERDE)
        _celda(hoja, fila + 1, col + i, ETIQUETAS_DESGLOSE[k], negrita=True, relleno=VERDE)
    hoja.merge_cells(start_row=fila, start_column=col, end_row=fila, end_column=col + len(CLAVES_DESGLOSE) - 1)
    fila += 2
    for p in reporte['productos']:
        _celda(hoja, fila, 1, p['producto']['codigo'])
        _celda(hoja, fila, 2, p['producto']['descripcion'])
        _celda(hoja, fila, 3, p['producto']['unidad'])
        col = 4
        for _, clave in grupos:
            bloque = p[clave]
            _celda(hoja, fila, col, _num(bloque['cantidad']), FMT_CANT)
            _celda(hoja, fila, col + 1, _num(bloque['costo_unitario']), FMT_CANT)
            _celda(hoja, fila, col + 2, _num(bloque['valor']), FMT_MONTO, negrita=clave == 'costo_venta')
            col += 3
        for i, k in enumerate(CLAVES_DESGLOSE):
            _celda(hoja, fila, col + i, _num(p['desglose'][k]['valor']), FMT_MONTO)
        fila += 1
    t = reporte['totales']
    _celda(hoja, fila, 1, 'TOTAL EMPRESA', negrita=True, relleno=AZUL_CLARO)
    hoja.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=3)
    col = 4
    for _, clave in grupos:
        _celda(hoja, fila, col, None, relleno=AZUL_CLARO)
        _celda(hoja, fila, col + 1, None, relleno=AZUL_CLARO)
        _celda(hoja, fila, col + 2, _num(t[clave]['valor']), FMT_MONTO, negrita=True, relleno=AZUL_CLARO)
        col += 3
    for i, k in enumerate(CLAVES_DESGLOSE):
        _celda(hoja, fila, col + i, _num(t['desglose'][k]), FMT_MONTO, negrita=True, relleno=AZUL_CLARO)
    anchos = {1: 14, 2: 40, 3: 8}
    for c in range(1, col + len(CLAVES_DESGLOSE)):
        hoja.column_dimensions[get_column_letter(c)].width = anchos.get(c, 15)
    hoja.freeze_panes = 'D8'


def generar_excel_costo_ventas(**filtros):
    reporte = generar_costo_ventas(**filtros)
    libro = Workbook()
    _hoja_resumen(libro.active, reporte)
    libro.active.title = 'Resumen'
    _hoja_productos(libro.create_sheet('Por producto'), reporte)
    neutralizar_formulas(libro)
    buffer = io.BytesIO()
    libro.save(buffer)
    buffer.seek(0)
    return buffer, nombre_archivo_costo_ventas(reporte)
