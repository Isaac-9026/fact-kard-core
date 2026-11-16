import io
import re
from decimal import Decimal, InvalidOperation
from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.catalogos.models import TipoExistencia, UnidadMedida
from apps.documentos.afectacion_igv import AFECTACIONES
from apps.inventario.alta_rapida import autogenerar_codigo_producto
from apps.inventario.models import Producto, ProductoUnidad
from apps.reportes.excel_seguro import neutralizar_formulas

# Paleta visual corporativa coherente con Formato 13.1
AZUL_CABECERA = '17365D'
AZUL_CLARO = 'D9EAF7'
GRIS_BORDE = 'D1D5DB'
VERDE_SUAVE = 'E2F0D9'

BORDER_THIN = Border(*(Side(style='thin', color=GRIS_BORDE),) * 4)

SINONIMOS_UNIDAD = {
    'UND': 'NIU', 'UNIDAD': 'NIU', 'UNIDADES': 'NIU', 'NIU': 'NIU', 'PZA': 'NIU', 'PIEZA': 'NIU',
    'KG': 'KGM', 'KGM': 'KGM', 'KILO': 'KGM', 'KILOS': 'KGM', 'KILOGRAMO': 'KGM', 'KILOGRAMOS': 'KGM',
    'LT': 'LTR', 'LTR': 'LTR', 'LITRO': 'LTR', 'LITROS': 'LTR',
    'BX': 'BX', 'CAJA': 'BX', 'CAJAS': 'BX',
    'MTR': 'MTR', 'METRO': 'MTR', 'METROS': 'MTR',
    'GLI': 'GLI', 'GAL': 'GLI', 'GALON': 'GLI', 'GALONES': 'GLI',
    'SET': 'SET', 'JGO': 'SET', 'JUEGO': 'SET',
    'DZN': 'DZN', 'DOC': 'DZN', 'DOCENA': 'DZN', 'DOCENAS': 'DZN',
    'BLL': 'BLL', 'PQ': 'BLL', 'PAQUETE': 'BLL', 'PAQUETES': 'BLL',
    'SCO': 'SA', 'SA': 'SA', 'SACO': 'SA', 'SACOS': 'SA', 'BG': 'BG', 'BOLSA': 'BG',
}

SINONIMOS_TIPO_EXISTENCIA = {
    '01': '01', '1': '01', 'MERCADERIA': '01', 'MERCADERIAS': '01', 'MERCADERÍA': '01', 'MERCADERÍAS': '01',
    '02': '02', '2': '02', 'MATERIA PRIMA': '02', 'MATERIAS PRIMAS': '02',
    '03': '03', '3': '03', 'MATERIAL AUXILIAR': '03', 'SUMINISTROS': '03',
    '04': '04', '4': '04', 'ENVASES': '04', 'EMBALAJES': '04',
    '05': '05', '5': '05', 'SUBPRODUCTO': '05', 'DESECHO': '05',
}

SINONIMOS_AFECTACION = {
    '10': 'GRAVADO', '18%': 'GRAVADO', 'GRAVADO': 'GRAVADO', 'GRAVADA': 'GRAVADO', 'IGV': 'GRAVADO',
    '20': 'EXONERADO', 'EXONERADO': 'EXONERADO', 'EXONERADA': 'EXONERADO', '0%': 'EXONERADO',
    '30': 'INAFECTO', '40': 'INAFECTO', 'INAFECTO': 'INAFECTO', 'INAFECTA': 'INAFECTO',
    'EXPORTACION': 'EXPORTACION', 'EXPORTACIÓN': 'EXPORTACION',
    'GRATUITO': 'GRATUITO', 'GRATUITA': 'GRATUITO', 'BONIFICACION': 'GRATUITO',
}


def generar_plantilla_excel_productos() -> io.BytesIO:
    """
    Genera en memoria un archivo Excel (.xlsx) con:
      - Hoja 1 ('Productos'): cabeceras oficiales y filas de ejemplo.
      - Hoja 2 ('Catalogos_SUNAT'): tablas oficiales Tabla 5, Tabla 6 y Afectaciones.
    """
    wb = Workbook()

    # --- HOJA 1: PRODUCTOS ---
    ws_prod = wb.active
    ws_prod.title = 'Productos'

    encabezados = [
        'CODIGO_INTERNO',
        'DESCRIPCION',
        'TIPO_EXISTENCIA_CODIGO',
        'UNIDAD_BASE_CODIGO',
        'AFECTACION_IGV',
        'PRECIO_VENTA_SUGERIDO',
    ]
    ws_prod.append(encabezados)

    # Estilos de encabezado
    header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color=AZUL_CABECERA, end_color=AZUL_CABECERA, fill_type='solid')
    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for col_idx in range(1, len(encabezados) + 1):
        cell = ws_prod.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = BORDER_THIN
    ws_prod.row_dimensions[1].height = 28

    # Filas de ejemplo claras
    ejemplos = [
        ['PROD-0001', 'ARROZ EXTRA COSTAL 50KG', '01', 'KGM', 'GRAVADO', 185.50],
        ['', 'ACEITE VEGETAL 1 LITRO', '01', 'NIU', 'GRAVADO', 8.20],
        ['', '(Si deja el código vacío, el sistema autogenera PROD-XXXX)', '01=Mercaderías', 'NIU=Unidad, KGM=Kilo', 'GRAVADO / EXONERADO', 'Opcional (>= 0)'],
    ]
    for row_data in ejemplos:
        ws_prod.append(row_data)

    # Estilo fila de ayuda
    help_font = Font(name='Calibri', size=9, italic=True, color='6B7280')
    for col_idx in range(1, len(encabezados) + 1):
        ws_prod.cell(row=4, column=col_idx).font = help_font

    # Autoajuste de columnas
    for col in ws_prod.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_prod.column_dimensions[col_letter].width = max(max_len + 4, 18)
    ws_prod.column_dimensions['B'].width = 38

    # --- HOJA 2: CATÁLOGOS SUNAT ---
    ws_cat = wb.create_sheet(title='Catalogos_SUNAT')

    # Sub-encabezados de catálogos
    cat_header_fill = PatternFill(start_color=AZUL_CLARO, end_color=AZUL_CLARO, fill_type='solid')
    cat_header_font = Font(name='Calibri', size=10, bold=True, color='1E3A8A')

    ws_cat.merge_cells('A1:B1')
    ws_cat['A1'] = 'TABLA 5: TIPOS DE EXISTENCIA (SUNAT)'
    ws_cat['A1'].font = cat_header_font
    ws_cat['A1'].fill = cat_header_fill

    ws_cat.merge_cells('D1:E1')
    ws_cat['D1'] = 'TABLA 6: UNIDADES DE MEDIDA (SUNAT)'
    ws_cat['D1'].font = cat_header_font
    ws_cat['D1'].fill = cat_header_fill

    ws_cat.merge_cells('G1:H1')
    ws_cat['G1'] = 'AFECTACIONES IGV VÁLIDAS'
    ws_cat['G1'].font = cat_header_font
    ws_cat['G1'].fill = cat_header_fill

    ws_cat['A2'], ws_cat['B2'] = 'CÓDIGO', 'DESCRIPCIÓN'
    ws_cat['D2'], ws_cat['E2'] = 'CÓDIGO', 'DESCRIPCIÓN'
    ws_cat['G2'], ws_cat['H2'] = 'VALOR', 'DESCRIPCIÓN'

    for c in ['A2', 'B2', 'D2', 'E2', 'G2', 'H2']:
        ws_cat[c].font = Font(bold=True, size=9)

    # Datos Tabla 5
    tipos = list(TipoExistencia.objects.all().order_by('codigo').values_list('codigo', 'descripcion'))
    for idx, (cod, desc) in enumerate(tipos, start=3):
        ws_cat.cell(row=idx, column=1, value=cod)
        ws_cat.cell(row=idx, column=2, value=desc)

    # Datos Tabla 6
    unidades = list(UnidadMedida.objects.all().order_by('codigo').values_list('codigo', 'descripcion'))
    for idx, (cod, desc) in enumerate(unidades, start=3):
        ws_cat.cell(row=idx, column=4, value=cod)
        ws_cat.cell(row=idx, column=5, value=desc)

    # Datos Afectaciones
    for idx, (val, desc) in enumerate(AFECTACIONES, start=3):
        ws_cat.cell(row=idx, column=7, value=val)
        ws_cat.cell(row=idx, column=8, value=desc)

    for col_letter in ['A', 'B', 'D', 'E', 'G', 'H']:
        ws_cat.column_dimensions[col_letter].width = 24
    ws_cat.column_dimensions['B'].width = 32
    ws_cat.column_dimensions['E'].width = 30

    neutralizar_formulas(wb)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def _normalizar_header(val: str) -> str:
    s = str(val or '').strip().upper()
    return re.sub(r'[\s\-_]+', '_', s)


def procesar_importacion_excel_productos(*, empresa_id: int, archivo, modo: str = 'PREVISUALIZAR', usuario=None) -> dict:
    """
    Lee y valida un archivo Excel con productos.
    Modo 'PREVISUALIZAR': Retorna diagnóstico detallado fila por fila sin modificar BD.
    Modo 'CONFIRMAR': Ejecuta creación y actualización atómica en la base de datos.
    """
    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as exc:
        raise ValueError(f"No se pudo leer el archivo Excel (.xlsx): {str(exc)}")

    # Tomar hoja 'Productos' o la primera disponible
    sheet_name = 'Productos' if 'Productos' in wb.sheetnames else wb.sheetnames[0]
    ws = wb[sheet_name]

    filas_iter = list(ws.iter_rows(values_only=True))
    if not filas_iter or len(filas_iter) < 2:
        return {
            'total_filas': 0,
            'nuevos': 0,
            'actualizables': 0,
            'errores': 0,
            'filas': [],
            'mensaje': 'El archivo Excel no contiene filas de datos.',
        }

    # Mapeo de columnas de cabecera
    cabeceras_raw = filas_iter[0]
    idx_codigo = None
    idx_desc = None
    idx_tipo = None
    idx_unidad = None
    idx_afectacion = None
    idx_precio = None

    for idx, val in enumerate(cabeceras_raw):
        norm = _normalizar_header(val)
        if norm in ('CODIGO_INTERNO', 'CODIGO', 'COD_INTERNO', 'COD'):
            idx_codigo = idx
        elif norm in ('DESCRIPCION', 'NOMBRE', 'PRODUCTO', 'DESCRIPCION_PRODUCTO'):
            idx_desc = idx
        elif norm in ('TIPO_EXISTENCIA_CODIGO', 'TIPO_EXISTENCIA', 'TABLA_5', 'TIPO'):
            idx_tipo = idx
        elif norm in ('UNIDAD_BASE_CODIGO', 'UNIDAD_MEDIDA', 'UNIDAD', 'TABLA_6', 'UNIDAD_BASE'):
            idx_unidad = idx
        elif norm in ('AFECTACION_IGV', 'AFECTACION', 'IGV'):
            idx_afectacion = idx
        elif norm in ('PRECIO_VENTA_SUGERIDO', 'PRECIO_VENTA', 'PRECIO', 'PRECIO_SUGERIDO'):
            idx_precio = idx

    if idx_desc is None:
        raise ValueError("El archivo Excel debe contener al menos una columna 'DESCRIPCION'.")

    # Catálogos existentes en BD
    tipos_validos = set(TipoExistencia.objects.values_list('codigo', flat=True))
    unidades_validas = set(UnidadMedida.objects.values_list('codigo', flat=True))
    productos_existentes = dict(Producto.objects.filter(empresa_id=empresa_id).values_list('codigo_interno', 'id'))

    filas_diagnostico = []
    codigos_vistos_en_archivo = set()

    # Procesar filas a partir de la fila 2 (índice 1)
    for row_num, row in enumerate(filas_iter[1:], start=2):
        # Omitir filas totalmente vacías
        if not any(row):
            continue

        raw_desc = str(row[idx_desc] or '').strip()
        # Omitir fila de notas/instrucciones si empieza con paréntesis
        if raw_desc.startswith('(Si deja') or raw_desc.startswith('(Deje'):
            continue

        raw_codigo = str(row[idx_codigo] or '').strip().upper() if idx_codigo is not None and row[idx_codigo] is not None else ''
        raw_tipo = str(row[idx_tipo] or '').strip().upper() if idx_tipo is not None and row[idx_tipo] is not None else ''
        raw_unidad = str(row[idx_unidad] or '').strip().upper() if idx_unidad is not None and row[idx_unidad] is not None else ''
        raw_afectacion = str(row[idx_afectacion] or '').strip().upper() if idx_afectacion is not None and row[idx_afectacion] is not None else ''
        raw_precio = row[idx_precio] if idx_precio is not None else None

        errores_fila = []

        # 1. Validación de Descripción
        if not raw_desc:
            errores_fila.append('La descripción es obligatoria.')
        descripcion_limpia = raw_desc[:250]

        # 2. Validación de Tipo Existencia (Tabla 5)
        tipo_cod = SINONIMOS_TIPO_EXISTENCIA.get(raw_tipo, raw_tipo or '01')
        if tipo_cod not in tipos_validos:
            errores_fila.append(f"Tipo de existencia '{raw_tipo}' inválido según SUNAT Tabla 5.")

        # 3. Validación de Unidad Base (Tabla 6)
        unidad_cod = SINONIMOS_UNIDAD.get(raw_unidad, raw_unidad or 'NIU')
        if unidad_cod not in unidades_validas:
            errores_fila.append(f"Unidad de medida '{raw_unidad}' inválida según SUNAT Tabla 6.")

        # 4. Validación de Afectación IGV
        afectacion_cod = SINONIMOS_AFECTACION.get(raw_afectacion, raw_afectacion or 'GRAVADO')
        if afectacion_cod not in dict(AFECTACIONES):
            afectacion_cod = 'GRAVADO'

        # 5. Validación de Precio Venta Sugerido
        precio_val = None
        if raw_precio not in (None, ''):
            try:
                precio_val = Decimal(str(raw_precio))
                if precio_val < 0:
                    errores_fila.append('El precio de venta no puede ser negativo.')
            except (InvalidOperation, TypeError, ValueError):
                errores_fila.append(f"Precio '{raw_precio}' no es un número válido.")

        # 6. Validación de Código y Duplicados
        auto_generar = False
        if not raw_codigo:
            auto_generar = True
            codigo_para_mostrar = '(Autogenerar)'
        else:
            codigo_para_mostrar = raw_codigo[:50]
            if codigo_para_mostrar in codigos_vistos_en_archivo:
                errores_fila.append(f"Código '{codigo_para_mostrar}' duplicado en el mismo archivo Excel.")
            else:
                codigos_vistos_en_archivo.add(codigo_para_mostrar)

        # Estado de la fila
        if errores_fila:
            estado_fila = 'ERROR'
            observacion = '; '.join(errores_fila)
        else:
            if not auto_generar and codigo_para_mostrar in productos_existentes:
                estado_fila = 'ACTUALIZAR'
                observacion = 'Producto existente: se actualizarán datos comerciales y descripción.'
            else:
                estado_fila = 'NUEVO'
                observacion = 'Producto nuevo: se registrará en catálogo con unidad base.'

        filas_diagnostico.append({
            'fila': row_num,
            'codigo_interno': codigo_para_mostrar,
            'codigo_real': '' if auto_generar else codigo_para_mostrar,
            'auto_generar': auto_generar,
            'descripcion': descripcion_limpia,
            'tipo_existencia_codigo': tipo_cod,
            'unidad_base_codigo': unidad_cod,
            'afectacion_igv': afectacion_cod,
            'precio_venta_sugerido': str(precio_val) if precio_val is not None else None,
            'estado_fila': estado_fila,
            'observacion': observacion,
        })

    total_filas = len(filas_diagnostico)
    errores_count = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'ERROR')
    actualizables_count = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'ACTUALIZAR')
    nuevos_count = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'NUEVO')

    if modo != 'CONFIRMAR':
        return {
            'total_filas': total_filas,
            'nuevos': nuevos_count,
            'actualizables': actualizables_count,
            'errores': errores_count,
            'filas': filas_diagnostico,
            'mensaje': f'Análisis completado: {nuevos_count} nuevos, {actualizables_count} para actualizar, {errores_count} con error.',
        }

    # --- MODO CONFIRMAR: EJECUCIÓN ATÓMICA ---
    creados = 0
    actualizados = 0

    with transaction.atomic():
        for f in filas_diagnostico:
            if f['estado_fila'] == 'ERROR':
                continue

            precio_dec = Decimal(f['precio_venta_sugerido']) if f['precio_venta_sugerido'] else None

            if f['estado_fila'] == 'NUEVO':
                # Autogenerar si es necesario
                codigo = f['codigo_real']
                if not codigo or f['auto_generar']:
                    codigo = autogenerar_codigo_producto(empresa_id)

                prod = Producto.objects.create(
                    empresa_id=empresa_id,
                    codigo_interno=codigo,
                    descripcion=f['descripcion'],
                    tipo_existencia_codigo_id=f['tipo_existencia_codigo'],
                    estado='ACTIVO',
                    afectacion_igv_defecto=f['afectacion_igv'],
                    precio_venta_sugerido=precio_dec,
                )
                ProductoUnidad.objects.create(
                    producto=prod,
                    unidad_codigo_id=f['unidad_base_codigo'],
                    factor_a_base=Decimal('1.00000000'),
                    es_base=True,
                )
                creados += 1

            elif f['estado_fila'] == 'ACTUALIZAR':
                prod_id = productos_existentes.get(f['codigo_real'])
                if prod_id:
                    Producto.objects.filter(pk=prod_id, empresa_id=empresa_id).update(
                        descripcion=f['descripcion'],
                        tipo_existencia_codigo_id=f['tipo_existencia_codigo'],
                        afectacion_igv_defecto=f['afectacion_igv'],
                        precio_venta_sugerido=precio_dec,
                    )
                    actualizados += 1

    return {
        'total_filas': total_filas,
        'creados': creados,
        'actualizados': actualizados,
        'omitidos_por_error': errores_count,
        'total_procesados': creados + actualizados,
        'mensaje': f'Importación completada: {creados} productos creados, {actualizados} actualizados, {errores_count} omitidos por error.',
    }

