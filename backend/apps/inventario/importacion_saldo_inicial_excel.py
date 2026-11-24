import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from apps.auditoria.services import registrar_auditoria
from apps.empresas.models import Periodo
from apps.inventario.models import Almacen, Producto, SaldoInicial
from apps.inventario.services import confirmar_saldo_inicial
from apps.reportes.excel_seguro import neutralizar_formulas

AZUL_CABECERA = '17365D'
AZUL_CLARO = 'D9EAF7'
GRIS_BORDE = 'D1D5DB'

BORDER_THIN = Border(*(Side(style='thin', color=GRIS_BORDE),) * 4)
BORDE_MODELO = Border(*(Side(style='thin'),) * 4)

Q8 = Decimal('0.00000001')
Q6 = Decimal('0.000001')
CERO = Decimal('0')
TOLERANCIA_BASE = Decimal('0.05')
RESIDUO_SALDO_CERO = Decimal('0.01')   # un saldo de cantidad 0 puede arrastrar céntimos de redondeo

HOJA_SALDOS = 'Saldo_inicial'
TIPO_OPERACION_MODELO = 'Saldo Anterior'


def generar_plantilla_excel_saldos_iniciales(empresa_id: int) -> io.BytesIO:
    """
    Plantilla con el mismo formato del resumen de saldos iniciales del cliente:
    Código | FECHA | Tipo de Operación | SALDO FINAL (Cantidad, Costo Unitario, Costo Total),
    con encabezado de dos filas. Trae una fila por producto activo para completar solo los importes.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = HOJA_SALDOS

    fuente = Font(name='Aptos Narrow', size=12)
    fuente_titulo = Font(name='Aptos Narrow', size=12, bold=True)
    centro = Alignment(horizontal='center', vertical='center', wrap_text=True)

    ws.append(['Código', 'FECHA', 'Tipo de Operación', 'SALDO FINAL', None, None])
    ws.append([None, None, None, 'Cantidad', 'Costo Unitario', 'Costo Total'])
    for rango in ('A1:A2', 'B1:B2', 'C1:C2', 'D1:F1'):
        ws.merge_cells(rango)
    for fila in ws.iter_rows(min_row=1, max_row=2, max_col=6):
        for celda in fila:
            celda.font = fuente_titulo
            celda.alignment = centro
            celda.border = BORDE_MODELO
    ws.row_dimensions[2].height = 31.5

    productos = list(
        Producto.objects.filter(empresa_id=empresa_id, estado='ACTIVO')
        .select_related('tipo_existencia_codigo')
        .prefetch_related('unidades__unidad_codigo')
        .order_by('codigo_interno')
    )
    for prod in productos:
        ws.append([prod.codigo_interno, None, TIPO_OPERACION_MODELO, None, None, None])
        n = ws.max_row
        for col in range(1, 7):
            celda = ws.cell(n, col)
            celda.font = fuente
            celda.border = BORDE_MODELO
        for col in (1, 2, 3):
            ws.cell(n, col).alignment = Alignment(horizontal='center')
        ws.cell(n, 1).number_format = '@'
        ws.cell(n, 2).number_format = 'mm-dd-yy'
        ws.cell(n, 4).number_format = '#,##0.000'
        ws.cell(n, 5).number_format = '#,##0.0000'
        ws.cell(n, 6).number_format = '#,##0.000'

    for col, ancho in zip('ABCDEF', (12, 12, 18, 13, 15, 15)):
        ws.column_dimensions[col].width = ancho

    # Hoja de referencia: descripción, tipo y unidad de cada código.
    ws_cat = wb.create_sheet(title='Catalogo_Productos_Activos')
    ws_cat.merge_cells('A1:D1')
    ws_cat['A1'] = 'CATÁLOGO DE PRODUCTOS ACTIVOS DE LA EMPRESA (REFERENCIA)'
    ws_cat['A1'].font = Font(name='Calibri', size=10, bold=True, color='1E3A8A')
    ws_cat['A1'].fill = PatternFill(start_color=AZUL_CLARO, end_color=AZUL_CLARO, fill_type='solid')
    ws_cat['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws_cat.append(['CÓDIGO INTERNO', 'DESCRIPCIÓN', 'TIPO EXISTENCIA (TABLA 5)', 'UNIDAD BASE (TABLA 6)'])
    for celda in ws_cat[2]:
        celda.font = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
        celda.fill = PatternFill(start_color=AZUL_CABECERA, end_color=AZUL_CABECERA, fill_type='solid')
        celda.alignment = Alignment(horizontal='center', vertical='center')
        celda.border = BORDER_THIN
    for prod in productos:
        unidad_base = next((u.unidad_codigo_id for u in prod.unidades.all() if u.es_base), 'NIU')
        tipo_str = f"{prod.tipo_existencia_codigo_id} - {prod.tipo_existencia_codigo.descripcion}" if prod.tipo_existencia_codigo else ''
        ws_cat.append([prod.codigo_interno, prod.descripcion, tipo_str, unidad_base])
        for celda in ws_cat[ws_cat.max_row]:
            celda.border = BORDER_THIN
            celda.font = Font(name='Calibri', size=10)
    if not productos:
        ws_cat.append(['(Sin productos activos registrados)', '', '', ''])
    for col, ancho in zip('ABCD', (18, 44, 30, 22)):
        ws_cat.column_dimensions[col].width = ancho

    neutralizar_formulas(wb)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def _normalizar_header(val) -> str:
    if val is None:
        return ''
    s = unicodedata.normalize('NFKD', str(val)).encode('ascii', 'ignore').decode()
    s = s.strip().upper()
    return re.sub(r'[^A-Z0-9]+', '_', s).strip('_')


ALIAS_CODIGO = ('CODIGO_INTERNO', 'CODIGO', 'COD_INTERNO', 'COD', 'SKU', 'COD_PRODUCTO')
ALIAS_DESCRIPCION = ('DESCRIPCION_REFERENCIAL', 'DESCRIPCION', 'NOMBRE', 'PRODUCTO', 'DESCRIPCION_PRODUCTO')
ALIAS_CANTIDAD = ('CANTIDAD', 'CANT', 'STOCK', 'STOCK_INICIAL', 'CANTIDAD_INICIAL')
ALIAS_COSTO = ('COSTO_UNITARIO_PEN', 'COSTO_UNITARIO', 'COSTO_PEN', 'COSTO', 'CPP_INICIAL', 'CPP')
ALIAS_VALOR = ('VALOR_TOTAL_PEN', 'VALOR_TOTAL', 'VALOR_PEN', 'TOTAL_PEN', 'VALOR', 'COSTO_TOTAL')


def _detectar_columnas(filas):
    """
    Devuelve (indices, fila_inicio_datos). Acepta el encabezado de una fila (formato anterior) o el
    de dos filas del resumen del cliente, donde Cantidad/Costo Unitario/Costo Total van bajo SALDO FINAL.
    """
    indices = {}
    alias = (('codigo', ALIAS_CODIGO), ('descripcion', ALIAS_DESCRIPCION), ('cantidad', ALIAS_CANTIDAD),
             ('costo', ALIAS_COSTO), ('valor', ALIAS_VALOR))
    for num_fila in (0, 1):
        if num_fila >= len(filas):
            break
        for idx, val in enumerate(filas[num_fila]):
            norm = _normalizar_header(val)
            for clave, nombres in alias:
                if norm in nombres and clave not in indices:
                    indices[clave] = idx
    usa_dos_filas = len(filas) > 1 and any(
        _normalizar_header(v) in ALIAS_CANTIDAD + ALIAS_COSTO + ALIAS_VALOR for v in filas[1]
    )
    return indices, (3 if usa_dos_filas else 2)


def _decimal(valor):
    """Decimal exacto de lo que se ve en la celda; None si está vacía. Lanza ValueError si no es número."""
    if valor in (None, ''):
        return None
    if isinstance(valor, float):
        valor = repr(valor)
    try:
        return Decimal(str(valor).replace(',', '').strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(valor)


def _texto_codigo(valor) -> str:
    if valor is None:
        return ''
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip().upper()


def _tolerancia(cantidad: Decimal, costo: Decimal) -> Decimal:
    """El costo unitario suele venir redondeado: se acepta medio dígito de su último decimal por unidad."""
    decimales = max(-costo.as_tuple().exponent, 0)
    return TOLERANCIA_BASE + abs(cantidad) * Decimal(5) / (Decimal(10) ** (decimales + 1))


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
    Importa saldos iniciales (Operación 16 SUNAT) desde Excel.
    PREVISUALIZAR: diagnóstico sin escribir. CONFIRMAR: todo o nada; no graba si alguna fila tiene error.
    Las filas con cantidad 0 (saldo cero) se omiten.
    """
    periodo = Periodo.objects.filter(empresa_id=empresa_id, pk=periodo_id).first()
    if not periodo:
        raise ValidationError({'periodo': 'El período seleccionado no existe en la empresa.'})
    if periodo.estado != 'ABIERTO':
        raise ValidationError({'periodo': 'El período seleccionado debe estar en estado ABIERTO.'})

    almacen = Almacen.objects.filter(empresa_id=empresa_id, pk=almacen_id, activo=True).first()
    if not almacen:
        raise ValidationError({'almacen': 'El almacén seleccionado no existe en la empresa o no está activo.'})

    try:
        wb = load_workbook(archivo, data_only=True)
    except Exception as exc:
        raise ValidationError({'archivo': f'No se pudo leer el archivo Excel: {exc}'})

    if HOJA_SALDOS in wb.sheetnames:
        ws = wb[HOJA_SALDOS]
    elif 'Saldos_Iniciales' in wb.sheetnames:
        ws = wb['Saldos_Iniciales']
    else:
        ws = wb.worksheets[0]
    filas_iter = list(ws.iter_rows(values_only=True))
    if len(filas_iter) < 2:
        raise ValidationError({'archivo': 'El archivo Excel no contiene filas de datos.'})

    columnas, inicio = _detectar_columnas(filas_iter)
    if 'codigo' not in columnas:
        raise ValidationError({'archivo': "El archivo Excel debe contener la columna 'Código'."})
    if 'cantidad' not in columnas:
        raise ValidationError({'archivo': "El archivo Excel debe contener la columna 'Cantidad'."})
    if 'costo' not in columnas and 'valor' not in columnas:
        raise ValidationError({'archivo': "El archivo Excel debe contener 'Costo Unitario' o 'Costo Total'."})

    def celda(row, clave):
        idx = columnas.get(clave)
        return row[idx] if idx is not None and idx < len(row) else None

    productos_dict = {
        p.codigo_interno.strip().upper(): p
        for p in Producto.objects.filter(empresa_id=empresa_id, estado='ACTIVO')
    }
    saldos_existentes = {
        si.producto_id: si
        for si in SaldoInicial.objects.filter(empresa_id=empresa_id, periodo_id=periodo_id, almacen_id=almacen_id)
    }

    filas_diagnostico = []
    codigos_vistos = set()

    for row_num, row in enumerate(filas_iter[inicio - 1:], start=inicio):
        if not any(v not in (None, '') for v in row):
            continue

        raw_codigo = _texto_codigo(celda(row, 'codigo'))
        if raw_codigo.startswith('('):
            continue
        raw_desc = str(celda(row, 'descripcion') or '').strip()

        errores_fila = []
        valores = {}
        for clave, etiqueta in (('cantidad', 'Cantidad'), ('costo', 'Costo unitario'), ('valor', 'Costo total')):
            try:
                valores[clave] = _decimal(celda(row, clave))
            except ValueError as exc:
                valores[clave] = None
                errores_fila.append(f"{etiqueta} '{exc.args[0]}' no es un número válido.")
        cant_dec, costo_dec, valor_dec = valores['cantidad'], valores['costo'], valores['valor']

        if not raw_codigo:
            errores_fila.append('El código del producto es obligatorio.')
        elif raw_codigo in codigos_vistos:
            errores_fila.append(f"Código '{raw_codigo}' duplicado en el mismo archivo Excel.")
        else:
            codigos_vistos.add(raw_codigo)

        prod = productos_dict.get(raw_codigo)
        if raw_codigo and not prod:
            errores_fila.append(f"El producto con código '{raw_codigo}' no existe en el catálogo activo de la empresa.")

        cpp_final = None
        valor_final = None
        omitir = False

        if cant_dec is None or cant_dec == CERO:
            residuo = abs(valor_dec) if valor_dec is not None else CERO
            if residuo <= RESIDUO_SALDO_CERO:
                omitir = True
            else:
                errores_fila.append(f'Cantidad 0 con un costo total de S/ {valor_dec}: revise la fila.')
        elif cant_dec < CERO:
            errores_fila.append('La cantidad no puede ser negativa.')
        elif costo_dec is not None and costo_dec < CERO:
            errores_fila.append('El costo unitario no puede ser negativo.')
        elif valor_dec is not None and valor_dec < CERO:
            errores_fila.append('El costo total no puede ser negativo.')
        elif costo_dec is None and valor_dec is None:
            errores_fila.append('Debe indicar el Costo Unitario o el Costo Total.')
        else:
            if valor_dec is not None:
                if costo_dec is not None:
                    calculado = cant_dec * costo_dec
                    if abs(calculado - valor_dec) > _tolerancia(cant_dec, costo_dec):
                        errores_fila.append(
                            f'Incoherencia: Cantidad ({cant_dec}) × Costo Unitario ({costo_dec}) = '
                            f'{calculado.quantize(Q8)} no coincide con el Costo Total ({valor_dec}).'
                        )
                valor_final = valor_dec.quantize(Q8, rounding=ROUND_HALF_UP)
                cpp_final = (valor_final / cant_dec).quantize(Q6, rounding=ROUND_HALF_UP)
            else:
                cpp_final = costo_dec.quantize(Q6, rounding=ROUND_HALF_UP)
                valor_final = (cant_dec * costo_dec).quantize(Q8, rounding=ROUND_HALF_UP)

        if omitir:
            # Un saldo cero no se registra: no importa si el código no existe en el sistema.
            errores_fila = [e for e in errores_fila if 'no existe en el catálogo' not in e]

        saldo_existente = saldos_existentes.get(prod.id) if prod else None
        if errores_fila:
            estado_fila = 'ERROR'
            observacion = '; '.join(errores_fila)
        elif omitir:
            estado_fila = 'OMITIDO'
            observacion = 'Saldo cero: no se registra.'
        elif saldo_existente and saldo_existente.estado == 'CONFIRMADO':
            estado_fila = 'ERROR'
            observacion = 'Ya existe un Saldo Inicial CONFIRMADO para este producto en el período y almacén seleccionados.'
        elif saldo_existente:
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
            'cpp_inicial': str(cpp_final) if cpp_final is not None and estado_fila != 'ERROR' else '',
            'valor_pen': str(valor_final) if valor_final is not None and estado_fila != 'ERROR' else '',
            'estado_fila': estado_fila,
            'observacion': observacion,
            'producto_id': prod.id if prod else None,
            'saldo_existente_id': saldo_existente.id if saldo_existente else None,
        })

    total_filas = len(filas_diagnostico)
    count_nuevos = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'NUEVO')
    count_actualizables = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'ACTUALIZAR')
    count_errores = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'ERROR')
    count_omitidos = sum(1 for f in filas_diagnostico if f['estado_fila'] == 'OMITIDO')
    valor_total = sum(
        (Decimal(f['valor_pen']) for f in filas_diagnostico if f['estado_fila'] in ('NUEVO', 'ACTUALIZAR')), CERO,
    )

    if modo == 'PREVISUALIZAR':
        return {
            'modo': 'PREVISUALIZAR',
            'periodo_id': periodo_id,
            'periodo_codigo': f"{periodo.anio}-{periodo.mes:02d}",
            'almacen_id': almacen_id,
            'almacen_nombre': almacen.nombre,
            'resumen': {
                'total_filas': total_filas,
                'validas': count_nuevos + count_actualizables,
                'nuevos': count_nuevos,
                'actualizables': count_actualizables,
                'con_error': count_errores,
                'omitidos': count_omitidos,
                'valor_total_pen': str(valor_total.quantize(Decimal('0.01'))),
            },
            'filas': filas_diagnostico,
        }

    if count_errores:
        raise ValidationError({
            'archivo': f'No se importó nada: el archivo tiene {count_errores} fila(s) con error. Corríjalas y vuelva a previsualizar.',
        })
    if not count_nuevos and not count_actualizables:
        raise ValidationError({'archivo': 'El archivo no tiene saldos para importar.'})

    creados = 0
    actualizados = 0
    confirmados_kardex = 0

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
                confirmar_saldo_inicial(saldo_id=saldo.id, empresa_id=empresa_id, usuario=usuario)
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
                'omitidos': count_omitidos,
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
            'omitidos': count_omitidos,
            'omitidos_por_error': 0,
        },
        'filas': filas_diagnostico,
    }
