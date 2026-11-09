"""
Bloque 17D — importación del Padrón Reducido del RUC (SUNAT) a PostgreSQL.

Fuente oficial: https://www.sunat.gob.pe/descargaPRR/mrc137_padron_reducido.html
(enlace "padrón_reducido_RUC.zip" → http://www2.sunat.gob.pe/padron_reducido_ruc.zip).

Formato REAL verificado el 31/10/2026 sobre el ZIP oficial "Actualizado al 31/10/2026"
(padron_reducido_ruc.zip, 394.484.786 bytes, sha256 f4b85f5c…a46dd0):
- Un único archivo interno `padron_reducido_ruc.txt` (1.579.804.683 bytes, deflate).
- Codificación Windows-1252 (compatible con ISO-8859-1 en las letras con tilde; 2.711 filas usan
  caracteres propios de cp1252 como ’ – Š y 5 filas traen bytes 0x81/0x8D, indefinidos en cp1252,
  que se decodifican como U+FFFD).
- Filas terminadas en LF (sin CR); separador `|` y un `|` final en cada fila (16 trozos por fila).
- Un `|` dentro de un valor viene escapado como `\\|` (5 filas, p. ej. "EBEN EZER \\| INGENIERIA").
- 18.501.026 filas de datos; 0 RUC repetidos; 32 RUC inválidos (27 con prefijo 00, 4 con dígito
  verificador errado y 1 "AAAAAAAAAAA"); 1 fila sin razón social.
- Encabezado (15 columnas):

    RUC|NOMBRE O RAZÓN SOCIAL|ESTADO DEL CONTRIBUYENTE|CONDICIÓN DE DOMICILIO|UBIGEO|TIPO DE VÍA|
    NOMBRE DE VÍA|CÓDIGO DE ZONA|TIPO DE ZONA|NÚMERO|INTERIOR|LOTE|DEPARTAMENTO|MANZANA|KILÓMETRO|

- Vacíos como "-" (y "----" en tipo de vía/zona). UBIGEO: 2.728.863 filas con 6 dígitos, el resto "-".
  "CÓDIGO DE ZONA" trae el tipo de zona (URB., A.H., C.H.…) y "TIPO DE ZONA" su nombre.
  "DEPARTAMENTO" es el número de departamento/piso del domicilio, NO el departamento geográfico:
  el padrón no trae nombres de departamento/provincia/distrito.

Nada de eso se da por supuesto en el código: la codificación y el separador se detectan desde el
encabezado y las columnas se ubican por NOMBRE (no por posición).

Reglas:
- Nunca se extrae nada a disco: el TXT se lee en streaming desde el ZIP (sin ZIP Slip posible) y
  aun así se rechazan entradas con rutas peligrosas o contenido inesperado.
- Se procesa por lotes (COPY a una tabla temporal + INSERT ... ON CONFLICT DO NOTHING): la memoria
  usada no depende del tamaño del padrón y los RUC repetidos se cuentan como duplicados.
- Actualización segura: la versión nueva se carga aparte (CARGANDO) y solo se activa al terminar
  y validarse. Si algo falla, queda FALLIDA y la versión ACTIVA anterior sigue respondiendo.
- Retención: al activar la nueva, la anterior queda RETIRADA CON sus filas, para que una consulta
  que ya había tomado esa versión termine bien. Sus filas se borran después, de forma controlada,
  cuando lleva retirada más de RETENCION_MINUTOS (al inicio de la siguiente importación o con
  `manage.py limpiar_padrones_ruc`). Así nunca hay más de dos versiones con filas en reposo.
- Una sola importación a la vez: candado de PostgreSQL (pg_try_advisory_lock), compartido por
  todas las conexiones/procesos/servidores que usan la misma base.
"""
import hashlib
import os
import re
import time
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.documentos.reglas_tributarias import ubigeo_valido
from apps.inventario.documentos_identidad import es_ruc_valido

from .models import PadronRuc, VersionPadronRuc
from .schemas import texto

FUENTE_OFICIAL = 'https://www.sunat.gob.pe/descargaPRR/mrc137_padron_reducido.html'
NOMBRE_FUENTE = 'Padrón Reducido SUNAT'
ZONA_SUNAT = ZoneInfo('America/Lima')
EXTENSIONES_DATOS = ('.txt', '.csv')
SEPARADORES = ('|', ';', '\t', ',')
LOTE_POR_DEFECTO = 20000
CANDADO_IMPORTACION = 1717_0017  # pg_advisory_lock: una sola importación a la vez
RETENCION_MINUTOS = 10  # cuánto se conservan las filas de la versión recién retirada

# Columnas por nombre normalizado (sin tildes, mayúsculas, espacios simples).
COL_RUC, COL_NOMBRE, COL_ESTADO, COL_CONDICION, COL_UBIGEO = (
    'RUC', 'NOMBRE O RAZON SOCIAL', 'ESTADO DEL CONTRIBUYENTE', 'CONDICION DE DOMICILIO', 'UBIGEO')
REQUERIDAS = (COL_RUC, COL_NOMBRE, COL_ESTADO, COL_CONDICION, COL_UBIGEO)
# Partes del domicilio, en el orden en que se arma el texto, con su prefijo. Los prefijos son los
# abreviados usuales de SUNAT; los valores se copian tal cual vienen (no se deduce nada).
PARTES_DOMICILIO = (
    ('TIPO DE VIA', ''), ('NOMBRE DE VIA', ''), ('NUMERO', 'NRO. '), ('KILOMETRO', 'KM. '), ('MANZANA', 'MZA. '),
    ('LOTE', 'LOTE. '), ('DEPARTAMENTO', 'DPTO. '), ('INTERIOR', 'INT. '), ('CODIGO DE ZONA', ''), ('TIPO DE ZONA', ''),
)

LARGO = {f.name: f.max_length for f in PadronRuc._meta.fields if getattr(f, 'max_length', None)}


class ErrorImportacion(Exception):
    """Error controlado de la importación (mensaje apto para la consola, sin trazas)."""


def normalizar_columna(nombre):
    sin_tildes = unicodedata.normalize('NFKD', nombre).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', sin_tildes).strip().upper()


# ---- ZIP ------------------------------------------------------------------------------------------
def _nombre_seguro(nombre):
    if not nombre or '\x00' in nombre or '\\' in nombre or re.match(r'^[A-Za-z]:', nombre):
        return False
    ruta = PurePosixPath(nombre)
    return not ruta.is_absolute() and '..' not in ruta.parts


def abrir_zip(ruta, *, max_bytes=None, max_ratio=None):
    """
    (ZipFile, ZipInfo del archivo de datos). Valida existencia, que sea ZIP, nombres seguros (sin
    ZIP Slip), un único archivo de datos .txt/.csv y límites contra ZIP bomb.
    """
    max_bytes = max_bytes or getattr(settings, 'PADRON_RUC_MAX_BYTES', 8 * 1024 ** 3)
    max_ratio = max_ratio or getattr(settings, 'PADRON_RUC_MAX_RATIO', 50)
    if not os.path.isfile(ruta):
        raise ErrorImportacion(f'El archivo no existe: {os.path.basename(str(ruta))}')
    if not zipfile.is_zipfile(ruta):
        raise ErrorImportacion('El archivo no es un ZIP válido.')
    try:
        zf = zipfile.ZipFile(ruta)
        entradas = zf.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise ErrorImportacion(f'ZIP dañado o ilegible ({type(exc).__name__}).') from None
    for e in entradas:
        if not _nombre_seguro(e.filename):
            zf.close()
            raise ErrorImportacion('El ZIP contiene rutas no permitidas (posible ZIP Slip); no se importa.')
    archivos = [e for e in entradas if not e.is_dir()]
    datos = [e for e in archivos if e.filename.lower().endswith(EXTENSIONES_DATOS)]
    otros = [e for e in archivos if e not in datos]
    if len(datos) != 1 or otros:
        zf.close()
        nombres = ', '.join(e.filename[:60] for e in archivos[:5]) or '(vacío)'
        raise ErrorImportacion(f'Contenido inesperado: se esperaba un único archivo .txt/.csv y hay: {nombres}.')
    info = datos[0]
    if info.flag_bits & 0x1:
        zf.close()
        raise ErrorImportacion('El ZIP está cifrado; no se importa.')
    if info.file_size > max_bytes or (info.compress_size and info.file_size / info.compress_size > max_ratio):
        zf.close()
        raise ErrorImportacion('El archivo interno excede el tamaño o la tasa de compresión permitidos.')
    return zf, info


def fecha_de_entrada(info):
    """Fecha/hora del TXT dentro del ZIP (hora de Perú), o None si no es válida."""
    try:
        return datetime(*info.date_time, tzinfo=ZONA_SUNAT)
    except (TypeError, ValueError):
        return None


def sha256_archivo(ruta, bloque=1024 * 1024):
    h = hashlib.sha256()
    with open(ruta, 'rb') as f:
        for trozo in iter(lambda: f.read(bloque), b''):
            h.update(trozo)
    return h.hexdigest()


# ---- Formato --------------------------------------------------------------------------------------
@dataclass
class Formato:
    codificacion: str
    separador: str
    columnas: dict = field(default_factory=dict)   # nombre normalizado -> índice
    total_columnas: int = 0


def detectar_formato(encabezado: bytes, codificacion=None) -> Formato:
    """
    Codificación (UTF-8 si el encabezado lo es; si no Windows-1252, que es la del padrón oficial y
    cubre ISO-8859-1), separador y columnas por nombre.
    """
    if codificacion in (None, '', 'auto'):
        try:
            encabezado.decode('utf-8')
            codificacion = 'utf-8'
        except UnicodeDecodeError:
            codificacion = 'cp1252'
    try:
        texto_cab = encabezado.decode(codificacion).lstrip('\ufeff').rstrip('\r\n')
    except (UnicodeDecodeError, LookupError):
        raise ErrorImportacion(f'El encabezado no se puede leer con la codificación {codificacion!r}.') from None
    for sep in SEPARADORES:
        nombres = [normalizar_columna(n) for n in texto_cab.split(sep)]
        if all(r in nombres for r in REQUERIDAS):
            columnas = {}
            for i, n in enumerate(nombres):
                if n and n not in columnas:
                    columnas[n] = i
            return Formato(codificacion=codificacion, separador=sep, columnas=columnas,
                           total_columnas=len([n for n in nombres if n]))
    raise ErrorImportacion('Encabezado inesperado: no se encontraron las columnas del padrón reducido '
                           f"({', '.join(REQUERIDAS)}).")


# ---- Filas ----------------------------------------------------------------------------------------
def _corta(valor, campo):
    return valor[:LARGO[campo]] if valor else valor


def armar_domicilio(partes, columnas):
    """Domicilio fiscal a partir de las columnas de dirección del padrón (solo lo que viene)."""
    trozos = []
    for nombre, prefijo in PARTES_DOMICILIO:
        i = columnas.get(nombre)
        if i is None or i >= len(partes):
            continue
        valor = texto(partes[i])
        if valor and valor.strip('-'):  # '-' o '----' = sin dato
            trozos.append(f'{prefijo}{valor}')
    return ' '.join(trozos) or None


def separar(texto_fila, sep):
    """Divide la fila respetando el separador escapado (`\\|` dentro de un valor → `|`)."""
    escapado = '\\' + sep
    if escapado not in texto_fila:
        return texto_fila.split(sep)
    return [p.replace('\x00', sep) for p in texto_fila.replace(escapado, '\x00').split(sep)]


def interpretar_fila(linea: bytes, formato: Formato):
    """('ok', dict) | ('incompleta', None) | ('ruc_invalido', None) para una línea del TXT."""
    partes = separar(linea.decode(formato.codificacion, errors='replace').rstrip('\r\n'), formato.separador)
    if len(partes) < formato.total_columnas:
        return 'incompleta', None
    c = formato.columnas
    ruc = partes[c[COL_RUC]].strip()
    if not es_ruc_valido(ruc):
        return 'ruc_invalido', None
    razon_social = texto(partes[c[COL_NOMBRE]])
    if not razon_social:
        return 'incompleta', None
    ubigeo = texto(partes[c[COL_UBIGEO]])
    return 'ok', {
        'ruc': ruc,
        'razon_social': _corta(razon_social, 'razon_social'),
        'estado': _corta(texto(partes[c[COL_ESTADO]], mayusculas=True) or '', 'estado'),
        'condicion': _corta(texto(partes[c[COL_CONDICION]], mayusculas=True) or '', 'condicion'),
        'ubigeo': ubigeo if ubigeo and ubigeo_valido(ubigeo) else None,
        'domicilio_fiscal': _corta(armar_domicilio(partes, c), 'domicilio_fiscal'),
    }


# ---- Importación ----------------------------------------------------------------------------------
@dataclass
class Resumen:
    leidos: int = 0
    validos: int = 0
    omitidos: int = 0
    duplicados: int = 0
    incompletas: int = 0
    ruc_invalidos: int = 0
    segundos: float = 0.0


COLUMNAS_COPY = ('ruc', 'razon_social', 'estado', 'condicion', 'ubigeo', 'domicilio_fiscal')


def _cargar_lote(version_id, filas):
    """COPY del lote a una tabla temporal y alta en padron_ruc sin duplicar RUC. Devuelve insertados."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute('CREATE TEMP TABLE IF NOT EXISTS padron_ruc_lote ('
                    'ruc varchar(11), razon_social varchar(300), estado varchar(60), condicion varchar(60), '
                    'ubigeo varchar(6), domicilio_fiscal varchar(500))')
        cur.execute('TRUNCATE padron_ruc_lote')
        with cur.cursor.copy(f"COPY padron_ruc_lote ({', '.join(COLUMNAS_COPY)}) FROM STDIN") as copia:
            for fila in filas:
                copia.write_row([fila[k] for k in COLUMNAS_COPY])
        cur.execute(
            f"INSERT INTO padron_ruc (version_id, {', '.join(COLUMNAS_COPY)}) "
            f"SELECT %s, {', '.join(COLUMNAS_COPY)} FROM padron_ruc_lote "
            'ON CONFLICT (version_id, ruc) DO NOTHING', [version_id])
        return cur.rowcount


def _borrar_filas(version_ids):
    if version_ids:
        # Un solo DELETE (sin señales ni relaciones inversas: Django no carga las filas).
        PadronRuc.objects.filter(version_id__in=list(version_ids)).delete()


def limpiar_cargas_interrumpidas():
    """Una importación cortada (proceso muerto) deja una versión CARGANDO: se marca FALLIDA y se vacía."""
    colgadas = list(VersionPadronRuc.objects.filter(estado=VersionPadronRuc.CARGANDO).values_list('id', flat=True))
    if colgadas:
        _borrar_filas(colgadas)
        VersionPadronRuc.objects.filter(id__in=colgadas).update(
            estado=VersionPadronRuc.FALLIDA, error='Importación interrumpida.', finalizado_en=timezone.now())
    return len(colgadas)


def version_activa():
    return VersionPadronRuc.objects.filter(estado=VersionPadronRuc.ACTIVA).first()


def validar_version(version, resumen, *, minimo, proporcion_minima):
    """La versión nueva debe tener datos suficientes antes de reemplazar a la activa."""
    if resumen.validos < max(1, minimo):
        raise ErrorImportacion(f'La importación solo cargó {resumen.validos} registros válidos (mínimo {max(1, minimo)}).')
    activa = version_activa()
    if activa and proporcion_minima and resumen.validos < activa.registros_validos * proporcion_minima:
        raise ErrorImportacion(
            f'La versión nueva tiene {resumen.validos} registros y la activa {activa.registros_validos}: '
            'la caída es sospechosa (¿archivo truncado?). Use --permitir-reduccion si es correcta.')


def activar_version(version):
    """
    Activa `version` y retira la anterior en una sola transacción. La retirada CONSERVA sus filas:
    una consulta que ya había tomado esa versión (ProveedorPadronReducido la fija al empezar) puede
    terminar; las consultas nuevas leen la activa. Las filas se borran luego con
    `limpiar_versiones_retiradas`.
    """
    with transaction.atomic():
        anteriores = list(VersionPadronRuc.objects.select_for_update().filter(estado=VersionPadronRuc.ACTIVA)
                          .exclude(pk=version.pk).values_list('id', flat=True))
        VersionPadronRuc.objects.filter(id__in=anteriores).update(estado=VersionPadronRuc.RETIRADA)
        ahora = timezone.now()
        version.estado, version.activada_en, version.finalizado_en = VersionPadronRuc.ACTIVA, ahora, ahora
        version.save(update_fields=['estado', 'activada_en', 'finalizado_en'])
    return anteriores


def retirada_en(version):
    """Cuándo dejó de ser la activa: activación de la versión que la reemplazó (o None)."""
    return (VersionPadronRuc.objects.filter(id__gt=version.pk, activada_en__isnull=False)
            .order_by('activada_en').values_list('activada_en', flat=True).first())


def limpiar_versiones_retiradas(*, retencion_minutos=RETENCION_MINUTOS, ahora=None):
    """
    Borra las filas de las versiones RETIRADAS hace más de `retencion_minutos` (sus metadatos se
    conservan). Nunca toca la ACTIVA ni una retirada dentro del plazo. Un DELETE no bloquea las
    consultas (PostgreSQL MVCC); el espacio lo reutiliza autovacuum (no se ejecuta VACUUM FULL).
    Devuelve los ids de versión limpiados.
    """
    if not isinstance(retencion_minutos, int) or isinstance(retencion_minutos, bool) or retencion_minutos < 0:
        # Nunca se corrige en silencio: un negativo anularía la protección de retención.
        raise ValueError('retencion_minutos debe ser un entero mayor o igual a 0.')
    limite = (ahora or timezone.now()) - timedelta(minutes=retencion_minutos)
    limpiadas = []
    for version in VersionPadronRuc.objects.filter(estado=VersionPadronRuc.RETIRADA).order_by('id'):
        momento = retirada_en(version)
        if momento is None or momento > limite:
            continue
        if PadronRuc.objects.filter(version=version).exists():
            _borrar_filas([version.pk])
            limpiadas.append(version.pk)
    return limpiadas


def versiones_retiradas_con_filas():
    return [v for v in VersionPadronRuc.objects.filter(estado=VersionPadronRuc.RETIRADA).order_by('id')
            if PadronRuc.objects.filter(version=v).exists()]


def importar_padron(ruta, *, fuente=FUENTE_OFICIAL, lote=LOTE_POR_DEFECTO, codificacion=None, minimo=1,
                    proporcion_minima=0.5, limpiar_retiradas=True, progreso=None):
    """
    Importa el ZIP oficial como versión nueva y la activa si todo salió bien.
    Devuelve (version, resumen). Ante cualquier error deja la versión FALLIDA y lanza ErrorImportacion;
    la versión activa anterior no se toca. Antes de cargar borra las filas de versiones retiradas
    hace más de RETENCION_MINUTOS (salvo limpiar_retiradas=False), para no acumular versiones.
    """
    lote = max(100, int(lote))
    zf, info = abrir_zip(ruta)
    inicio = time.monotonic()
    with connection.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_lock(%s)', [CANDADO_IMPORTACION])
        if not cur.fetchone()[0]:
            zf.close()
            raise ErrorImportacion('Ya hay otra importación del padrón en curso.')
    version = None
    resumen = Resumen()
    try:
        limpiar_cargas_interrumpidas()
        if limpiar_retiradas:
            limpiar_versiones_retiradas()
        with zf.open(info) as flujo:
            formato = detectar_formato(flujo.readline(), codificacion)
            version = VersionPadronRuc.objects.create(
                fuente=fuente[:200], archivo=os.path.basename(str(ruta))[:255], archivo_interno=info.filename[:255],
                sha256=sha256_archivo(ruta), fecha_padron=fecha_de_entrada(info),
                codificacion=formato.codificacion, separador=formato.separador)
            pendientes = []
            for linea in flujo:
                if not linea.strip():
                    continue
                resumen.leidos += 1
                resultado, fila = interpretar_fila(linea, formato)
                if resultado == 'ok':
                    pendientes.append(fila)
                    if len(pendientes) >= lote:
                        insertados = _cargar_lote(version.pk, pendientes)
                        resumen.validos += insertados
                        resumen.duplicados += len(pendientes) - insertados
                        pendientes = []
                        if progreso:
                            progreso(resumen)
                elif resultado == 'incompleta':
                    resumen.incompletas += 1
                else:
                    resumen.ruc_invalidos += 1
            if pendientes:
                insertados = _cargar_lote(version.pk, pendientes)
                resumen.validos += insertados
                resumen.duplicados += len(pendientes) - insertados
        resumen.omitidos = resumen.incompletas + resumen.ruc_invalidos
        version.registros_leidos, version.registros_validos = resumen.leidos, resumen.validos
        version.registros_omitidos, version.registros_duplicados = resumen.omitidos, resumen.duplicados
        version.save(update_fields=['registros_leidos', 'registros_validos', 'registros_omitidos', 'registros_duplicados'])
        validar_version(version, resumen, minimo=minimo, proporcion_minima=proporcion_minima)
        activar_version(version)
    except Exception as exc:  # noqa: BLE001 — cualquier fallo deja la versión FALLIDA y la activa intacta
        if version is not None:
            _borrar_filas([version.pk])
            mensaje = str(exc) if isinstance(exc, ErrorImportacion) else f'{type(exc).__name__}: {str(exc)[:200]}'
            VersionPadronRuc.objects.filter(pk=version.pk).update(
                estado=VersionPadronRuc.FALLIDA, error=mensaje[:300], finalizado_en=timezone.now(),
                registros_leidos=resumen.leidos, registros_validos=0,
                registros_omitidos=resumen.incompletas + resumen.ruc_invalidos, registros_duplicados=resumen.duplicados)
        if isinstance(exc, ErrorImportacion):
            raise
        if isinstance(exc, (zipfile.BadZipFile, zlib.error, EOFError)):
            raise ErrorImportacion(f'ZIP dañado o ilegible durante la lectura ({type(exc).__name__}).') from None
        raise ErrorImportacion(f'La importación falló ({type(exc).__name__}); el padrón activo no cambió.') from None
    finally:
        zf.close()
        with connection.cursor() as cur:
            cur.execute('SELECT pg_advisory_unlock(%s)', [CANDADO_IMPORTACION])
    resumen.segundos = round(time.monotonic() - inicio, 1)
    version.refresh_from_db()
    return version, resumen


def estado_padron():
    """Solo metadatos de la versión activa (nunca filas)."""
    v = version_activa()
    if v is None:
        return {'disponible': False, 'version': None, 'registros': 0, 'fecha_padron': None, 'fecha_importacion': None,
                'archivo': None}
    return {
        'disponible': True,
        'version': v.pk,
        'registros': v.registros_validos,
        'fecha_padron': timezone.localtime(v.fecha_padron, ZONA_SUNAT).date().isoformat() if v.fecha_padron else None,
        'fecha_importacion': timezone.localtime(v.activada_en).isoformat() if v.activada_en else None,
        'archivo': v.archivo_interno,
    }
