"""
Homologación de ítems de proveedor — ÚNICA regla para normalizar y buscar equivalencias.

La usan la captura XML/OCR (vista previa y borrador), la sugerencia y la validación de
equivalencias repetidas. Nadie más compara códigos, descripciones o unidades por su cuenta.

Clave: empresa + proveedor + código del proveedor + unidad.
- La descripción solo se usa cuando el ítem NO trae código (fallback real, no "si no se
  encontró por código").
- Normalización (solo para comparar; no inventa datos): espacios al inicio/fin y repetidos
  o saltos de línea → un espacio; mayúsculas/minúsculas indistintas; '—' / '-' (lo que la
  pantalla mostraba sin código) cuenta como vacío. Unidad: código en mayúsculas y sin espacios.
- Una equivalencia sin unidad externa sirve para cualquier unidad; con unidad, solo para esa
  (el factor de conversión depende de la unidad).
- Solo equivalencias activas y confirmadas, del mismo proveedor y de la misma empresa.

QA2-001: la captura no aplicaba nada hasta generar el borrador (la vista previa del XML 2
mostraba otra vez "Homologar") y el proveedor recién se creaba en ese paso (al homologar el
XML 1 antes del borrador el proveedor no existía). `homologacion_de_captura` resuelve el
proveedor y las líneas con esta misma regla en cuanto el XML se sube.
"""
import re

from apps.inventario.models import ProductoEquivalencia, Tercero

_ESPACIOS = re.compile(r'\s+')
_VACIOS = {'', '-', '—', '–'}


def normalizar_texto(valor):
    """'  sku  77\\n' → 'SKU 77'. Vacío o marcador '—' → ''."""
    texto = _ESPACIOS.sub(' ', str(valor or '')).strip()
    return '' if texto in _VACIOS else texto.upper()


def limpiar_texto(valor):
    """Para guardar: mismos espacios que normalizar_texto pero conservando mayúsculas."""
    texto = _ESPACIOS.sub(' ', str(valor or '')).strip()
    return None if texto in _VACIOS else texto


def normalizar_unidad(valor):
    return _ESPACIOS.sub('', str(getattr(valor, 'codigo', valor) or '')).upper()


def solo_digitos(valor):
    return ''.join(ch for ch in str(valor or '') if ch.isdigit())


def unidad_de(equivalencia):
    return normalizar_unidad(equivalencia.unidad_externa_codigo_id)


def criterio_de(codigo, descripcion):
    """('codigo', 'ABC-01') | ('descripcion', 'TORNILLO 3/8') | (None, '')."""
    codigo, descripcion = normalizar_texto(codigo), normalizar_texto(descripcion)
    if codigo:
        return 'codigo', codigo
    if descripcion:
        return 'descripcion', descripcion
    return None, ''


def _misma_clave(equivalencia, criterio, clave):
    if criterio == 'codigo':
        return normalizar_texto(equivalencia.codigo_externo) == clave
    if criterio == 'descripcion':
        # Fallback por descripción: solo equivalencias registradas SIN código.
        return not normalizar_texto(equivalencia.codigo_externo) and normalizar_texto(equivalencia.descripcion_externa) == clave
    return False


def _unidad_compatible(equivalencia, unidad):
    return not unidad or not unidad_de(equivalencia) or unidad_de(equivalencia) == unidad


def buscar_equivalencia(*, empresa_id, tercero, codigo, descripcion='', unidad='', candidatas=None):
    """
    (equivalencia | None, motivo). Motivo: 'ok', 'sin proveedor', 'sin código ni descripción',
    'sin equivalencia' o la unidad distinta encontrada.
    """
    if tercero is None:
        return None, 'sin proveedor'
    criterio, clave = criterio_de(codigo, descripcion)
    if criterio is None:
        return None, 'sin código ni descripción'
    if candidatas is None:
        candidatas = equivalencias_del_proveedor(empresa_id, tercero)
    unidad = normalizar_unidad(unidad)
    otra_unidad = None
    for equivalencia in candidatas:
        if not _misma_clave(equivalencia, criterio, clave):
            continue
        if _unidad_compatible(equivalencia, unidad):
            return equivalencia, 'ok'
        otra_unidad = otra_unidad or equivalencia
    if otra_unidad is not None:
        return None, f'existe una equivalencia para la unidad {unidad_de(otra_unidad)}, pero el comprobante trae {unidad}'
    return None, 'sin equivalencia'


def equivalencias_del_proveedor(empresa_id, tercero):
    tercero_id = getattr(tercero, 'id', tercero)
    return list(ProductoEquivalencia.objects.filter(
        empresa_id=empresa_id, tercero_id=tercero_id, activa=True, confirmado_por__isnull=False,
    ).select_related('producto_unidad__producto', 'producto_unidad__unidad_codigo').order_by('id'))


def equivalencia_activa_repetida(*, empresa_id, tercero, codigo, descripcion, unidad, excluir_id=None):
    """Otra equivalencia ACTIVA con la misma clave y unidad compatible, o None."""
    criterio, clave = criterio_de(codigo, descripcion)
    if criterio is None or tercero is None:
        return None
    qs = ProductoEquivalencia.objects.filter(empresa_id=empresa_id, tercero=tercero, activa=True)
    if excluir_id is not None:
        qs = qs.exclude(pk=excluir_id)
    unidad = normalizar_unidad(unidad)
    for e in qs.select_related('producto_unidad__producto').order_by('id'):
        if _misma_clave(e, criterio, clave) and _unidad_compatible(e, unidad):
            return e
    return None


# ---- Proveedor del comprobante -------------------------------------------------------------

def tercero_por_documento(*, empresa_id, documento, crear=False, nombre='', clase='COMPRA'):
    """
    Tercero de la empresa con ese RUC/DNI (el mismo que usa el borrador). Con `crear`, lo crea
    si no existe y lo marca como proveedor/cliente si aún no lo estaba (para que aparezca en la
    lista de proveedores al homologar). Sin documento válido → None.
    """
    documento = solo_digitos(documento)
    if len(documento) not in (8, 11):
        return None
    tercero = Tercero.objects.filter(empresa_id=empresa_id, numero_documento=documento).order_by('id').first()
    if tercero is None and crear:
        tercero = Tercero.objects.create(
            empresa_id=empresa_id, numero_documento=documento,
            tipo_documento='6' if len(documento) == 11 else '1',
            razon_social=(nombre or '').strip() or f'{"PROVEEDOR" if clase == "COMPRA" else "CLIENTE"} {documento}',
            es_proveedor=clase == 'COMPRA', es_cliente=clase == 'VENTA',
        )
    elif tercero is not None and crear:
        campo = 'es_proveedor' if clase == 'COMPRA' else 'es_cliente'
        if not getattr(tercero, campo):
            setattr(tercero, campo, True)
            tercero.save(update_fields=[campo])
    return tercero


# ---- Captura -------------------------------------------------------------------------------

def valores_captura(captura):
    """(cabecera, {linea: campos}) con el valor efectivo (corregido si existe, si no el extraído)."""
    cabecera, detalles = {}, {}
    for c in captura.campos.all():
        val = c.valor_corregido if (c.valor_corregido is not None and c.valor_corregido != '') else (c.valor_extraido or '')
        if c.seccion == 'CABECERA':
            cabecera[c.nombre_campo] = val
        elif c.seccion == 'DETALLE':
            detalles.setdefault(c.numero_linea or 1, {})[c.nombre_campo] = val
    return cabecera, detalles


def homologar_linea(*, empresa_id, clase, tercero, codigo, descripcion, unidad, candidatas=None):
    """
    Resultado de una línea: {'estado': 'HOMOLOGADA'|'PENDIENTE', 'criterio', 'equivalencia',
    'producto', 'producto_unidad', 'factor', 'motivo'}. Compra: equivalencia del proveedor.
    Venta: la empresa emitió el comprobante con su propio código interno.
    """
    from decimal import Decimal
    from apps.inventario.models import Producto

    criterio, clave = criterio_de(codigo, descripcion)
    base = {'criterio': criterio, 'clave': clave, 'equivalencia': None, 'producto': None, 'producto_unidad': None,
            'factor': Decimal('1'), 'estado': 'PENDIENTE', 'motivo': ''}
    if clase == 'VENTA':
        producto = Producto.objects.filter(empresa_id=empresa_id, codigo_interno__iexact=(codigo or '').strip()).first() if normalizar_texto(codigo) else None
        unidad_base = producto.unidades.filter(es_base=True).first() if producto else None
        if unidad_base is not None:
            base.update(estado='HOMOLOGADA', producto=producto, producto_unidad=unidad_base, motivo='código interno')
        else:
            base['motivo'] = 'sin producto con ese código interno'
        return base
    equivalencia, motivo = buscar_equivalencia(
        empresa_id=empresa_id, tercero=tercero, codigo=codigo, descripcion=descripcion, unidad=unidad, candidatas=candidatas,
    )
    base['motivo'] = motivo
    if equivalencia is not None:
        base.update(estado='HOMOLOGADA', equivalencia=equivalencia, producto=equivalencia.producto_unidad.producto,
                    producto_unidad=equivalencia.producto_unidad, factor=equivalencia.factor_conversion)
    return base


def homologacion_de_captura(captura):
    """
    Vista previa de la homologación de una captura con la MISMA regla que el borrador:
    {'clase', 'proveedor': {...}, 'lineas': [...], 'pendientes_homologacion': n}.
    No crea nada (el proveedor se crea al registrar la equivalencia o al generar el borrador).
    """
    from django.core.exceptions import ValidationError as DjangoValidationError
    from rest_framework.exceptions import ValidationError
    from apps.documentos.clasificacion_captura import clasificar_comprobante
    from apps.empresas.models import Empresa

    cabecera, detalles = valores_captura(captura)
    empresa = Empresa.objects.get(pk=captura.empresa_id)
    try:
        clasificacion = clasificar_comprobante(cabecera=cabecera, ruc_empresa=empresa.ruc)
    except (ValidationError, DjangoValidationError) as exc:
        detalle = getattr(exc, 'detail', None) or getattr(exc, 'message_dict', None) or str(exc)
        return {'clase': None, 'proveedor': None, 'lineas': [], 'pendientes_homologacion': None,
                'error': detalle if isinstance(detalle, str) else ' '.join(str(v) for v in (detalle.values() if isinstance(detalle, dict) else detalle))}
    clase = clasificacion['clase']
    documento = solo_digitos(clasificacion['contraparte_documento'])
    tercero = tercero_por_documento(empresa_id=captura.empresa_id, documento=documento)
    candidatas = equivalencias_del_proveedor(captura.empresa_id, tercero) if (clase == 'COMPRA' and tercero) else []
    lineas = []
    for numero, campos in sorted(detalles.items()):
        codigo = (campos.get('codigo_externo') or '').strip()
        descripcion = (campos.get('descripcion') or '').strip()
        unidad = (campos.get('unidad_medida') or 'NIU').strip()
        r = homologar_linea(empresa_id=captura.empresa_id, clase=clase, tercero=tercero, codigo=codigo,
                            descripcion=descripcion, unidad=unidad, candidatas=candidatas)
        lineas.append({
            'linea': numero, 'codigo_externo': codigo, 'codigo_normalizado': normalizar_texto(codigo),
            'descripcion': descripcion, 'unidad': unidad, 'unidad_normalizada': normalizar_unidad(unidad),
            'criterio': r['criterio'], 'estado': r['estado'], 'motivo': r['motivo'],
            'equivalencia_id': r['equivalencia'].id if r['equivalencia'] else None,
            'producto_id': r['producto'].id if r['producto'] else None,
            'producto_codigo': r['producto'].codigo_interno if r['producto'] else None,
            'producto_unidad_id': r['producto_unidad'].id if r['producto_unidad'] else None,
            'factor_conversion': str(r['factor']),
        })
    return {
        'clase': clase,
        'proveedor': {
            'documento': documento, 'nombre': clasificacion.get('contraparte_nombre') or '',
            'tercero_id': tercero.id if tercero else None,
            'razon_social': tercero.razon_social if tercero else None,
        },
        'lineas': lineas,
        'pendientes_homologacion': sum(1 for x in lineas if x['estado'] != 'HOMOLOGADA'),
    }


def proveedor_de_captura(captura, *, crear=False):
    """Proveedor (emisor) de una captura de COMPRA; con `crear`, lo registra si no existe."""
    from apps.documentos.clasificacion_captura import clasificar_comprobante
    from apps.empresas.models import Empresa

    cabecera, _ = valores_captura(captura)
    clasificacion = clasificar_comprobante(cabecera=cabecera, ruc_empresa=Empresa.objects.get(pk=captura.empresa_id).ruc)
    if clasificacion['clase'] != 'COMPRA':
        return None
    return tercero_por_documento(empresa_id=captura.empresa_id, documento=clasificacion['contraparte_documento'],
                                 crear=crear, nombre=clasificacion.get('contraparte_nombre') or '', clase='COMPRA')
