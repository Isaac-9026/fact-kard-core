"""
Importación masiva de comprobantes desde el Excel "Entradas y salidas" (formato Kardex por producto).

Paso 1: solo lectura y previsualización. No graba nada.

Formato (el que exporta el sistema anterior del cliente), un archivo por producto:
    Código | Fecha | Tipo | Serie | Número | Tipo de operación |
    ENTRADAS: Cantidad, Costo unitario, Costo total | SALIDAS: Cantidad, Costo unitario, Costo total
y, opcionales al final: RUC/DNI | Razón social | Precio unitario | Moneda.

Reglas:
- Ninguna fila se descarta en silencio: cada una sale como NUEVO, COMPLETAR, YA_EXISTE, CONFLICTO o ERROR.
- Un comprobante puede venir repartido en varios archivos (uno por producto): se agrupa.
- Contra lo ya registrado se compara por línea. Si al comprobante le falta un producto del Excel y
  fue importado y confirmado (cabecera igual, período abierto, sin cobros ni pagos), es COMPLETAR:
  se le agregará solo esa línea. Si no se puede completar, o el mismo producto trae otra cantidad o
  costo, es CONFLICTO (nunca se omite en silencio).
- Las notas de crédito se emparejan con su venta (o compra) de origen por producto y cantidad.
"""
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from rest_framework.exceptions import ValidationError

from apps.catalogos.models import TipoComprobante
from django.db.models import Prefetch

from apps.documentos.models import Documento, DocumentoDetalle, PagoDocumento
from apps.documentos.services import MONEDAS_SOPORTADAS, normalizar_numero, normalizar_serie
from apps.empresas.models import Empresa, Periodo
from apps.inventario.models import Producto

MAX_FILAS = 5000
# Medido con 810 comprobantes reales en modo lote: importar 19.6 s, anular 17.7 s, reimportar 30.9 s.
# 1500 deja margen frente al límite de 120 s del servidor.
MAX_COMPROBANTES_LOTE = 1500
MAX_ARCHIVOS = 50
CERO = Decimal('0')
# Diferencia máxima para considerar que el costo de una línea del Excel es el ya registrado.
TOLERANCIA_COSTO = Decimal('0.000001')

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
    origen: tuple | None = None
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


def clave_proveedor(fila) -> str:
    """Identifica una compra sin RUC para elegir su proveedor en pantalla (nunca una regla fija)."""
    return f'{fila.tipo}-{fila.serie}-{fila.numero}-{fila.fecha.isoformat() if fila.fecha else ""}'


def _aplicar_proveedores(filas, proveedores):
    if not proveedores:
        return
    if not isinstance(proveedores, dict):
        raise ValidationError({'proveedores': 'Debe ser un objeto {comprobante: RUC}.'})
    limpios = {}
    for clave, ruc in proveedores.items():
        ruc = re.sub(r'\D', '', str(ruc or ''))
        if len(ruc) != 11:
            raise ValidationError({'proveedores': f'RUC inválido para {clave}: debe tener 11 dígitos.'})
        limpios[str(clave)] = ruc
    for f in filas:
        if f.clase == 'COMPRA' and not f.ruc and clave_proveedor(f) in limpios:
            f.ruc = limpios[clave_proveedor(f)]


def _tipo_identidad(numero):
    from apps.inventario.documentos_identidad import DNI, RUC
    return RUC if len(numero) == 11 else DNI


def _validar_contexto(filas, empresa_id):
    from apps.inventario.models import Tercero
    codigos = {f.codigo for f in filas if f.codigo}
    productos = {p.codigo_interno: p for p in Producto.objects.filter(empresa_id=empresa_id, codigo_interno__in=codigos)}
    periodos = list(Periodo.objects.filter(empresa_id=empresa_id).order_by('fecha_inicio'))
    tipos = {t.codigo_sunat: t for t in TipoComprobante.objects.filter(codigo_sunat__in={f.tipo for f in filas if f.tipo})}
    terceros = {
        (t.tipo_documento, t.numero_documento): t
        for t in Tercero.objects.filter(empresa_id=empresa_id, numero_documento__in={f.ruc for f in filas if f.ruc})
    }

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
            e.append('Una compra necesita el RUC del proveedor (11 dígitos): llénelo en la columna RUC/DNI o elíjalo en la previsualización.')
        if f.clase == 'VENTA' and f.tipo == '01' and f.operacion == '01' and not f.ruc:
            f.observaciones.append('Factura sin RUC del cliente: se registrará con el cliente genérico "VARIOS (importación)".')
        if f.ruc and f.operacion not in DEVOLUCIONES and not e:
            rol = 'proveedor' if f.clase == 'COMPRA' else 'cliente'
            tercero = terceros.get((_tipo_identidad(f.ruc), f.ruc))
            if not tercero:
                f.observaciones.append(f'Se registrará el {rol} {f.ruc}.')
            elif not (tercero.es_proveedor if rol == 'proveedor' else tercero.es_cliente):
                f.observaciones.append(f'{tercero.razon_social} se marcará también como {rol}.')
        if f.naturaleza == 'SALIDA' and f.cantidad > CERO and f.costo_unitario == CERO:
            f.observaciones.append('Costo 0 en el Excel: se valoriza con el costo promedio del sistema.')
        if f.clase == 'VENTA' and f.operacion == '01' and f.precio_unitario is None:
            f.observaciones.append('Sin precio de venta: entra a costo y no suma ingresos en el dashboard.')
    return productos, periodos, tipos


def _agrupar(filas, ruc_empresa):
    grupos = defaultdict(list)
    for f in filas:
        if f.tipo and f.serie and f.numero != '0' and f.operacion:
            grupos[_clave_comprobante(f, ruc_empresa)].append(f)
    for lineas in grupos.values():
        problemas = []
        if len({l.fecha for l in lineas if l.fecha}) > 1:
            problemas.append('El mismo comprobante aparece con fechas distintas.')
        if len({l.operacion for l in lineas}) > 1:
            problemas.append('El mismo comprobante mezcla tipos de operación distintos.')
        if len({l.ruc for l in lineas}) > 1:
            problemas.append('El mismo comprobante aparece con RUC/DNI distintos.')
        if len({l.moneda for l in lineas}) > 1:
            problemas.append('El mismo comprobante aparece con monedas distintas.')
        for l in lineas:
            l.errores.extend(problemas)
    # Una compra con el mismo número y fecha pero RUC distinto suele ser un RUC mal escrito en
    # uno de los archivos: se bloquea en vez de partir la factura en dos.
    compras = defaultdict(set)
    for (ruc, tipo, serie, numero), lineas in grupos.items():
        if lineas[0].clase == 'COMPRA' and ruc:
            compras[(tipo, serie, numero, lineas[0].fecha)].add(ruc)
    for (ruc, tipo, serie, numero), lineas in grupos.items():
        rucs = compras.get((tipo, serie, numero, lineas[0].fecha), set())
        if lineas[0].clase == 'COMPRA' and len(rucs) > 1:
            for l in lineas:
                l.errores.append(f'La compra {serie}-{numero} del mismo día aparece con RUC distintos ({", ".join(sorted(rucs))}). Revise el RUC.')
    return grupos


def _existentes(empresa_id, claves):
    if not claves:
        return {}
    docs = (
        Documento.objects.filter(empresa_id=empresa_id, serie_normalizada__in={c[2] for c in claves})
        .exclude(estado='ANULADO', importacion_lote__isnull=False)
        .select_related('tipo_comprobante', 'periodo', 'tercero', 'importacion_lote')
        .prefetch_related(
            Prefetch('detalles', queryset=DocumentoDetalle.objects.filter(revertida_en__isnull=True).order_by('linea')),
            Prefetch('pagos', queryset=PagoDocumento.objects.filter(estado='VIGENTE'), to_attr='pagos_vigentes'),
        )
    )
    resultado = {}
    for d in docs:
        clave = (d.ruc_emisor, d.tipo_comprobante.codigo_sunat, d.serie_normalizada, d.numero_normalizado)
        if clave in claves:
            resultado[clave] = d
    return resultado


def _emparejar_devoluciones(grupos, productos, empresa_id):
    """
    Cada nota de crédito necesita su comprobante de origen: una venta (o compra) del mismo producto
    ANTERIOR a la nota (fecha menor, o el mismo día pero más arriba en el mismo archivo).
    1) Misma cantidad, la más reciente: en el Excel y luego en lo ya registrado.
    2) Si no hay, la más reciente con cantidad suficiente (origen aproximado, queda observado).
    En cada línea de la nota queda `origen`: ('EXCEL', clave, índice) o ('SISTEMA', id del detalle).
    """
    disponible = {}
    candidatos = defaultdict(list)
    for clave, lineas in grupos.items():
        for i, l in enumerate(lineas):
            if l.operacion in ('01', '02') and l.fecha and not l.errores:
                candidatos[(l.clase, l.codigo)].append((l.fecha, l.archivo, l.fila, clave, i, l))
                disponible[('EXCEL', clave, i)] = l.cantidad
    usados_sistema = defaultdict(lambda: CERO)

    def anterior(c, nota):
        return c[0] < nota.fecha or (c[0] == nota.fecha and c[1] == nota.archivo and c[2] < nota.fila)

    def del_excel(nota, exacta):
        opciones = [
            c for c in candidatos[(nota.clase, nota.codigo)]
            if anterior(c, nota) and (disponible[('EXCEL', c[3], c[4])] == nota.cantidad if exacta
                                      else disponible[('EXCEL', c[3], c[4])] >= nota.cantidad)
        ]
        return max(opciones, key=lambda c: (c[0], c[2]), default=None)

    def del_sistema(nota, exacta):
        producto = productos.get(nota.codigo)
        if not producto:
            return None
        qs = DocumentoDetalle.objects.filter(
            documento__empresa_id=empresa_id, documento__clase=nota.clase, documento__estado='CONFIRMADO',
            documento__tipo_comprobante__es_nota=False, documento__fecha_emision__lte=nota.fecha, producto=producto,
            revertida_en__isnull=True,
        ).select_related('documento__tipo_comprobante').order_by('-documento__fecha_emision', '-id')
        qs = qs.filter(cantidad_original=nota.cantidad) if exacta else qs.filter(cantidad_original__gte=nota.cantidad)
        for detalle in qs[:50]:
            if detalle.cantidad_original - usados_sistema[detalle.id] >= nota.cantidad:
                return detalle
        return None

    origenes = {}
    for clave, lineas in grupos.items():
        if lineas[0].operacion not in DEVOLUCIONES:
            continue
        destinos = set()
        aproximado = False
        for l in lineas:
            if l.errores or not l.fecha:
                continue
            encontrado = None
            for exacta in (True, False):
                c = del_excel(l, exacta)
                if c:
                    disponible[('EXCEL', c[3], c[4])] -= l.cantidad
                    l.origen = ('EXCEL', c[3], c[4])
                    destinos.add(('EXCEL', c[3], c[0], c[5].naturaleza))
                    encontrado = True
                    break
                detalle = del_sistema(l, exacta)
                if detalle:
                    d = detalle.documento
                    usados_sistema[detalle.id] += l.cantidad
                    l.origen = ('SISTEMA', detalle.id)
                    destinos.add(('SISTEMA', (d.ruc_emisor, d.tipo_comprobante.codigo_sunat, d.serie_normalizada, d.numero_normalizado), d.fecha_emision, None))
                    encontrado = True
                    break
            if not encontrado:
                l.errores.append(
                    f'Devolución sin comprobante de origen: no hay una {"venta" if l.clase == "VENTA" else "compra"} '
                    f'anterior de {l.codigo} por {l.cantidad} o más.'
                )
            elif not exacta:
                aproximado = True
        if len(destinos) > 1:
            for l in lineas:
                l.errores.append('Las líneas de la nota de crédito corresponden a comprobantes de origen distintos.')
        elif destinos:
            fuente, origen, fecha_origen, naturaleza_origen = destinos.pop()
            origenes[clave] = {
                'fuente': fuente, 'comprobante': f'{origen[2]}-{origen[3]}', 'tipo': origen[1],
                'aproximado': aproximado, '_clave': origen,
                '_mismo_dia_salida': fecha_origen == lineas[0].fecha and naturaleza_origen == 'SALIDA',
            }
            if aproximado:
                for l in lineas:
                    l.observaciones.append(
                        f'Origen aproximado: no hay un comprobante anterior por la misma cantidad; se asocia a '
                        f'{origen[2]}-{origen[3]} (cantidad suficiente). Revíselo.'
                    )
            if lineas[0].serie[:1] != origen[2][:1]:
                for l in lineas:
                    l.observaciones.append(f'La nota {l.serie} devuelve el comprobante {origen[2]}-{origen[3]} de otra serie.')
    return origenes


def _texto_decimal(valor):
    return None if valor is None else format(valor, 'f')


def _orden(lineas, origen=None):
    """Por fecha; el mismo día primero las entradas (más stock disponible), luego las salidas. Una nota
    cuyo origen es una salida del mismo día va al final, después de su origen."""
    primera = lineas[0]
    if origen and origen.get('_mismo_dia_salida'):
        rango = 2
    else:
        rango = 0 if primera.naturaleza == 'ENTRADA' else 1
    return (primera.fecha or date.max, rango, primera.serie, primera.numero.zfill(12))


def _cantidad(valor):
    return format(valor.normalize(), 'f') if valor else '0'


def _simular_stock(ordenados, existentes, productos, empresa_id, planes=None):
    """
    Recorre en orden los comprobantes que se van a grabar y marca como error la salida que dejaría
    el stock en negativo, para verlo en la previsualización y no recién al confirmar. Parte del stock
    registrado antes de la primera fecha del Excel y suma los movimientos ya registrados después.
    De un comprobante a completar solo cuentan las líneas que se le agregarán.
    """
    from django.db.models import Case, DecimalField, F, Sum, When
    from apps.kardex.models import Movimiento

    planes = planes or {}
    pendientes = []
    for c, ls in ordenados:
        if any(l.errores for l in ls):
            continue
        if c not in existentes:
            pendientes.append((c, ls))
        elif planes.get(c, {}).get('estado') == 'COMPLETAR':
            pendientes.append((c, planes[c]['agregar']))
    primeras = {}
    for _, lineas in pendientes:
        for l in lineas:
            pid = productos[l.codigo].id
            primeras[pid] = min(primeras.get(pid, l.fecha), l.fecha)
    if not primeras:
        return

    # El Kardex se recalcula desde la fecha más antigua del Excel: si después hay movimientos del
    # producto en un período cerrado, el recálculo no se permite.
    cerrados = defaultdict(set)
    for pid, anio, mes, fecha in Movimiento.objects.filter(
        empresa_id=empresa_id, producto_id__in=primeras, periodo__estado='CERRADO',
    ).values_list('producto_id', 'periodo__anio', 'periodo__mes', 'fecha_movimiento'):
        if fecha >= primeras[pid]:
            cerrados[pid].add(f'{anio}-{mes:02d}')
    if cerrados:
        for _, lineas in pendientes:
            for l in lineas:
                pid = productos[l.codigo].id
                if pid in cerrados:
                    l.errores.append(
                        f'{l.codigo} tiene movimientos posteriores en períodos cerrados ({", ".join(sorted(cerrados[pid]))}): '
                        'el Kardex no se puede recalcular. Reabra esos períodos.'
                    )
        pendientes = [(c, ls) for c, ls in pendientes if not any(l.errores for l in ls)]
    efecto = Case(
        When(naturaleza='ENTRADA', then=F('cantidad_base')),
        When(naturaleza='SALIDA', then=-F('cantidad_base')),
        default=CERO, output_field=DecimalField(max_digits=20, decimal_places=8),
    )
    stock = {}
    posteriores = defaultdict(list)
    for pid, desde in primeras.items():
        movs = Movimiento.objects.filter(empresa_id=empresa_id, producto_id=pid)
        stock[pid] = movs.filter(fecha_movimiento__lt=desde).aggregate(t=Sum(efecto))['t'] or CERO
        posteriores[pid] = list(
            movs.filter(fecha_movimiento__gte=desde).values_list('fecha_movimiento').annotate(t=Sum(efecto)).order_by('fecha_movimiento')
        )

    def avanzar(pid, fecha):
        while posteriores[pid] and posteriores[pid][0][0] <= fecha:
            stock[pid] += posteriores[pid].pop(0)[1] or CERO

    for _, lineas in pendientes:
        cambios = defaultdict(lambda: CERO)
        for l in lineas:
            cambios[productos[l.codigo].id] += l.cantidad if l.naturaleza == 'ENTRADA' else -l.cantidad
        faltantes = []
        for pid, delta in cambios.items():
            avanzar(pid, lineas[0].fecha)
            if stock[pid] + delta < CERO:
                codigo = next(l.codigo for l in lineas if productos[l.codigo].id == pid)
                faltantes.append(f'Stock insuficiente de {codigo}: hay {_cantidad(stock[pid])} y sale {_cantidad(-delta)}. '
                                 'Revise el saldo inicial o las compras anteriores.')
        if faltantes:
            for l in lineas:
                l.errores.extend(faltantes)
            continue
        for pid, delta in cambios.items():
            stock[pid] += delta


def _costo_registrado(detalle, clase):
    if detalle.costo_unitario_importado is not None:
        return detalle.costo_unitario_importado
    if clase == 'COMPRA':
        return detalle.precio_unitario
    return None


def _identificacion(tercero):
    return (tercero.numero_documento or '').strip() if tercero else ''


def motivo_no_completable(existente, lineas):
    """Por qué no se le pueden agregar líneas a un comprobante ya registrado (None si se puede)."""
    primera = lineas[0]
    if existente.estado != 'CONFIRMADO':
        return f'El comprobante ya existe en estado {existente.estado}: solo se completan comprobantes confirmados.'
    if existente.origen_captura != 'IMPORTACION' or existente.importacion_lote_id is None:
        return 'El comprobante ya existe y no fue importado por Excel: agregue la línea manualmente.'
    if existente.importacion_lote.estado != 'CONFIRMADO':
        return 'El lote que importó el comprobante está anulado.'
    if existente.tipo_comprobante.es_nota or any(l.operacion in DEVOLUCIONES for l in lineas):
        return 'Las notas de crédito no se completan: anule la nota y vuelva a importarla completa.'
    diferencias = []
    if existente.clase != primera.clase:
        diferencias.append('clase')
    if existente.fecha_emision != primera.fecha:
        diferencias.append(f'fecha (registrada {existente.fecha_emision:%d/%m/%Y})')
    if existente.moneda_codigo_id != primera.moneda:
        diferencias.append(f'moneda (registrada {existente.moneda_codigo_id})')
    if primera.clase == 'VENTA' and primera.ruc and _identificacion(existente.tercero) not in ('', primera.ruc):
        diferencias.append(f'cliente (registrado {_identificacion(existente.tercero)})')
    if diferencias:
        return f'La cabecera no coincide con la registrada: {", ".join(diferencias)}.'
    if existente.periodo.estado != 'ABIERTO':
        return f'El período {existente.periodo.anio}-{existente.periodo.mes:02d} del comprobante está cerrado.'
    if getattr(existente, 'pagos_vigentes', None) is None:
        tiene_pagos = existente.pagos.filter(estado='VIGENTE').exists()
    else:
        tiene_pagos = bool(existente.pagos_vigentes)
    if tiene_pagos:
        return 'El comprobante tiene cobros o pagos aplicados: anúlelos antes de completarlo.'
    return None


def comparar_con_registrado(existente, lineas, productos):
    """
    Compara las líneas del Excel con las vigentes del comprobante registrado.
    - Mismo producto, cantidad y costo → ya está (se omite).
    - Mismo producto con otra cantidad o costo → CONFLICTO: el Excel no identifica qué línea es.
    - Producto que no está → se agregará (COMPLETAR), si el comprobante admite completarse.
    Devuelve {'estado', 'agregar': [FilaKardex], 'mensaje'}.
    """
    if existente.estado == 'ANULADO':
        return {'estado': 'CONFLICTO', 'agregar': [],
                'mensaje': 'Existe un comprobante ANULADO con este número: el sistema no permite reutilizarlo.'}
    registradas = defaultdict(list)
    for d in existente.detalles.all():
        if d.revertida_en is None:
            registradas[d.producto_id].append(d)
    agregar, diferentes = [], []
    for l in lineas:
        pid = productos[l.codigo].id
        if pid not in registradas:
            agregar.append(l)
            continue
        candidatas = registradas[pid]
        igual = next((
            d for d in candidatas
            if d.cantidad_original == l.cantidad and (
                _costo_registrado(d, existente.clase) is None
                or abs(_costo_registrado(d, existente.clase) - l.costo_unitario) <= TOLERANCIA_COSTO
            )
        ), None)
        if igual is not None:
            candidatas.remove(igual)
            continue
        if candidatas:
            d = candidatas[0]
            costo = _costo_registrado(d, existente.clase)
            diferentes.append(
                f'{l.codigo}: el Excel trae {_cantidad(l.cantidad)} a {_texto_costo(l.costo_unitario)} y está registrado '
                f'{_cantidad(d.cantidad_original or CERO)}' + (f' a {_texto_costo(costo)}' if costo is not None else '')
            )
        else:
            diferentes.append(f'{l.codigo}: el Excel trae más líneas de este producto que las registradas')
    if diferentes:
        return {'estado': 'CONFLICTO', 'agregar': [], 'mensaje': (
            'El comprobante ya está registrado con el mismo producto pero otra cantidad o costo, y el Excel no '
            f'identifica la línea. Revíselo: {"; ".join(diferentes)}.'
        )}
    if not agregar:
        return {'estado': 'YA_EXISTE', 'agregar': [],
                'mensaje': 'Ya está registrado con estos productos: se omite, no se sobrescribe.'}
    motivo = motivo_no_completable(existente, lineas)
    if motivo:
        faltan = ', '.join(sorted({l.codigo for l in agregar}))
        return {'estado': 'CONFLICTO', 'agregar': [],
                'mensaje': f'Al comprobante registrado le faltan los productos {faltan}, pero no se puede completar. {motivo}'}
    return {'estado': 'COMPLETAR', 'agregar': agregar, 'mensaje': 'Se agregará: ' + '; '.join(
        f'{l.codigo} × {_cantidad(l.cantidad)} a {_texto_costo(l.costo_unitario)}' for l in agregar
    ) + f' (al comprobante del lote {existente.importacion_lote_id}).'}


def _texto_costo(valor):
    return format(valor.quantize(Decimal('0.01')), 'f') if valor is not None else '—'


def _analizar(*, empresa_id, archivos, proveedores=None):
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

    _aplicar_proveedores(filas, proveedores)
    productos, periodos, tipos = _validar_contexto(filas, empresa_id)
    grupos = _agrupar(filas, empresa.ruc)
    origenes = _emparejar_devoluciones(grupos, productos, empresa_id)
    existentes = _existentes(empresa_id, set(grupos))

    ordenados = sorted(grupos.items(), key=lambda g: _orden(g[1], origenes.get(g[0])))
    planes = {
        clave: comparar_con_registrado(existentes[clave], lineas, productos)
        for clave, lineas in ordenados
        if clave in existentes and not any(l.errores for l in lineas)
    }
    _simular_stock(ordenados, existentes, productos, empresa_id, planes)
    comprobantes = []
    estados = {}
    for clave, lineas in ordenados:
        primera = lineas[0]
        errores = sorted({m for l in lineas for m in l.errores})
        plan = planes.get(clave)
        if errores:
            estado, mensaje = 'ERROR', '; '.join(errores)
        elif plan:
            estado, mensaje = plan['estado'], plan['mensaje']
        else:
            estado, mensaje = 'NUEVO', ''
        estados[clave] = estado
        agregar = plan['agregar'] if plan and estado == 'COMPLETAR' else []
        origen = origenes.get(clave)
        sin_proveedor = primera.clase == 'COMPRA' and len(primera.ruc) != 11
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
            'origen': {k: v for k, v in origen.items() if not k.startswith('_')} if origen else None,
            'requiere_proveedor': sin_proveedor,
            'clave_proveedor': clave_proveedor(primera) if sin_proveedor else None,
            'estado': estado,
            'mensaje': mensaje,
            'observaciones': sorted({m for l in lineas for m in l.observaciones}),
            'completa_lote': existentes[clave].importacion_lote_id if estado == 'COMPLETAR' else None,
            'agregar': [{
                'archivo': l.archivo, 'fila': l.fila, 'codigo': l.codigo, 'cantidad': _texto_decimal(l.cantidad),
                'costo_unitario': _texto_decimal(l.costo_unitario), 'costo_total': _texto_decimal(l.costo_total),
                'precio_unitario': _texto_decimal(l.precio_unitario),
            } for l in agregar],
        })
        for l in lineas:
            if l.errores:
                l.estado = 'ERROR'
            elif estado == 'COMPLETAR':
                l.estado = 'COMPLETAR' if any(l is a for a in agregar) else 'YA_EXISTE'
            else:
                l.estado = estado
            if estado == 'ERROR' and not l.errores:
                l.errores.append('Otra línea del mismo comprobante tiene error.')

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
    observados = sum(1 for c in comprobantes if c['observaciones'])
    sin_proveedor_total = sum(1 for c in comprobantes if c['requiere_proveedor'])
    fechas = [f.fecha for f in filas if f.fecha]
    periodos_detectados = sorted({f'{f.fecha:%Y-%m}' for f in filas if f.fecha})
    contadores = {
        'todos': len(comprobantes),
        'nuevos': contar('NUEVO'),
        'a_completar': contar('COMPLETAR'),
        'ya_existen': contar('YA_EXISTE'),
        'errores': contar('ERROR'),
        'conflictos': contar('CONFLICTO'),
        'sin_proveedor': sin_proveedor_total,
        'observaciones': observados,
    }
    resultado = {
        'formato': 'ENTRADAS_SALIDAS',
        'resumen': {
            'archivos': len(archivos),
            'filas': len(filas),
            'total_filas': len(filas),
            'filas_con_error': sum(1 for f in detalle_filas if f['estado'] == 'ERROR'),
            'filas_con_observacion': sum(1 for f in detalle_filas if f['observaciones']),
            'comprobantes': len(comprobantes),
            'total_comprobantes': len(comprobantes),
            'nuevos': contar('NUEVO'),
            'completar': contar('COMPLETAR'),
            'a_completar': contar('COMPLETAR'),
            'lineas_a_agregar': sum(len(c['agregar']) for c in comprobantes),
            'ya_existen': contar('YA_EXISTE'),
            'conflictos': contar('CONFLICTO'),
            'con_error': contar('ERROR'),
            'errores': contar('ERROR'),
            'requieren_proveedor': sin_proveedor_total,
            'sin_proveedor': sin_proveedor_total,
            'observaciones': observados,
            'periodos_detectados': periodos_detectados,
            'productos': len({f.codigo for f in filas if f.codigo}),
            'desde': min(fechas).isoformat() if fechas else None,
            'hasta': max(fechas).isoformat() if fechas else None,
            'limite_lote': MAX_COMPROBANTES_LOTE,
            'excede_limite': contar('NUEVO') + contar('COMPLETAR') > MAX_COMPROBANTES_LOTE,
            'puede_confirmar': (
                0 < contar('NUEVO') + contar('COMPLETAR') <= MAX_COMPROBANTES_LOTE
                and contar('ERROR') == 0 and contar('CONFLICTO') == 0
            ),
        },
        'contadores': contadores,
        'comprobantes': comprobantes,
        'filas': detalle_filas,
    }
    contexto = {
        'empresa': empresa, 'ordenados': ordenados, 'estados': estados, 'origenes': origenes,
        'productos': productos, 'periodos': periodos, 'tipos': tipos, 'existentes': existentes,
        'planes': planes,
    }
    return resultado, contexto


def previsualizar_importacion_kardex(*, empresa_id: int, archivos, proveedores=None) -> dict:
    """archivos: lista de (nombre, archivo). Devuelve el diagnóstico sin escribir nada."""
    return _analizar(empresa_id=empresa_id, archivos=archivos, proveedores=proveedores)[0]


def generar_plantilla_entradas_salidas(empresa_id: int):
    """Plantilla .xlsx con el mismo formato del Kardex por producto del cliente + columnas opcionales."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from apps.reportes.excel_seguro import neutralizar_formulas

    azul = PatternFill('solid', fgColor='17365D')
    gris = PatternFill('solid', fgColor='E5E7EB')
    blanco = Font(bold=True, color='FFFFFF')
    centro = Alignment(horizontal='center', vertical='center', wrap_text=True)

    libro = Workbook()
    hoja = libro.active
    hoja.title = 'Entradas_y_salidas'
    hoja.append(['Código', 'COMPROBANTE', None, None, None, 'Tipo de Operación', 'ENTRADAS', None, None, 'SALIDAS', None, None,
                 'OPCIONALES', None, None, None])
    hoja.append([None, 'Fecha', 'Tipo', 'Serie', 'Número', None, 'Cantidad', 'Costo Unitario', 'Costo Total',
                 'Cantidad', 'Costo Unitario', 'Costo Total', 'RUC/DNI', 'Razón social', 'Precio unitario', 'Moneda'])
    for rango in ('A1:A2', 'B1:E1', 'F1:F2', 'G1:I1', 'J1:L1', 'M1:P1'):
        hoja.merge_cells(rango)
    for fila in hoja.iter_rows(min_row=1, max_row=2):
        for celda in fila:
            celda.fill = gris if celda.column > 12 else azul
            celda.font = Font(bold=True) if celda.column > 12 else blanco
            celda.alignment = centro
    ejemplos = [
        ['P-001', date(2026, 1, 5), 1, 'F001', 120, '02 Compra', 20, 10.5, 210, 0, 0, 0, '20100100100', 'PROVEEDOR EJEMPLO SAC', None, 'PEN'],
        ['P-001', date(2026, 1, 8), 3, 'B001', 455, '01 Venta', 0, 0, 0, 2, 10.5, 21, None, None, 15, 'PEN'],
        ['P-001', date(2026, 1, 9), 1, 'F001', 88, '01 Venta', 0, 0, 0, 1, 10.5, 10.5, '20600600600', 'CLIENTE EJEMPLO SAC', 16, 'PEN'],
        ['P-001', date(2026, 1, 9), 7, 'FC01', 3, '05 Devolución Recibida', 1, 0, 0, 0, 0, 0, None, None, None, 'PEN'],
    ]
    for fila in ejemplos:
        hoja.append(fila)
    for fila in hoja.iter_rows(min_row=3, min_col=2, max_col=2):
        for celda in fila:
            celda.number_format = 'DD/MM/YYYY'
    for col, ancho in zip('ABCDEFGHIJKLMNOP', (12, 12, 6, 8, 10, 24, 10, 14, 14, 10, 14, 14, 14, 30, 14, 8)):
        hoja.column_dimensions[col].width = ancho
    hoja.freeze_panes = 'A3'

    ayuda = libro.create_sheet('Instrucciones')
    for linea in (
        ['Cómo llenar la plantilla "Entradas y salidas"'],
        [],
        ['Una fila = una línea de comprobante. Si un comprobante tiene varios productos, repita fecha, tipo, serie y número.'],
        ['Tipo: 1 Factura, 3 Boleta, 7 Nota de crédito.'],
        ['Tipo de operación: 01 Venta, 02 Compra, 05 Devolución recibida, 06 Devolución entregada.'],
        ['Entradas (compras y devoluciones recibidas): cantidad y costo unitario sin IGV. Salidas: solo cantidad (el costo lo calcula el sistema).'],
        ['RUC/DNI: obligatorio en compras (o elíjalo en la previsualización). En facturas de venta sin RUC se usa "VARIOS (importación)".'],
        ['Precio unitario: precio de venta sin IGV. Si se deja vacío la venta entra a costo y no suma ingresos.'],
        ['Moneda: PEN o USD (el tipo de cambio se toma de la fecha). Vacío = PEN.'],
        ['Puede subir varios archivos a la vez (uno por producto). Las filas de ejemplo deben borrarse.'],
    ):
        ayuda.append(linea)
    ayuda['A1'].font = Font(bold=True, size=12)
    ayuda.column_dimensions['A'].width = 120

    catalogo = libro.create_sheet('Productos')
    catalogo.append(['Código', 'Descripción'])
    for celda in catalogo[1]:
        celda.font = Font(bold=True)
    for codigo, descripcion in Producto.objects.filter(empresa_id=empresa_id, estado='ACTIVO').order_by('codigo_interno').values_list('codigo_interno', 'descripcion'):
        catalogo.append([codigo, descripcion])
    catalogo.column_dimensions['A'].width = 14
    catalogo.column_dimensions['B'].width = 60

    neutralizar_formulas(libro)
    salida = io.BytesIO()
    libro.save(salida)
    salida.seek(0)
    return salida
