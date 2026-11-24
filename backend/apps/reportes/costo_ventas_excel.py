"""Hoja "Costo de Venta" del Excel del Kardex Valorizado."""
from decimal import Decimal

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.reportes.costo_ventas import CLAVES_COMPRA, CLAVES_CONCILIACION, CLAVES_VENTA, resumen_mensual

TITULO_HOJA = 'Costo de Venta'
FUENTE = 'Segoe UI'
AZUL = '17365D'
AZUL_CLARO = 'D9EAF7'
VERDE = 'E2F0D9'
AMARILLO = 'FFF2CC'
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
GRUPOS = (('Saldo inicial', 'saldo_inicial'), ('+ Compras', 'compras'), ('Subtotal', 'disponible'),
          ('− Saldo final (Kardex)', 'saldo_final'), ('= Salidas del inventario', 'salidas'),
          ('− Salidas que no son ventas', 'no_atribuibles'), ('= Costo de venta', 'costo_venta'))
NOTA_METODO = ('Resultado principal según el Kardex (promedio móvil): cuadra con el inventario valorizado. '
               'El promedio ponderado se muestra solo como comparación, con su diferencia (promedio − Kardex).')


def _es_cero(valor):
    return valor in (None, '') or Decimal(valor) == 0


def _num(valor):
    return Decimal(valor) if valor not in (None, '') else None


def _celda(hoja, fila, col, valor, fmt=None, negrita=False, relleno=None, borde=True):
    celda = hoja.cell(fila, col, valor)
    celda.font = Font(name=FUENTE, size=10, bold=negrita)
    if fmt:
        celda.number_format = fmt
    if relleno:
        celda.fill = PatternFill('solid', fgColor=relleno)
    if borde:
        celda.border = BORDE
    return celda


def _titulo(hoja, texto):
    hoja['A1'] = texto
    hoja['A1'].font = Font(name=FUENTE, bold=True, size=14, color=AZUL)


def _nota(hoja, fila, texto):
    celda = _celda(hoja, fila, 1, texto, relleno=AMARILLO, borde=False)
    celda.font = Font(name=FUENTE, size=10, italic=True)
    return fila + 1


def escribir_hoja_por_mes(hoja, reportes, *, razon_social, ruc, notas=()):
    _titulo(hoja, 'COSTO DE VENTA POR MES')
    hoja['A2'] = f'{razon_social} — RUC {ruc}'
    hoja['A3'] = 'Importes en soles (PEN), calculados con precisión completa y mostrados en céntimos.'
    fila = 4
    metodo = ('Costo de venta = Saldo inicial + Compras − Saldo final según el Kardex − Salidas que no son ventas. '
              'Cada mes parte de su saldo inicial según el Kardex y el total del año es la suma de los meses. '
              'Las columnas amarillas comparan con el promedio ponderado de cada mes (diferencia = promedio − Kardex).')
    for nota in (metodo, *notas, 'Para ver el detalle por producto, elija un período en el Kardex Valorizado.'):
        fila = _nota(hoja, fila, nota)
    fila += 1
    columnas = (('Período', None), ('Saldo inicial', 'saldo_inicial'), ('+ Compras', 'compras'),
                ('− Saldo final (Kardex)', 'saldo_final'), ('− Salidas que no son ventas', 'no_atribuibles'),
                ('= Costo de venta (Kardex)', 'costo_venta'), ('Comparación: promedio mensual', 'costo_venta_promedio'),
                ('Diferencia (promedio − Kardex)', 'diferencia_metodo'))
    for col, (texto, _) in enumerate(columnas, start=1):
        _celda(hoja, fila, col, texto, negrita=True, relleno=AMARILLO if col > 6 else AZUL_CLARO)
    fila += 1
    meses, total = resumen_mensual(reportes)
    for mes in meses:
        _celda(hoja, fila, 1, mes['periodo']['etiqueta'])
        for col, (_, clave) in enumerate(columnas[1:], start=2):
            _celda(hoja, fila, col, mes[clave], FMT_MONTO, negrita=clave == 'costo_venta')
        fila += 1
    _celda(hoja, fila, 1, 'TOTAL', negrita=True, relleno=AZUL_CLARO)
    for col, (_, clave) in enumerate(columnas[1:], start=2):
        valor = total.get(clave) if clave not in ('saldo_inicial', 'saldo_final') else None
        _celda(hoja, fila, col, valor, FMT_MONTO, negrita=True, relleno=AMARILLO if col > 6 else AZUL_CLARO)
    if not reportes:
        _nota(hoja, fila + 2, 'No hay movimientos de inventario registrados.')
    hoja.column_dimensions['A'].width = 14
    for col in range(2, len(columnas) + 1):
        hoja.column_dimensions[get_column_letter(col)].width = 18 if col <= 6 else 22


def escribir_hoja_costo_venta(hoja, reporte, notas=()):
    _titulo(hoja, 'COSTO DE VENTA')
    hoja['A2'] = f"{reporte['empresa']['razon_social']} — RUC {reporte['empresa']['ruc']}"
    desde, hasta = reporte['periodo_desde']['etiqueta'], reporte['periodo_hasta']['etiqueta']
    hoja['A3'] = (f'Período: {desde}' + ('' if desde == hasta else f' a {hasta}')
                  + f"  ({reporte['fecha_inicio']} al {reporte['fecha_fin']}) — Importes en soles (PEN)")
    hoja['A4'] = f"{reporte['formula']}  ·  {reporte['metodo']}"
    hoja['A4'].font = Font(name=FUENTE, italic=True)
    fila = 5
    for nota in notas:
        fila = _nota(hoja, fila, nota)
    fila += 1

    fila = _nota(hoja, fila, NOTA_METODO) + 1

    # ---- Resumen de la empresa ----
    t = reporte['totales']
    _celda(hoja, fila, 1, 'RESUMEN EMPRESA', negrita=True, relleno=AZUL_CLARO)
    _celda(hoja, fila, 2, 'Importe (S/)', negrita=True, relleno=AZUL_CLARO)
    fila += 1
    resumen = [
        ('Saldo inicial (Kardex)', t['saldo_inicial']['valor'], False),
        ('+ Compras netas', t['compras']['valor'], False),
        *[(f'      {ETIQUETAS_COMPRA[k]}', t['compras_detalle'][k], False) for k in CLAVES_COMPRA],
        ('Subtotal', t['disponible']['valor'], False),
        ('− Saldo final (Kardex)', t['saldo_final']['valor'], False),
        ('= Salidas del inventario', t['salidas']['valor'], False),
        *[(f'   − {ETIQUETAS_DESGLOSE[k]}', t['conciliacion'][k], False)
          for k in CLAVES_CONCILIACION if not _es_cero(t['conciliacion'][k])],
        ('= COSTO DE VENTA', t['costo_venta']['valor'], True),
    ]
    for etiqueta, valor, total in resumen:
        _celda(hoja, fila, 1, etiqueta, negrita=total, relleno=AZUL_CLARO if total else None)
        _celda(hoja, fila, 2, _num(valor), FMT_MONTO, negrita=total, relleno=AZUL_CLARO if total else None)
        fila += 1
    fila += 1
    _celda(hoja, fila, 1, 'Comprobación: salidas por ventas según el Kardex', negrita=True, relleno=VERDE)
    _celda(hoja, fila, 2, None, relleno=VERDE)
    fila += 1
    for k in CLAVES_VENTA:
        _celda(hoja, fila, 1, ETIQUETAS_DESGLOSE[k])
        _celda(hoja, fila, 2, _num(t['desglose'][k]), FMT_MONTO)
        fila += 1
    _celda(hoja, fila, 1, 'Diferencia (debe ser 0)', negrita=True)
    _celda(hoja, fila, 2, _num(t['diferencia']), FMT_MONTO, negrita=True)
    fila += 2
    _celda(hoja, fila, 1, f"Comparación: {reporte['metodo_comparacion']}", negrita=True, relleno=AMARILLO)
    _celda(hoja, fila, 2, None, relleno=AMARILLO)
    fila += 1
    for etiqueta, valor in (('Saldo final al P.U. promedio', t['comparacion']['saldo_final']['valor']),
                            ('Costo de venta con promedio', t['comparacion']['costo_venta']['valor']),
                            ('Diferencia (promedio − Kardex)', t['diferencia_metodo'])):
        _celda(hoja, fila, 1, etiqueta)
        _celda(hoja, fila, 2, _num(valor), FMT_MONTO)
        fila += 1
    fila += 2

    conciliacion = [k for k in CLAVES_CONCILIACION if not _es_cero(t['conciliacion'][k])]
    detalle = [*CLAVES_VENTA, *conciliacion]
    # ---- Detalle por producto ----
    titulo = _celda(hoja, fila, 1, 'DETALLE POR PRODUCTO', borde=False)
    titulo.font = Font(name=FUENTE, bold=True, size=12, color=AZUL)
    fila += 1
    for col, texto in enumerate(('Código', 'Producto', 'Unidad'), start=1):
        hoja.merge_cells(start_row=fila, start_column=col, end_row=fila + 1, end_column=col)
        _celda(hoja, fila, col, texto, negrita=True, relleno=AZUL_CLARO)
    col = 4
    for texto, _ in GRUPOS:
        hoja.merge_cells(start_row=fila, start_column=col, end_row=fila, end_column=col + 2)
        _celda(hoja, fila, col, texto, negrita=True, relleno=AZUL_CLARO).alignment = Alignment(horizontal='center')
        for i, sub in enumerate(('Unid.', 'P.U.', 'Total')):
            _celda(hoja, fila + 1, col + i, sub, negrita=True, relleno=AZUL_CLARO)
        col += 3
    hoja.merge_cells(start_row=fila, start_column=col, end_row=fila, end_column=col + 2)
    _celda(hoja, fila, col, 'Comparación: promedio', negrita=True, relleno=AMARILLO)
    for i, sub in enumerate(('P.U. promedio', 'Costo de venta', 'Diferencia')):
        _celda(hoja, fila + 1, col + i, sub, negrita=True, relleno=AMARILLO)
    col += 3
    hoja.merge_cells(start_row=fila, start_column=col, end_row=fila, end_column=col + len(detalle) - 1)
    _celda(hoja, fila, col, 'Detalle de salidas según Kardex (S/)', negrita=True, relleno=VERDE)
    for i, k in enumerate(detalle):
        _celda(hoja, fila + 1, col + i, ETIQUETAS_DESGLOSE[k], negrita=True, relleno=VERDE)
    ultima_col = col + len(detalle) - 1
    fila += 2

    for p in reporte['productos']:
        _celda(hoja, fila, 1, p['producto']['codigo'])
        _celda(hoja, fila, 2, p['producto']['descripcion'])
        _celda(hoja, fila, 3, p['producto']['unidad'])
        col = 4
        for _, clave in GRUPOS:
            bloque = p[clave]
            _celda(hoja, fila, col, _num(bloque['cantidad']), FMT_CANT)
            _celda(hoja, fila, col + 1, _num(bloque['costo_unitario']), FMT_CANT)
            _celda(hoja, fila, col + 2, _num(bloque['valor']), FMT_MONTO, negrita=clave == 'costo_venta')
            col += 3
        _celda(hoja, fila, col, _num(p['comparacion']['costo_unitario']), FMT_CANT)
        _celda(hoja, fila, col + 1, _num(p['comparacion']['costo_venta']['valor']), FMT_MONTO)
        _celda(hoja, fila, col + 2, _num(p['diferencia_metodo']), FMT_MONTO)
        col += 3
        for i, k in enumerate(detalle):
            bloque = p['desglose'][k] if k in CLAVES_VENTA else p['conciliacion'][k]
            _celda(hoja, fila, col + i, _num(bloque['valor']), FMT_MONTO)
        fila += 1

    hoja.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=3)
    _celda(hoja, fila, 1, 'TOTAL EMPRESA', negrita=True, relleno=AZUL_CLARO)
    col = 4
    for _, clave in GRUPOS:
        _celda(hoja, fila, col, None, relleno=AZUL_CLARO)
        _celda(hoja, fila, col + 1, None, relleno=AZUL_CLARO)
        _celda(hoja, fila, col + 2, _num(t[clave]['valor']), FMT_MONTO, negrita=True, relleno=AZUL_CLARO)
        col += 3
    _celda(hoja, fila, col, None, relleno=AMARILLO)
    _celda(hoja, fila, col + 1, _num(t['comparacion']['costo_venta']['valor']), FMT_MONTO, negrita=True, relleno=AMARILLO)
    _celda(hoja, fila, col + 2, _num(t['diferencia_metodo']), FMT_MONTO, negrita=True, relleno=AMARILLO)
    col += 3
    for i, k in enumerate(detalle):
        valor = t['desglose'][k] if k in CLAVES_VENTA else t['conciliacion'][k]
        _celda(hoja, fila, col + i, _num(valor), FMT_MONTO, negrita=True, relleno=AZUL_CLARO)

    anchos = {1: 40, 2: 40, 3: 8}
    for c in range(1, ultima_col + 1):
        hoja.column_dimensions[get_column_letter(c)].width = anchos.get(c, 15)
    hoja.page_setup.orientation = 'landscape'
    hoja.sheet_properties.pageSetUpPr.fitToPage = True
    hoja.page_setup.fitToWidth = 1
    hoja.page_setup.fitToHeight = 0
