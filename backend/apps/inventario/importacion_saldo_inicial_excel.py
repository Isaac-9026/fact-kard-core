import io
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.auditoria.services import registrar_auditoria
from apps.empresas.models import Periodo
from apps.inventario.models import Almacen, Producto, SaldoInicial
from apps.inventario.services import confirmar_saldo_inicial
from apps.reportes.excel_seguro import neutralizar_formulas

# Paleta visual corporativa coherente con el sistema
AZUL_CABECERA = '17365D'
AZUL_CLARO = 'D9EAF7'
GRIS_BORDE = 'D1D5DB'
VERDE_SUAVE = 'E2F0D9'

BORDER_THIN = Border(*(Side(style='thin', color=GRIS_BORDE),) * 4)

Q8 = Decimal('0.00000001')
Q6 = Decimal('0.000001')


def generar_plantilla_excel_saldos_iniciales(empresa_id: int) -> io.BytesIO:
    """
    Genera en memoria un archivo Excel (.xlsx) con:
      - Hoja 1 ('Saldos_Iniciales'): columnas requeridas y filas de ejemplo seguro.
      - Hoja 2 ('Catalogo_Productos_Activos'): catálogo de referencia de productos de la empresa.
    """
    wb = Workbook()

    # --- HOJA 1: SALDOS INICIALES ---
    ws_saldos = wb.active
    ws_saldos.title = 'Saldos_Iniciales'

    encabezados = [
        'CODIGO_INTERNO',
        'DESCRIPCION_REFERENCIAL',
        'CANTIDAD',
        'COSTO_UNITARIO_PEN',
        'VALOR_TOTAL_PEN',
    ]
    ws_saldos.append(encabezados)

    header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color=AZUL_CABECERA, end_color=AZUL_CABECERA, fill_type='solid')
    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for col_idx in range(1, len(encabezados) + 1):
        cell = ws_saldos.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = BORDER_THIN
    ws_saldos.row_dimensions[1].height = 28

    # Filas de ejemplo claras y neutralizadas
    ejemplos = [
        ['PROD-0001', 'ARROZ EXTRA COSTAL 50KG', 100.0, 18.50, 1850.00],
        ['PROD-0002', 'ACEITE VEGETAL 1 LITRO', 50.0, 8.20, 410.00],
        [
            '(Obligatorio: Código activo)',
            '(Opcional: Solo referencia visual)',
            '(Obligatorio: Cantidad > 0)',
            '(Opcional si indica Valor Total)',
            '(Opcional si indica Costo Unitario)',
        ],
    ]
    for row_data in ejemplos:
        ws_saldos.append(row_data)

    help_font = Font(name='Calibri', size=9, italic=True, color='6B7280')
    for col_idx in range(1, len(encabezados) + 1):
        ws_saldos.cell(row=4, column=col_idx).font = help_font

    # Autoajuste de columnas
    for col in ws_saldos.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_saldos.column_dimensions[col_letter].width = max(max_len + 4, 18)
    ws_saldos.column_dimensions['B'].width = 36

    # --- HOJA 2: CATÁLOGO DE PRODUCTOS ACTIVOS (REFERENCIA) ---
    ws_cat = wb.create_sheet(title='Catalogo_Productos_Activos')

    cat_header_fill = PatternFill(start_color=AZUL_CLARO, end_color=AZUL_CLARO, fill_type='solid')
    cat_header_font = Font(name='Calibri', size=10, bold=True, color='1E3A8A')

    ws_cat.merge_cells('A1:D1')
    ws_cat['A1'] = 'CATÁLOGO DE PRODUCTOS ACTIVOS DE LA EMPRESA (COPIE EL CÓDIGO INTERNO)'
    ws_cat['A1'].font = cat_header_font
    ws_cat['A1'].fill = cat_header_fill
    ws_cat['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws_cat.row_dimensions[1].height = 24

    ws_cat['A2'] = 'CÓDIGO INTERNO'
    ws_cat['B2'] = 'DESCRIPCIÓN'
    ws_cat['C2'] = 'TIPO EXISTENCIA (TABLA 5)'
    ws_cat['D2'] = 'UNIDAD BASE (TABLA 6)'

    for c in ['A2', 'B2', 'C2', 'D2']:
        ws_cat[c].font = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
        ws_cat[c].fill = PatternFill(start_color=AZUL_CABECERA, end_color=AZUL_CABECERA, fill_type='solid')
        ws_cat[c].alignment = Alignment(horizontal='center', vertical='center')
        ws_cat[c].border = BORDER_THIN
    ws_cat.row_dimensions[2].height = 22

    productos = (
        Producto.objects.filter(empresa_id=empresa_id, estado='ACTIVO')
        .select_related('tipo_existencia_codigo')
        .prefetch_related('unidades__unidad_codigo')
        .order_by('codigo_interno')
    )

    fila_idx = 3
    for prod in productos:
        unidad_base = next((u.unidad_codigo_id for u in prod.unidades.all() if u.es_base), 'NIU')
        tipo_str = f"{prod.tipo_existencia_codigo_id} - {prod.tipo_existencia_codigo.descripcion}" if prod.tipo_existencia_codigo else ''
        ws_cat.append([
            prod.codigo_interno,
            prod.descripcion,
            tipo_str,
            unidad_base,
        ])
        for c_idx in range(1, 5):
            cell = ws_cat.cell(row=fila_idx, column=c_idx)
            cell.border = BORDER_THIN
            cell.font = Font(name='Calibri', size=10)
        fila_idx += 1

    if fila_idx == 3:
        ws_cat.append(['(Sin productos activos registrados)', '', '', ''])
        fila_idx += 1

    for col in ws_cat.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_cat.column_dimensions[col_letter].width = max(max_len + 4, 18)
    ws_cat.column_dimensions['B'].width = 40

    neutralizar_formulas(wb)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def _normalizar_header(val) -> str:
    if val is None:
        return ''
    s = str(val).strip().upper()
    return re.sub(r'[^A-Z0-9_]', '_', s)


def procesar_importacion_excel_saldos_iniciales(
    *,
    empresa_id: int,
    periodo_id: int,
    almacen_id: int,
    archivo,
    modo: str = 'PREVISUALIZAR',
    auto_confirmar: bool = True,
    usuario,
) -> dict:
    """
    Procesa un archivo Excel (.xlsx) para importar saldos iniciales (Operación 16 SUNAT).
    Soporta modo='PREVISUALIZAR' (diagnóstico sin escribir) y modo='CONFIRMAR' (escritura atómica).
    """
    # 1. Validaciones estrictas de Cabecera
    periodo = Periodo.objects.filter(empresa_id=empresa_id, pk=periodo_id).first()
    if not periodo:
        raise ValidationError({'periodo': 'El período seleccionado no existe en la empresa.'})
    if periodo.estado != 'ABIERTO':
        raise ValidationError({'periodo': 'El período seleccionado debe estar en estado ABIERTO.'})

    almacen = Almacen.objects.filter(empresa_id=empresa_id, pk=almacen_id, activo=True).first()
    if not almacen:
        raise ValidationError({'almacen': 'El almacén seleccionado no existe en la empresa o no está activo.'})

    # 2. Carga del libro Excel
    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as exc:
        raise ValidationError({'archivo': f'No se pudo leer el archivo Excel: {exc}'})

    ws = wb['Saldos_Iniciales'] if 'Saldos_Iniciales' in wb.sheetnames else wb.active
    filas_iter = list(ws.iter_rows(values_only=True))
    if not filas_iter or len(filas_iter) < 2:
        raise ValidationError({'archivo': 'El archivo Excel no contiene filas de datos.'})

    # 3. Detección dinámica de columnas
    cabeceras_raw = filas_iter[0]
    idx_codigo = None
    idx_desc = None
    idx_cantidad = None
    idx_costo = None
    idx_valor = None

    for idx, val in enumerate(cabeceras_raw):
        norm = _normalizar_header(val)
        if norm in ('CODIGO_INTERNO', 'CODIGO', 'COD_INTERNO', 'COD', 'SKU', 'COD_PRODUCTO'):
            idx_codigo = idx
        elif norm in ('DESCRIPCION_REFERENCIAL', 'DESCRIPCION', 'NOMBRE', 'PRODUCTO', 'DESCRIPCION_PRODUCTO'):
            idx_desc = idx
        elif norm in ('CANTIDAD', 'CANT', 'STOCK', 'STOCK_INICIAL', 'CANTIDAD_INICIAL'):
            idx_cantidad = idx
        elif norm in ('COSTO_UNITARIO_PEN', 'COSTO_UNITARIO', 'COSTO_PEN', 'COSTO', 'CPP_INICIAL', 'CPP'):
            idx_costo = idx
        elif norm in ('VALOR_TOTAL_PEN', 'VALOR_TOTAL', 'VALOR_PEN', 'TOTAL_PEN', 'VALOR'):
            idx_valor = idx

    if idx_codigo is None:
        raise ValidationError({'archivo': "El archivo Excel debe contener la columna 'CODIGO_INTERNO'."})
    if idx_cantidad is None:
        raise ValidationError({'archivo': "El archivo Excel debe contener la columna 'CANTIDAD'."})
    if idx_costo is None and idx_valor is None:
        raise ValidationError({'archivo': "El archivo Excel debe contener al menos una columna de importe: 'COSTO_UNITARIO_PEN' o 'VALOR_TOTAL_PEN'."})

    # 4. Catálogos en memoria
    productos_dict = {
        p.codigo_interno.strip().upper(): p
        for p in Producto.objects.filter(empresa_id=empresa_id, estado='ACTIVO')
    }
    saldos_existentes = {
        si.producto_id: si
        for si in SaldoInicial.objects.filter(
            empresa_id=empresa_id,
            periodo_id=periodo_id,
            almacen_id=almacen_id,
        )
    }

    filas_diagnostico = []
    codigos_vistos = set()

    # 5. Procesamiento fila por fila
    for row_num, row in enumerate(filas_iter[1:], start=2):
        if not any(row):
            continue

        raw_codigo = str(row[idx_codigo] or '').strip().upper() if idx_codigo is not None and row[idx_codigo] is not None else ''
        if raw_codigo.startswith('(OBLIGATORIO') or raw_codigo.startswith('(COMPLETE') or raw_codigo.startswith('('):
            continue

        raw_desc = str(row[idx_desc] or '').strip() if idx_desc is not None and row[idx_desc] is not None else ''
        raw_cant = row[idx_cantidad] if idx_cantidad is not None else None
        raw_costo = row[idx_costo] if idx_costo is not None else None
        raw_valor = row[idx_valor] if idx_valor is not None else None

        errores_fila = []

        # A. Validación de Código de Producto
        if not raw_codigo:
            errores_fila.append('El código interno de producto es obligatorio.')
        elif raw_codigo in codigos_vistos:
            errores_fila.append(f"Código '{raw_codigo}' duplicado en el mismo archivo Excel.")
        else:
            codigos_vistos.add(raw_codigo)

        prod = productos_dict.get(raw_codigo)
        if raw_codigo and not prod:
            errores_fila.append(f"El producto con código '{raw_codigo}' no existe en el catálogo activo de la empresa.")

        # B. Validación de Cantidad Física
        cant_dec = None
        if raw_cant in (None, ''):
            errores_fila.append('La cantidad es obligatoria.')
        else:
            try:
                cant_str = str(raw_cant).replace(',', '').strip()
                cant_dec = Decimal(cant_str)
                if cant_dec <= Decimal('0'):
                    errores_fila.append('La cantidad física debe ser mayor a cero (> 0).')
            except (InvalidOperation, TypeError, ValueError):
                errores_fila.append(f"Cantidad '{raw_cant}' no es un número decimal válido.")

        # C. Resolución de Costo Unitario y Valor Total PEN
        costo_dec = None
        valor_dec = None
        cpp_final = None
        valor_final = None

        if raw_costo not in (None, ''):
            try:
                c_str = str(raw_costo).replace(',', '').strip()
                costo_dec = Decimal(c_str)
                if costo_dec < Decimal('0'):
                    errores_fila.append('El costo unitario no puede ser negativo.')
            except (InvalidOperation, TypeError, ValueError):
                errores_fila.append(f"Costo unitario '{raw_costo}' no es un número válido.")

        if raw_valor not in (None, ''):
            try:
                v_str = str(raw_valor).replace(',', '').strip()
                valor_dec = Decimal(v_str)
                if valor_dec < Decimal('0'):
                    errores_fila.append('El valor total PEN no puede ser negativo.')
            except (InvalidOperation, TypeError, ValueError):
                errores_fila.append(f"Valor total '{raw_valor}' no es un número válido.")

        if cant_dec is not None and cant_dec > Decimal('0'):
            if costo_dec is not None and valor_dec is not None:
                # Ambos indicados: comprobar consistencia (tolerancia de 5 centavos)
                calculado = (cant_dec * costo_dec).quantize(Q8, rounding=ROUND_HALF_UP)
                if abs(calculado - valor_dec) > Decimal('0.05'):
                    errores_fila.append(
                        f"Incoherencia: Cantidad ({cant_dec}) × Costo Unitario ({costo_dec}) = {calculado} "
                        f"no coincide con Valor Total PEN ({valor_dec})."
                    )
                else:
                    valor_final = valor_dec.quantize(Q8, rounding=ROUND_HALF_UP)
                    cpp_final = (valor_final / cant_dec).quantize(Q6, rounding=ROUND_HALF_UP)
            elif valor_dec is not None:
                valor_final = valor_dec.quantize(Q8, rounding=ROUND_HALF_UP)
                cpp_final = (valor_final / cant_dec).quantize(Q6, rounding=ROUND_HALF_UP)
            elif costo_dec is not None:
                cpp_final = costo_dec.quantize(Q6, rounding=ROUND_HALF_UP)
                valor_final = (cant_dec * costo_dec).quantize(Q8, rounding=ROUND_HALF_UP)
            else:
                errores_fila.append('Debe indicar al menos COSTO_UNITARIO_PEN o VALOR_TOTAL_PEN.')
        elif costo_dec is None and valor_dec is None:
            errores_fila.append('Debe indicar al menos COSTO_UNITARIO_PEN o VALOR_TOTAL_PEN.')

        # D. Verificación contra saldos existentes en la BD
        saldo_existente = saldos_existentes.get(prod.id) if prod else None
        if errores_fila:
            estado_fila = 'ERROR'
            observacion = '; '.join(errores_fila)
        else:
            if saldo_existente:
                if saldo_existente.estado == 'CONFIRMADO':
                    estado_fila = 'ERROR'
                    observacion = 'Ya existe un Saldo Inicial CONFIRMADO para este producto en el período y almacén seleccionados.'
                else:
                    estado_fila = 'ACTUALIZAR'
                    observacion = 'Actualizará el saldo inicial borrador existente.'
            else:
                estado_fila = 'NUEVO'
                observacion = 'Listo para registrar como nuevo saldo inicial.'

        filas_diagnostico.append({
            'numero_fila': row_num,
            'codigo_interno': raw_codigo,
            'descripcion_producto': prod.descripcion if prod else raw_desc,
            'cantidad': str(cant_dec.quantize(Q8)) if cant_dec is not None else '',
            'cpp_inicial': str(cpp_final) if cpp_final is not None else '',
            'valor_pen': str(valor_final) if valor_final is not None else '',
            'estado_fila': estado_fila,
            'observacion': observacion,
            'producto_id': prod.id if prod else None,
            'saldo_existente_id': saldo_existente.id if saldo_existente else None,
        })

    # Resumen
    total_filas = len(filas_diagnostico)
    count_nuevos = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'NUEVO')
    count_actualizables = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'ACTUALIZAR')
    count_errores = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'ERROR')
    count_validas = count_nuevos + count_actualizables

    if modo == 'PREVISUALIZAR':
        return {
            'modo': 'PREVISUALIZAR',
            'periodo_id': periodo_id,
            'periodo_codigo': f"{periodo.anio}-{periodo.mes:02d}",
            'almacen_id': almacen_id,
            'almacen_nombre': almacen.nombre,
            'resumen': {
                'total_filas': total_filas,
                'validas': count_validas,
                'nuevos': count_nuevos,
                'actualizables': count_actualizables,
                'con_error': count_errores,
            },
            'filas': filas_diagnostico,
        }

    # Modo CONFIRMAR: Ejecución atómica en base de datos
    creados = 0
    actualizados = 0
    confirmados_kardex = 0
    omitidos_por_error = count_errores

    with transaction.atomic():
        for fila in filas_diagnostico:
            if fila['estado_fila'] not in ('NUEVO', 'ACTUALIZAR'):
                continue

            cant = Decimal(fila['cantidad'])
            val_pen = Decimal(fila['valor_pen'])
            cpp_ini = Decimal(fila['cpp_inicial'])

            if fila['estado_fila'] == 'NUEVO':
                saldo = SaldoInicial.objects.create(
                    empresa_id=empresa_id,
                    periodo_id=periodo_id,
                    almacen_id=almacen_id,
                    producto_id=fila['producto_id'],
                    cantidad=cant,
                    valor_pen=val_pen,
                    cpp_inicial=cpp_ini,
                    estado='BORRADOR',
                    creado_por=usuario,
                )
                creados += 1
            else:
                saldo = SaldoInicial.objects.select_for_update().get(
                    pk=fila['saldo_existente_id'],
                    empresa_id=empresa_id,
                )
                saldo.cantidad = cant
                saldo.valor_pen = val_pen
                saldo.cpp_inicial = cpp_ini
                saldo.save(update_fields=['cantidad', 'valor_pen', 'cpp_inicial'])
                actualizados += 1

            if auto_confirmar:
                confirmar_saldo_inicial(
                    saldo_id=saldo.id,
                    empresa_id=empresa_id,
                    usuario=usuario,
                )
                confirmados_kardex += 1

        registrar_auditoria(
            empresa_id=empresa_id,
            usuario_id=usuario.id,
            accion='IMPORTAR_SALDOS_INICIALES_EXCEL',
            entidad='SALDO_INICIAL',
            registro_id=almacen_id,
            valor_anterior=None,
            valor_nuevo={
                'periodo_id': periodo_id,
                'almacen_id': almacen_id,
                'creados': creados,
                'actualizados': actualizados,
                'confirmados_kardex': confirmados_kardex,
                'auto_confirmar': auto_confirmar,
            },
            motivo=f'Importación masiva de saldos iniciales vía Excel ({creados + actualizados} procesados).',
        )

    return {
        'modo': 'CONFIRMAR',
        'periodo_id': periodo_id,
        'periodo_codigo': f"{periodo.anio}-{periodo.mes:02d}",
        'almacen_id': almacen_id,
        'almacen_nombre': almacen.nombre,
        'resumen': {
            'total_filas': total_filas,
            'creados': creados,
            'actualizados': actualizados,
            'confirmados_kardex': confirmados_kardex,
            'omitidos_por_error': omitidos_por_error,
        },
        'filas': filas_diagnostico,
    }
