"""
Importación masiva de comprobantes desde el Excel "Entradas y salidas" (formato Kardex por producto).

Paso 1: solo lectura y previsualización. No graba nada.

Formato (el que exporta el sistema anterior del cliente), un archivo por producto:
    Código | Fecha | Tipo | Serie | Número | Tipo de operación |
    ENTRADAS: Cantidad, Costo unitario, Costo total | SALIDAS: Cantidad, Costo unitario, Costo total
y, opcionales al final: RUC/DNI | Razón social | Precio unitario | Moneda.

Reglas:
- Ninguna fila se descarta en silencio: cada una sale como NUEVO, YA_EXISTE, CONFLICTO o ERROR.
- Un comprobante puede venir repartido en varios archivos (uno por producto): se agrupa.
- Contra lo ya registrado se compara por línea: si el comprobante existe pero le falta un producto
  del Excel, es CONFLICTO (nunca se omite).
- Las notas de crédito se emparejan con su venta (o compra) de origen por producto y cantidad.
"""
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from openpyxl import load_workbook

from apps.catalogos.models import TipoComprobante
from apps.documentos.models import Documento, DocumentoDetalle
from apps.documentos.services import MONEDAS_SOPORTADAS, normalizar_numero, normalizar_serie
from apps.empresas.models import Empresa, Periodo
from apps.inventario.models import Producto

MAX_FILAS = 5000
MAX_ARCHIVOS = 50
CERO = Decimal('0')

# Tipo de operación (Tabla 12 SUNAT) → (clase del comprobante, naturaleza en el Kardex)
OPERACIONES = {
    '01': ('VENTA', 'SALIDA', 'Venta'),
    '02': ('COMPRA', 'ENTRADA', 'Compra'),
    '05': ('VENTA', 'ENTRADA', 'Devolución recibida'),
    '06': ('COMPRA', 'SALIDA', 'Devolución entregada'),
}
DEVOLUCIONES = ('05', '06')

ENCABEZADOS_OPCIONALES = {
    'ruc': ('ruc', 'dni', 'ruc/dni', 'ruc / dni', 'ruc o dni', 'documento'),
    'razon_social': ('razon social', 'cliente/proveedor', 'nombre'),
    'precio_unitario': ('precio unitario', 'precio', 'precio unitario sin igv', 'valor unitario'),
    'moneda': ('moneda',),
}


@dataclass
class FilaKardex:
    archivo: str
    fila: int
    codigo: str = ''
    fecha: date | None = None
    tipo: str = ''
    serie: str = ''
    numero: str = ''
    operacion: str = ''
    cantidad: Decimal = CERO
    costo_unitario: Decimal = CERO
    costo_total: Decimal = CERO
    ruc: str = ''
    razon_social: str = ''
    precio_unitario: Decimal | None = None
    moneda: str = 'PEN'
    estado: str = ''
    errores: list = field(default_factory=list)
    observaciones: list = field(default_factory=list)

    @property
    def clase(self):
        return OPERACIONES[self.operacion][0] if self.operacion in OPERACIONES else ''

    @property
    def naturaleza(self):
        return OPERACIONES[self.operacion][1] if self.operacion in OPERACIONES else ''


def _texto(valor) -> str:
    if valor is None:
        return ''
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _normalizar(texto) -> str:
    limpio = unicodedata.normalize('NFD', _texto(texto)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', limpio).strip()


def _decimal(valor, campo, errores) -> Decimal:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return CERO
    try:
        numero = Decimal(str(valor).strip().replace(',', ''))
    except (InvalidOperation, ValueError):
        errores.append(f'{campo} no es un número válido ("{_texto(valor)}").')
        return CERO
    if not numero.is_finite():
        errores.append(f'{campo} no es un número válido.')
        return CERO
    return numero


def _fecha(valor, errores):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = _texto(valor)
    for formato in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    errores.append(f'Fecha inválida ("{texto}").' if texto else 'Falta la fecha.')
    return None


def _tipo_comprobante(valor, errores) -> str:
    texto = _texto(valor)
    if texto.isdigit() and 1 <= len(texto) <= 2:
        return texto.zfill(2)
    errores.append(f'Tipo de comprobante inválido ("{texto}"). Use 1 Factura, 3 Boleta, 7 Nota de crédito.')
    return ''


def _operacion(valor, errores) -> str:
    texto = _texto(valor)
    codigo = re.match(r'^\s*(\d{1,2})', texto)
    codigo = codigo.group(1).zfill(2) if codigo else ''
    if codigo not in OPERACIONES:
        errores.append(
            f'Tipo de operación no soportado ("{texto}"). Use 01 Venta, 02 Compra, '
            '05 Devolución recibida o 06 Devolución entregada.'
        )
        return ''
    return codigo


def _ubicar_encabezado(filas):
    """Índice de la fila con 'Fecha' y 'Tipo' (la segunda fila de encabezado del formato)."""
    for i, fila in enumerate(filas[:10]):
        textos = [_normalizar(c) for c in fila]
        if 'fecha' in textos and 'tipo' in textos:
            return i
    return None


def _columnas_opcionales(filas, indice):
    columnas = {}
    candidatas = [filas[indice]] + ([filas[indice - 1]] if indice > 0 else [])
    for fila in candidatas:
        for col, valor in enumerate(fila):
            if col < 12:
                continue
            texto = _normalizar(valor)
            for clave, nombres in ENCABEZADOS_OPCIONALES.items():
                if clave not in columnas and texto in nombres:
                    columnas[clave] = col
    return columnas


def leer_archivo(archivo, nombre: str) -> list[FilaKardex]:
    try:
        libro = load_workbook(archivo, read_only=True, data_only=True)
    except Exception as exc:
        raise ValidationError({'archivos': f'No se pudo leer "{nombre}" como Excel (.xlsx): {exc}'})
    try:
        filas = [tuple(f) for f in libro.worksheets[0].iter_rows(values_only=True)]
    finally:
        libro.close()

    indice = _ubicar_encabezado(filas)
    if indice is None:
        raise ValidationError({'archivos': f'"{nombre}" no tiene el formato Entradas y salidas (no se encontró la fila de encabezado con Fecha y Tipo).'})
    opcionales = _columnas_opcionales(filas, indice)

    resultado = []
    for numero_fila, valores in enumerate(filas[indice + 1:], start=indice + 2):
        valores = list(valores) + [None] * max(0, 12 - len(valores))
        if all(v is None or _texto(v) == '' for v in valores):
            continue
        fila = FilaKardex(archivo=nombre, fila=numero_fila)
        e = fila.errores
        fila.codigo = _texto(valores[0])
        if not fila.codigo:
            e.append('Falta el código del producto.')
        fila.fecha = _fecha(valores[1], e)
        fila.tipo = _tipo_comprobante(valores[2], e)
        fila.serie = normalizar_serie(_texto(valores[3]))
        fila.numero = normalizar_numero(_texto(valores[4]))
        if not fila.serie:
            e.append('Falta la serie.')
        if fila.numero == '0':
            e.append('Falta el número del comprobante.')
        fila.operacion = _operacion(valores[5], e)

        ent = [_decimal(valores[i], n, e) for i, n in ((6, 'Cantidad de entrada'), (7, 'Costo unitario de entrada'), (8, 'Costo total de entrada'))]
        sal = [_decimal(valores[i], n, e) for i, n in ((9, 'Cantidad de salida'), (10, 'Costo unitario de salida'), (11, 'Costo total de salida'))]
        if ent[0] > CERO and sal[0] > CERO:
            e.append('La fila tiene cantidad de entrada y de salida a la vez.')
        elif fila.operacion:
            usado, otro = (ent, sal) if fila.naturaleza == 'ENTRADA' else (sal, ent)
            if usado[0] <= CERO:
                lado = 'entrada' if fila.naturaleza == 'ENTRADA' else 'salida'
                e.append(f'{OPERACIONES[fila.operacion][2]} sin cantidad de {lado}.')
            if otro[0] != CERO:
                e.append(f'{OPERACIONES[fila.operacion][2]} con cantidad en la columna equivocada.')
            fila.cantidad, fila.costo_unitario, fila.costo_total = usado
            if fila.costo_unitario < CERO or fila.costo_total < CERO:
                e.append('El costo no puede ser negativo.')

        if 'ruc' in opcionales:
            fila.ruc = re.sub(r'\D', '', _texto(valores[opcionales['ruc']]) if opcionales['ruc'] < len(valores) else '')
            if fila.ruc and len(fila.ruc) not in (8, 11):
                e.append(f'RUC/DNI inválido ("{fila.ruc}"): debe tener 11 dígitos (RUC) u 8 (DNI).')
        if 'razon_social' in opcionales and opcionales['razon_social'] < len(valores):
            fila.razon_social = _texto(valores[opcionales['razon_social']])
        if 'precio_unitario' in opcionales and opcionales['precio_unitario'] < len(valores):
            bruto = valores[opcionales['precio_unitario']]
            if _texto(bruto):
                fila.precio_unitario = _decimal(bruto, 'Precio unitario', e)
                if fila.precio_unitario < CERO:
                    e.append('El precio unitario no puede ser negativo.')
        if 'moneda' in opcionales and opcionales['moneda'] < len(valores):
            moneda = _texto(valores[opcionales['moneda']]).upper() or 'PEN'
            fila.moneda = {'S/': 'PEN', 'SOLES': 'PEN', '$': 'USD', 'DOLARES': 'USD'}.get(moneda, moneda)
            if fila.moneda not in MONEDAS_SOPORTADAS:
                e.append(f'Moneda no soportada ("{moneda}"). Use PEN o USD.')
        resultado.append(fila)
    return resultado


def _periodo_de(periodos, fecha):
    for p in periodos:
        if p.fecha_inicio <= fecha <= p.fecha_fin:
            return p
    return None


def _clave_comprobante(fila, ruc_empresa):
    """Clave lógica igual a la del sistema: RUC emisor + tipo + serie + número."""
    ruc_emisor = ruc_empresa if fila.clase == 'VENTA' else fila.ruc
    return (ruc_emisor, fila.tipo, fila.serie, fila.numero)


def _validar_contexto(filas, empresa_id):
    codigos = {f.codigo for f in filas if f.codigo}
    productos = {p.codigo_interno: p for p in Producto.objects.filter(empresa_id=empresa_id, codigo_interno__in=codigos)}
    periodos = list(Periodo.objects.filter(empresa_id=empresa_id).order_by('fecha_inicio'))
    tipos = {t.codigo_sunat: t for t in TipoComprobante.objects.filter(codigo_sunat__in={f.tipo for f in filas if f.tipo})}

    for f in filas:
        e = f.errores
        if f.codigo:
            producto = productos.get(f.codigo)
            if not producto:
                e.append(f'El producto {f.codigo} no existe en la empresa. Regístrelo antes de importar.')
            elif producto.estado != 'ACTIVO':
                e.append(f'El producto {f.codigo} está inactivo.')
        if f.fecha:
            periodo = _periodo_de(periodos, f.fecha)
            if not periodo:
                e.append(f'No existe el período {f.fecha:%Y-%m} en la empresa.')
            elif periodo.estado == 'CERRADO':
                e.append(f'El período {f.fecha:%Y-%m} está cerrado.')
        if f.tipo:
            tipo = tipos.get(f.tipo)
            if not tipo or not tipo.activo:
                e.append(f'El tipo de comprobante {f.tipo} no está habilitado en el sistema.')
            elif f.operacion:
                if f.operacion in DEVOLUCIONES and not tipo.es_nota:
                    e.append('Una devolución debe venir con nota de crédito (tipo 7).')
                if f.operacion not in DEVOLUCIONES and tipo.es_nota:
                    e.append('Una nota de crédito solo puede ser devolución (05 o 06).')
        if f.clase == 'COMPRA' and f.operacion and len(f.ruc) != 11:
            e.append('Una compra necesita el RUC del proveedor (11 dígitos) en la columna RUC/DNI.')
        if f.clase == 'VENTA' and f.tipo == '01' and not f.ruc:
            f.observaciones.append('Factura sin RUC del cliente: se registrará con el cliente genérico "VARIOS (importación)".')
        if f.naturaleza == 'SALIDA' and f.cantidad > CERO and f.costo_unitario == CERO:
            f.observaciones.append('Costo 0 en el Excel: se valoriza con el costo promedio del sistema.')
        if f.clase == 'VENTA' and f.operacion == '01' and f.precio_unitario is None:
            f.observaciones.append('Sin precio de venta: entra a costo y no suma ingresos en el dashboard.')
    return productos


def _agrupar(filas, ruc_empresa):
    grupos = defaultdict(list)
    for f in filas:
        if f.tipo and f.serie and f.numero != '0' and f.operacion:
            grupos[_clave_comprobante(f, ruc_empresa)].append(f)
    for lineas in grupos.values():
        fechas = {l.fecha for l in lineas if l.fecha}
        operaciones = {l.operacion for l in lineas}
        rucs = {l.ruc for l in lineas}
        monedas = {l.moneda for l in lineas}
        problemas = []
        if len(fechas) > 1:
            problemas.append('El mismo comprobante aparece con fechas distintas.')
        if len(operaciones) > 1:
            problemas.append('El mismo comprobante mezcla tipos de operación distintos.')
        if len(rucs) > 1:
            problemas.append('El mismo comprobante aparece con RUC/DNI distintos.')
        if len(monedas) > 1:
            problemas.append('El mismo comprobante aparece con monedas distintas.')
        for l in lineas:
            l.errores.extend(problemas)
    return grupos


def _existentes(empresa_id, claves):
    if not claves:
        return {}
    series = {c[2] for c in claves}
    docs = (
        Documento.objects.filter(empresa_id=empresa_id, serie_normalizada__in=series)
        .exclude(estado='ANULADO')
        .select_related('tipo_comprobante')
        .prefetch_related('detalles')
    )
    resultado = {}
    for d in docs:
        clave = (d.ruc_emisor, d.tipo_comprobante.codigo_sunat, d.serie_normalizada, d.numero_normalizado)
        if clave in claves:
            resultado[clave] = d
    return resultado


def _emparejar_devoluciones(grupos, productos, empresa_id, ruc_empresa):
    """
    Cada nota de crédito necesita su comprobante de origen. Se busca, por producto y cantidad,
    la venta (o compra) de la misma fecha o la más cercana anterior, primero en el Excel y
    luego en lo ya registrado. Cada línea de origen se usa una sola vez.
    """
    usados = set()
    candidatos = defaultdict(list)
    for clave, lineas in grupos.items():
        for i, l in enumerate(lineas):
            if l.operacion in ('01', '02') and l.fecha and not l.errores:
                candidatos[(l.clase, l.codigo, l.cantidad)].append((l.fecha, clave, i))

    origenes = {}
    for clave, lineas in grupos.items():
        if lineas[0].operacion not in DEVOLUCIONES:
            continue
        destinos = set()
        for l in lineas:
            if l.errores or not l.fecha:
                continue
            opciones = sorted(
                (c for c in candidatos[(l.clase, l.codigo, l.cantidad)] if c[0] <= l.fecha and (c[1], c[2]) not in usados),
                key=lambda c: (l.fecha - c[0], c[1]),
            )
            if opciones:
                fecha, origen, i = opciones[0]
                usados.add((origen, i))
                destinos.add(('EXCEL', origen))
                continue
            producto = productos.get(l.codigo)
            existente = (
                DocumentoDetalle.objects.filter(
                    documento__empresa_id=empresa_id, documento__clase=l.clase, documento__estado='CONFIRMADO',
                    documento__tipo_comprobante__es_nota=False, documento__fecha_emision__lte=l.fecha,
                    producto=producto, cantidad_original=l.cantidad,
                ).select_related('documento__tipo_comprobante').order_by('-documento__fecha_emision', '-id').first()
                if producto else None
            )
            if existente:
                d = existente.documento
                destinos.add(('SISTEMA', (d.ruc_emisor, d.tipo_comprobante.codigo_sunat, d.serie_normalizada, d.numero_normalizado)))
            else:
                l.errores.append(
                    f'Devolución sin comprobante de origen: no hay una {"venta" if l.clase == "VENTA" else "compra"} '
                    f'de {l.codigo} por {l.cantidad} en esa fecha o antes.'
                )
        if len(destinos) > 1:
            for l in lineas:
                l.errores.append('Las líneas de la nota de crédito corresponden a comprobantes de origen distintos.')
        elif destinos:
            fuente, origen = destinos.pop()
            origenes[clave] = {'fuente': fuente, 'comprobante': f'{origen[2]}-{origen[3]}', 'tipo': origen[1]}
            if lineas[0].serie[:1] != origen[2][:1]:
                for l in lineas:
                    l.observaciones.append(f'La nota {l.serie} devuelve el comprobante {origen[2]}-{origen[3]} de otra serie.')
    return origenes


def _texto_decimal(valor):
    return None if valor is None else format(valor, 'f')


def previsualizar_importacion_kardex(*, empresa_id: int, archivos) -> dict:
    """archivos: lista de (nombre, archivo). Devuelve el diagnóstico sin escribir nada."""
    if not archivos:
        raise ValidationError({'archivos': 'Adjunte al menos un archivo Excel (.xlsx).'})
    if len(archivos) > MAX_ARCHIVOS:
        raise ValidationError({'archivos': f'Máximo {MAX_ARCHIVOS} archivos por importación.'})
    empresa = Empresa.objects.get(pk=empresa_id)

    filas = []
    for nombre, archivo in archivos:
        filas.extend(leer_archivo(archivo, nombre))
        if len(filas) > MAX_FILAS:
            raise ValidationError({'archivos': f'La importación supera el máximo de {MAX_FILAS} filas. Divídala por período.'})
    if not filas:
        raise ValidationError({'archivos': 'Los archivos no tienen filas de datos.'})

    productos = _validar_contexto(filas, empresa_id)
    grupos = _agrupar(filas, empresa.ruc)
    origenes = _emparejar_devoluciones(grupos, productos, empresa_id, empresa.ruc)
    existentes = _existentes(empresa_id, set(grupos))

    comprobantes = []
    for clave, lineas in grupos.items():
        primera = lineas[0]
        errores = sorted({m for l in lineas for m in l.errores})
        existente = existentes.get(clave)
        faltantes = []
        if errores:
            estado = 'ERROR'
        elif existente:
            registrados = {d.producto_id for d in existente.detalles.all()}
            faltantes = sorted({l.codigo for l in lineas if productos[l.codigo].id not in registrados})
            estado = 'CONFLICTO' if faltantes else 'YA_EXISTE'
        else:
            estado = 'NUEVO'
        if estado == 'CONFLICTO':
            mensaje = (
                f'El comprobante ya está registrado sin los productos {", ".join(faltantes)}. '
                'Suba juntos todos los archivos del período o anule el lote anterior.'
            )
        elif estado == 'YA_EXISTE':
            mensaje = 'Ya está registrado con estos productos: se omite, no se sobrescribe.'
        else:
            mensaje = '; '.join(errores)
        comprobantes.append({
            'clave': f'{primera.tipo}-{primera.serie}-{primera.numero}' + (f'-{primera.ruc}' if primera.clase == 'COMPRA' else ''),
            'clase': primera.clase,
            'operacion': primera.operacion,
            'tipo': primera.tipo,
            'serie': primera.serie,
            'numero': primera.numero,
            'fecha': primera.fecha.isoformat() if primera.fecha else None,
            'ruc': primera.ruc or None,
            'naturaleza': primera.naturaleza,
            'lineas': len(lineas),
            'productos': sorted({l.codigo for l in lineas}),
            'origen': origenes.get(clave),
            'estado': estado,
            'mensaje': mensaje,
            'observaciones': sorted({m for l in lineas for m in l.observaciones}),
            '_orden': (primera.fecha or date.max, 0 if primera.naturaleza == 'ENTRADA' else 1, primera.serie, primera.numero.zfill(12)),
        })
        for l in lineas:
            l.estado = estado if not l.errores else 'ERROR'
            if estado == 'ERROR' and not l.errores:
                l.errores.append('Otra línea del mismo comprobante tiene error.')

    comprobantes.sort(key=lambda c: c['_orden'])
    for c in comprobantes:
        del c['_orden']

    detalle_filas = []
    for f in filas:
        estado = f.estado or 'ERROR'
        if estado == 'ERROR' and not f.errores:
            f.errores.append('La fila no se pudo asociar a un comprobante.')
        detalle_filas.append({
            'archivo': f.archivo, 'fila': f.fila, 'codigo': f.codigo,
            'fecha': f.fecha.isoformat() if f.fecha else None,
            'comprobante': f'{f.tipo}-{f.serie}-{f.numero}' if f.tipo and f.serie else None,
            'operacion': f.operacion or None, 'naturaleza': f.naturaleza or None,
            'cantidad': _texto_decimal(f.cantidad), 'costo_unitario': _texto_decimal(f.costo_unitario),
            'costo_total': _texto_decimal(f.costo_total), 'precio_unitario': _texto_decimal(f.precio_unitario),
            'estado': estado, 'errores': f.errores, 'observaciones': f.observaciones,
        })

    contar = lambda e: sum(1 for c in comprobantes if c['estado'] == e)
    fechas = [f.fecha for f in filas if f.fecha]
    return {
        'formato': 'ENTRADAS_SALIDAS',
        'resumen': {
            'archivos': len(archivos),
            'filas': len(filas),
            'filas_con_error': sum(1 for f in detalle_filas if f['estado'] == 'ERROR'),
            'filas_con_observacion': sum(1 for f in detalle_filas if f['observaciones']),
            'comprobantes': len(comprobantes),
            'nuevos': contar('NUEVO'),
            'ya_existen': contar('YA_EXISTE'),
            'conflictos': contar('CONFLICTO'),
            'con_error': contar('ERROR'),
            'productos': len({f.codigo for f in filas if f.codigo}),
            'desde': min(fechas).isoformat() if fechas else None,
            'hasta': max(fechas).isoformat() if fechas else None,
            'puede_confirmar': contar('NUEVO') > 0 and contar('ERROR') == 0 and contar('CONFLICTO') == 0,
        },
        'comprobantes': comprobantes,
        'filas': detalle_filas,
    }
