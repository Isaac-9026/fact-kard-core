"""
Almacenamiento temporal, paginación y exportación Excel de errores para previsualizaciones
de importación masiva (Paso 4).

Guarda el diagnóstico completo en disco bajo `IMPORTACION_STAGING_DIR/previsualizaciones/`
(evitando saturar los 64 MB de Redis) con aislamiento estricto por `empresa_id` y TTL de 60 min.
"""
import io
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.documentos.importacion_staging import DEFAULT_STAGING_DIR

PREVISUALIZACION_TTL_SEGUNDOS = 3600
PAGE_SIZE_DEFAULT = 100
PAGE_SIZE_MIN = 50
PAGE_SIZE_MAX = 200

_RE_PREV_ID = re.compile(r'^[a-f0-9]{32}$')

FILTROS_PREVISUALIZACION = {
    'todos': 'todos',
    'TODOS': 'todos',
    'nuevos': 'nuevos',
    'NUEVO': 'nuevos',
    'a_completar': 'a_completar',
    'COMPLETAR': 'a_completar',
    'ya_existen': 'ya_existen',
    'YA_EXISTE': 'ya_existen',
    'errores': 'errores',
    'ERROR': 'errores',
    'conflictos': 'conflictos',
    'CONFLICTO': 'conflictos',
    'sin_proveedor': 'sin_proveedor',
    'SIN_PROVEEDOR': 'sin_proveedor',
    'observaciones': 'observaciones',
    'OBSERVADOS': 'observaciones',
}


def _previsualizaciones_dir() -> Path:
    base = getattr(settings, 'IMPORTACION_STAGING_DIR', DEFAULT_STAGING_DIR) or DEFAULT_STAGING_DIR
    root = (Path(base).resolve() / 'previsualizaciones').resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ruta_segura(previsualizacion_id: str) -> Path:
    limpio = (previsualizacion_id or '').strip()
    if not _RE_PREV_ID.match(limpio):
        raise NotFound('Previsualización no encontrada o expirada.')
    root = _previsualizaciones_dir()
    ruta = (root / f'{limpio}.json').resolve()
    if ruta.parent != root or not ruta.is_relative_to(root):
        raise NotFound('Previsualización no encontrada o expirada.')
    return ruta


def _limpiar_expiradas(root: Path, ahora_ts: float) -> None:
    try:
        for archivo in root.glob('*.json'):
            try:
                if archivo.stat().st_mtime + PREVISUALIZACION_TTL_SEGUNDOS < ahora_ts:
                    archivo.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        return


def guardar_previsualizacion(*, empresa_id: int, resultado: dict, ttl: int = PREVISUALIZACION_TTL_SEGUNDOS) -> dict:
    """Persiste el resultado completo en disco con `empresa_id` y TTL, retornando ID y expiración."""
    root = _previsualizaciones_dir()
    ahora = timezone.now()
    ahora_ts = ahora.timestamp()
    _limpiar_expiradas(root, ahora_ts)

    ttl_seg = max(1, int(ttl))
    prev_id = uuid.uuid4().hex
    expira_dt = ahora + timedelta(seconds=ttl_seg)
    destino = (root / f'{prev_id}.json').resolve()
    temporal = (root / f'.{prev_id}.tmp').resolve()

    envoltura = {
        'previsualizacion_id': prev_id,
        'empresa_id': int(empresa_id),
        'creado_en': ahora.isoformat(),
        'expira_en': expira_dt.isoformat(),
        'expira_ts': ahora_ts + ttl_seg,
        'resultado': resultado,
    }
    temporal.write_text(json.dumps(envoltura, ensure_ascii=False), encoding='utf-8')
    temporal.replace(destino)
    return {'previsualizacion_id': prev_id, 'expira_en': envoltura['expira_en']}


def cargar_previsualizacion(*, previsualizacion_id: str, empresa_id: int) -> dict:
    """Carga una previsualización verificando existencia, TTL y pertenencia a `empresa_id`."""
    ruta = _ruta_segura(previsualizacion_id)
    if not ruta.is_file():
        raise NotFound('Previsualización no encontrada o expirada.')

    try:
        dato = json.loads(ruta.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise NotFound('Previsualización no encontrada o expirada.')

    if dato.get('empresa_id') != int(empresa_id):
        raise NotFound('Previsualización no encontrada o expirada.')

    if time.time() > float(dato.get('expira_ts') or 0):
        ruta.unlink(missing_ok=True)
        raise NotFound('La previsualización expiró; vuelva a previsualizar los archivos.')

    return dato['resultado']


def normalizar_paginacion(page_raw=None, page_size_raw=None) -> tuple[int, int]:
    """Valida `page >= 1` y `50 <= page_size <= 200` (por defecto page=1, page_size=100)."""
    if page_raw in (None, ''):
        page = 1
    else:
        try:
            page = int(page_raw)
        except (TypeError, ValueError):
            raise ValidationError({'page': 'El número de página debe ser un entero positivo.'})
        if page < 1:
            raise ValidationError({'page': 'El número de página debe ser mayor o igual a 1.'})

    if page_size_raw in (None, ''):
        page_size = PAGE_SIZE_DEFAULT
    else:
        try:
            page_size = int(page_size_raw)
        except (TypeError, ValueError):
            raise ValidationError({'page_size': f'El tamaño de página debe estar entre {PAGE_SIZE_MIN} y {PAGE_SIZE_MAX}.'})
        if page_size < PAGE_SIZE_MIN or page_size > PAGE_SIZE_MAX:
            raise ValidationError({'page_size': f'El tamaño de página debe estar entre {PAGE_SIZE_MIN} y {PAGE_SIZE_MAX}.'})

    return page, page_size


def filtrar_comprobantes_previsualizacion(comprobantes: list[dict], filtro_raw: str | None) -> tuple[str, list[dict]]:
    if not filtro_raw:
        filtro = 'todos'
    else:
        clave = str(filtro_raw).strip()
        if clave not in FILTROS_PREVISUALIZACION:
            raise ValidationError({'filtro': f'Filtro no válido: "{clave}".'})
        filtro = FILTROS_PREVISUALIZACION[clave]

    if filtro == 'todos':
        return filtro, comprobantes
    if filtro == 'nuevos':
        return filtro, [c for c in comprobantes if c.get('estado') == 'NUEVO']
    if filtro == 'a_completar':
        return filtro, [c for c in comprobantes if c.get('estado') == 'COMPLETAR']
    if filtro == 'ya_existen':
        return filtro, [c for c in comprobantes if c.get('estado') == 'YA_EXISTE']
    if filtro == 'errores':
        return filtro, [c for c in comprobantes if c.get('estado') == 'ERROR']
    if filtro == 'conflictos':
        return filtro, [c for c in comprobantes if c.get('estado') == 'CONFLICTO']
    if filtro == 'sin_proveedor':
        return filtro, [c for c in comprobantes if c.get('requiere_proveedor') and c.get('clave_proveedor')]
    return filtro, [c for c in comprobantes if c.get('observaciones')]


def paginar_comprobantes(comprobantes: list[dict], *, page: int = 1, page_size: int = PAGE_SIZE_DEFAULT) -> tuple[list[dict], dict]:
    total = len(comprobantes)
    total_pages = max(1, (total + page_size - 1) // page_size)
    pagina_actual = min(page, total_pages)
    inicio = (pagina_actual - 1) * page_size
    fin = inicio + page_size
    slice_items = comprobantes[inicio:fin]
    return slice_items, {
        'page': pagina_actual,
        'page_size': page_size,
        'total': total,
        'total_pages': total_pages,
        'has_next': pagina_actual < total_pages,
        'has_previous': pagina_actual > 1,
    }


def _claves_sin_proveedor(comprobantes: list[dict]) -> list[str]:
    vistas = set()
    claves = []
    for c in comprobantes:
        clave = c.get('clave_proveedor')
        if c.get('requiere_proveedor') and clave and clave not in vistas:
            vistas.add(clave)
            claves.append(clave)
    return claves


def construir_respuesta_previsualizacion_inicial(
    *,
    empresa_id: int,
    resultado: dict,
    page_size: int = PAGE_SIZE_DEFAULT,
) -> dict:
    """Guarda el diagnóstico completo en staging y responde con los contadores totales y la página 1."""
    meta = guardar_previsualizacion(empresa_id=empresa_id, resultado=resultado)
    comprobantes = resultado.get('comprobantes') or []
    pagina_comp, paginacion = paginar_comprobantes(comprobantes, page=1, page_size=page_size)

    claves_pagina = {f"{c.get('tipo')}-{c.get('serie')}-{c.get('numero')}" for c in pagina_comp}
    filas_todas = resultado.get('filas') or []
    filas_pagina = [
        f for f in filas_todas
        if f.get('comprobante') in claves_pagina or (f.get('comprobante') is None and f.get('estado') == 'ERROR')
    ][: max(page_size * 5, 250)]

    return {
        'previsualizacion_id': meta['previsualizacion_id'],
        'expira_en': meta['expira_en'],
        'formato': resultado.get('formato', 'ENTRADAS_SALIDAS'),
        'resumen': resultado.get('resumen') or {},
        'contadores': resultado.get('contadores') or {},
        'paginacion': paginacion,
        'comprobantes': pagina_comp,
        'filas': filas_pagina,
    }


def obtener_pagina_previsualizacion(
    *,
    previsualizacion_id: str,
    empresa_id: int,
    page_raw=None,
    page_size_raw=None,
    filtro_raw: str | None = None,
    incluir_claves: bool = False,
) -> dict:
    resultado = cargar_previsualizacion(previsualizacion_id=previsualizacion_id, empresa_id=empresa_id)
    page, page_size = normalizar_paginacion(page_raw, page_size_raw)
    comprobantes = resultado.get('comprobantes') or []
    filtro, filtrados = filtrar_comprobantes_previsualizacion(comprobantes, filtro_raw)
    pagina_comp, paginacion = paginar_comprobantes(filtrados, page=page, page_size=page_size)

    respuesta = {
        'previsualizacion_id': previsualizacion_id,
        'filtro': filtro,
        'contadores': resultado.get('contadores') or {},
        'paginacion': paginacion,
        'comprobantes': pagina_comp,
    }
    if incluir_claves:
        respuesta['claves_sin_proveedor'] = _claves_sin_proveedor(comprobantes)
    return respuesta


def exportar_errores_previsualizacion_excel(*, previsualizacion_id: str, empresa_id: int) -> io.BytesIO:
    """Exporta todos los errores, conflictos y observaciones de la previsualización a `.xlsx` seguro."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    from apps.reportes.excel_seguro import neutralizar_formulas

    resultado = cargar_previsualizacion(previsualizacion_id=previsualizacion_id, empresa_id=empresa_id)
    resumen = resultado.get('resumen') or {}
    comprobantes = [
        c for c in (resultado.get('comprobantes') or [])
        if c.get('estado') in ('ERROR', 'CONFLICTO') or c.get('observaciones')
    ]
    filas = [
        f for f in (resultado.get('filas') or [])
        if f.get('estado') in ('ERROR', 'CONFLICTO') or f.get('errores') or f.get('observaciones')
    ]

    colores = {'ERROR': 'FEE2E2', 'CONFLICTO': 'FEF3C7', 'NUEVO': 'D1FAE5', 'COMPLETAR': 'E0E7FF', 'YA_EXISTE': 'F1F5F9'}
    relleno_hdr = PatternFill('solid', fgColor='17365D')
    fuente_hdr = Font(bold=True, color='FFFFFF')
    centro = Alignment(horizontal='center', vertical='center', wrap_text=True)

    libro = Workbook()
    hoja_comp = libro.active
    hoja_comp.title = 'Comprobantes'
    hoja_comp.append([f'Diagnóstico de previsualización ({previsualizacion_id[:8]})'])
    hoja_comp['A1'].font = Font(bold=True, size=13)
    hoja_comp.append([
        f"Generado {timezone.localtime():%d/%m/%Y %H:%M} · Filas: {resumen.get('filas', 0)} · "
        f"Errores: {resumen.get('con_error', 0)} · Conflictos: {resumen.get('conflictos', 0)} · "
        f"Observaciones: {resumen.get('observaciones', 0)}"
    ])
    hoja_comp.append([])

    enc_comp = ['Fecha', 'Tipo', 'Serie', 'Número', 'Operación', 'RUC', 'Estado', 'Detalle / Error', 'Observaciones', 'Productos', 'Líneas']
    hoja_comp.append(enc_comp)
    fila_hdr_comp = hoja_comp.max_row
    for celda in hoja_comp[fila_hdr_comp]:
        celda.font = fuente_hdr
        celda.fill = relleno_hdr
        celda.alignment = centro

    if comprobantes:
        for c in comprobantes:
            fecha_txt = c.get('fecha') or ''
            try:
                fecha_val = datetime.strptime(fecha_txt[:10], '%Y-%m-%d').date() if fecha_txt else None
            except ValueError:
                fecha_val = fecha_txt
            hoja_comp.append([
                fecha_val,
                c.get('tipo') or '',
                c.get('serie') or '',
                c.get('numero') or '',
                c.get('operacion') or '',
                c.get('ruc') or '',
                c.get('estado') or '',
                c.get('mensaje') or '',
                '; '.join(c.get('observaciones') or []),
                ', '.join(c.get('productos') or []),
                c.get('lineas') or 0,
            ])
            n = hoja_comp.max_row
            if hasattr(fecha_val, 'year'):
                hoja_comp.cell(n, 1).number_format = 'DD/MM/YYYY'
            est = c.get('estado') or ''
            if est in colores:
                hoja_comp.cell(n, 7).fill = PatternFill('solid', fgColor=colores[est])
    else:
        hoja_comp.append(['Sin errores, conflictos ni observaciones en los comprobantes.'])

    for col, ancho in zip('ABCDEFGHIJK', (12, 8, 10, 12, 10, 14, 14, 52, 42, 24, 9)):
        hoja_comp.column_dimensions[col].width = ancho
    hoja_comp.freeze_panes = hoja_comp.cell(fila_hdr_comp + 1, 1)

    hoja_filas = libro.create_sheet('Detalle_Filas')
    enc_filas = ['Archivo', 'Fila', 'Código', 'Fecha', 'Comprobante', 'Operación', 'Cantidad', 'Costo unitario', 'Estado', 'Errores', 'Observaciones']
    hoja_filas.append(enc_filas)
    for celda in hoja_filas[1]:
        celda.font = fuente_hdr
        celda.fill = relleno_hdr
        celda.alignment = centro

    if filas:
        for f in filas:
            hoja_filas.append([
                f.get('archivo') or '',
                f.get('fila') or 0,
                f.get('codigo') or '',
                f.get('fecha') or '',
                f.get('comprobante') or '',
                f.get('operacion') or '',
                f.get('cantidad') or '',
                f.get('costo_unitario') or '',
                f.get('estado') or '',
                '; '.join(f.get('errores') or []),
                '; '.join(f.get('observaciones') or []),
            ])
            n = hoja_filas.max_row
            est = f.get('estado') or ''
            if est in colores:
                hoja_filas.cell(n, 9).fill = PatternFill('solid', fgColor=colores[est])
    else:
        hoja_filas.append(['Sin errores, conflictos ni observaciones en las filas.'])

    for col, ancho in zip('ABCDEFGHIJK', (26, 8, 14, 12, 18, 10, 12, 14, 14, 50, 40)):
        hoja_filas.column_dimensions[col].width = ancho
    hoja_filas.freeze_panes = 'A2'

    neutralizar_formulas(libro)
    salida = io.BytesIO()
    libro.save(salida)
    salida.seek(0)
    return salida
