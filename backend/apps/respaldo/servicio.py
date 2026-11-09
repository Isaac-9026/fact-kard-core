"""
Bloque 24 — respaldo completo de FACT-KARD: PostgreSQL + artefactos SUNAT + MEDIA_ROOT, con
manifest SHA-256, copia externa opcional, retención acotada, verificación y restauración seguras.

Python puro (Windows y Linux). Solo usa programas externos para la base de datos (pg_dump y
pg_restore, configurables por ruta). Ninguna contraseña se pasa por línea de comandos ni se
escribe en el manifest: la clave de PostgreSQL viaja solo en la variable PGPASSWORD del proceso hijo.

Estructura de un respaldo (dentro de FACT_KARD_BACKUP_DIR):

    .fact-kard-respaldos            marca: este directorio lo controla FACT-KARD (retención solo aquí)
    2026-11-02_023000/
        manifest.json               fecha, formato, componentes, archivos (ruta, tipo, bytes, sha256)
        manifest.json.sha256        SHA-256 del manifest (detecta corrupción del propio manifest)
        database/fact_kard.dump     pg_dump --format=custom
        artefactos/...              copia de SUNAT_ARTEFACTOS_PATH (XML, XML firmado, ZIP, CDR, PDF)
        media/...                   copia de MEDIA_ROOT (logos)

El respaldo se arma en ".parcial-<nombre>" y solo se renombra al nombre final cuando TODO se copió
y verificó; si algo falla, el parcial se elimina y se informa el error (código de salida ≠ 0).
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import connections
from django.utils import timezone

FORMATO = 'fact-kard-respaldo'
VERSION = 1
MARCA = '.fact-kard-respaldos'
MANIFEST = 'manifest.json'
MANIFEST_HASH = 'manifest.json.sha256'
PREFIJO_PARCIAL = '.parcial-'
NOMBRE_DUMP = 'database/fact_kard.dump'
PATRON_NOMBRE = re.compile(r'^(\d{4}-\d{2}-\d{2})_(\d{6})$')
TIPOS = ('database', 'artefactos', 'media')
BLOQUE = 1024 * 1024


class ErrorRespaldo(Exception):
    """Fallo controlado: mensaje para el operador, sin secretos ni trazas."""


@dataclass
class Resultado:
    ok: bool = True
    ruta: Path | None = None
    errores: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)
    eliminados: list = field(default_factory=list)
    copia_externa: str = 'NO_CONFIGURADA'   # NO_CONFIGURADA | OK | FALLIDA
    local_ok: bool = False                  # el respaldo local quedó completo y verificado

    def error(self, texto):
        self.ok = False
        self.errores.append(texto)


# ---- Utilidades seguras ---------------------------------------------------------------------------
def sha256_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, 'rb') as f:
        for bloque in iter(lambda: f.read(BLOQUE), b''):
            h.update(bloque)
    return h.hexdigest()


def _es_temporal(nombre):
    """Temporales de artefactos.py (".<nombre>.<hex>.tmp") y otros restos que no se respaldan."""
    return nombre.endswith(('.tmp', '.parcial', '.swp', '~')) or nombre in ('.DS_Store', 'Thumbs.db')


def ruta_relativa_segura(texto):
    """'database/x.dump' válida; rechaza absolutas, '..', unidades de Windows y barras invertidas."""
    if not isinstance(texto, str) or not texto or '\\' in texto or '\x00' in texto or ':' in texto:
        return None
    p = PurePosixPath(texto)
    if p.is_absolute() or any(parte in ('', '.', '..') for parte in p.parts):
        return None
    return p


def _dentro(hijo, padre):
    try:
        Path(hijo).resolve().relative_to(Path(padre).resolve())
        return True
    except ValueError:
        return False


def raiz_controlada(ruta, *, crear):
    """
    Directorio de respaldos validado: ruta absoluta, no la raíz del sistema ni el home, y marcado
    por FACT-KARD. Si no existe (o está vacío) y `crear`, se crea con la marca. Un directorio con
    contenido y sin marca NO se usa: la retención nunca debe borrar algo que FACT-KARD no creó.
    """
    texto = str(ruta or '').strip()
    if not texto:
        raise ErrorRespaldo('Ruta de respaldos vacía: configure FACT_KARD_BACKUP_DIR.')
    raiz = Path(texto)
    if not raiz.is_absolute():
        raise ErrorRespaldo(f'La ruta de respaldos debe ser absoluta: {texto}')
    raiz = raiz.resolve()
    if raiz == Path(raiz.anchor) or raiz == Path.home().resolve() or len(raiz.parts) < 2:
        raise ErrorRespaldo(f'Ruta de respaldos no permitida: {raiz}')
    for protegida in (settings.BASE_DIR, getattr(settings, 'MEDIA_ROOT', None), getattr(settings, 'SUNAT_ARTEFACTOS_PATH', None)):
        if protegida and str(protegida).strip() and (_dentro(raiz, protegida) or _dentro(protegida, raiz)):
            raise ErrorRespaldo('La ruta de respaldos no puede estar dentro (ni contener) el código, MEDIA_ROOT '
                                'o los artefactos SUNAT.')
    if raiz.exists() and not raiz.is_dir():
        raise ErrorRespaldo(f'La ruta de respaldos no es un directorio: {raiz}')
    marca = raiz / MARCA
    if marca.is_file():
        return raiz
    if not crear:
        raise ErrorRespaldo(f'{raiz} no es un directorio de respaldos de FACT-KARD (falta {MARCA}).')
    if raiz.exists() and any(raiz.iterdir()):
        raise ErrorRespaldo(f'{raiz} tiene contenido y no es un directorio de respaldos de FACT-KARD: no se usa.')
    raiz.mkdir(parents=True, exist_ok=True, mode=0o700)
    marca.write_text('Directorio de respaldos de FACT-KARD. No guarde otros archivos aquí.\n', encoding='utf-8')
    return raiz


def _borrar_dentro(ruta, raiz):
    """rmtree solo si `ruta` es un hijo DIRECTO de `raiz`, real (no enlace) y dentro de ella."""
    ruta, raiz = Path(ruta), Path(raiz).resolve()
    if ruta.is_symlink() or ruta.parent.resolve() != raiz or not _dentro(ruta, raiz) or ruta.resolve() == raiz:
        raise ErrorRespaldo(f'Eliminación fuera del directorio de respaldos rechazada: {ruta}')
    shutil.rmtree(ruta)


def _copiar_verificado(origen, destino):
    """Copia byte a byte (sin seguir enlaces), crea el destino en exclusiva y verifica el SHA-256 releído."""
    st = os.lstat(origen)
    if not stat.S_ISREG(st.st_mode):
        raise ErrorRespaldo(f'No es un archivo regular: {origen}')
    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    h = hashlib.sha256()
    total = 0
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(origen, flags)
    try:
        with os.fdopen(fd, 'rb') as fo, open(destino, 'xb') as fd_dest:
            for bloque in iter(lambda: fo.read(BLOQUE), b''):
                h.update(bloque)
                fd_dest.write(bloque)
                total += len(bloque)
            fd_dest.flush()
            os.fsync(fd_dest.fileno())
    except BaseException:
        destino.unlink(missing_ok=True)
        raise
    if total != os.lstat(origen).st_size or total != st.st_size:
        raise ErrorRespaldo(f'El archivo cambió mientras se copiaba: {origen}')
    digest = h.hexdigest()
    if sha256_archivo(destino) != digest:
        raise ErrorRespaldo(f'La copia no coincide con el original (SHA-256): {origen}')
    return total, digest


# ---- Base de datos --------------------------------------------------------------------------------
def _entorno_pg():
    """Conexión de la base configurada. La clave va SOLO en el entorno del proceso hijo."""
    db = connections['default'].settings_dict
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    if db.get('PASSWORD'):
        env['PGPASSWORD'] = str(db['PASSWORD'])
    args = []
    if db.get('HOST'):
        args += ['--host', str(db['HOST'])]
    if db.get('PORT'):
        args += ['--port', str(db['PORT'])]
    if db.get('USER'):
        args += ['--username', str(db['USER'])]
    return db['NAME'], args, env


def ejecutar(comando, *, env):
    """Ejecuta un programa externo; nunca por shell. Devuelve (código, stderr resumido)."""
    try:
        proc = subprocess.run(comando, env=env, capture_output=True, timeout=getattr(settings, 'FACT_KARD_BACKUP_TIMEOUT', 3600))
    except FileNotFoundError:
        return 127, f'No se encontró el programa {Path(comando[0]).name} (configure su ruta).'
    except subprocess.TimeoutExpired:
        return 124, f'{Path(comando[0]).name} excedió el tiempo máximo.'
    return proc.returncode, proc.stderr.decode('utf-8', 'replace').strip()[-500:]


def volcar_base(destino):
    nombre, args, env = _entorno_pg()
    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    codigo, err = ejecutar([settings.FACT_KARD_PG_DUMP, '--format=custom', '--compress=6', '--no-owner',
                            '--no-privileges', '--no-password', f'--file={destino}', *args, nombre], env=env)
    if codigo != 0 or not destino.is_file() or destino.stat().st_size == 0:
        raise ErrorRespaldo(f'pg_dump falló (código {codigo}): {err or "sin detalle"}')
    validar_dump(destino)


def validar_dump(ruta):
    codigo, err = ejecutar([settings.FACT_KARD_PG_RESTORE, '--list', str(ruta)], env=dict(os.environ))
    if codigo != 0:
        raise ErrorRespaldo(f'El volcado de la base no es legible por pg_restore (código {codigo}): {err or "sin detalle"}')


# ---- Crear ----------------------------------------------------------------------------------------
# Política estricta por componente (Bloque 24, corrección). Artefactos: lo que FACT-KARD persiste
# (nombres.py: XML sin firma y firmado .xml, ZIP de envío y CDR .zip, PDF .pdf). Media: logos
# (empresas/validators.py acepta WEBP/PNG/JPEG y los guarda como .webp).
EXTENSIONES_PERMITIDAS = {'artefactos': frozenset({'.xml', '.zip', '.pdf'}),
                          'media': frozenset({'.webp', '.png', '.jpg', '.jpeg'})}
EXTENSIONES_SENSIBLES = frozenset({'.env', '.pfx', '.p12', '.pem', '.key', '.crt', '.cer', '.der', '.csr', '.jks',
                                   '.keystore', '.kdbx', '.ppk', '.ovpn', '.p8', '.asc', '.gpg'})
PALABRAS_SENSIBLES = ('password', 'passwd', 'contrasena', 'contraseña', 'token', 'secret', 'credential', 'credencial',
                      'clave', 'id_rsa', 'id_ed25519', 'private', 'privada')


def normalizar_nombre(nombre):
    """
    Forma canónica para detectar secretos sin bypass Unicode:
      1. NFKC: compatibilidad (ｐａｓｓｗｏｒｄ → password, ⅼ → l, ligaduras) y composición;
      2. casefold(): mayúsculas/minúsculas en todo Unicode (PASSWORD, ß…);
      3. se eliminan caracteres de formato invisibles (categoría Cf: zero-width, BOM, bidi);
      4. NFKC otra vez tras casefold (casefold puede producir formas no normalizadas).
    Devuelve (normalizado, sin_diacriticos): el segundo quita marcas combinantes (contrásena →
    contrasena, contraseña → contrasena) para comparar también sin acentos.
    """
    n = unicodedata.normalize('NFKC', str(nombre or ''))
    n = ''.join(c for c in n.casefold() if unicodedata.category(c) != 'Cf')
    n = unicodedata.normalize('NFKC', n)
    sin_diacriticos = unicodedata.normalize(
        'NFKC', ''.join(c for c in unicodedata.normalize('NFKD', n) if not unicodedata.combining(c)))
    return n, sin_diacriticos


def es_sensible(nombre):
    """Nombre de archivo que sugiere un secreto (certificado, clave, .env, credenciales), ya normalizado."""
    for n in normalizar_nombre(nombre):
        sufijos = set(PurePosixPath(n).suffixes)
        if (n == '.env' or n.startswith('.env.') or n.endswith('.env') or sufijos & EXTENSIONES_SENSIBLES
                or any(p in n for p in PALABRAS_SENSIBLES)):
            return True
    return False


def _copiar_arbol(origen, destino_rel, base, tipo, archivos, resultado):
    """
    Copia SOLO los tipos permitidos del componente. Un archivo sensible (o de un tipo no esperado)
    ABORTA el respaldo con un error claro: nunca se incluye ni se omite en silencio.
    """
    permitidas = EXTENSIONES_PERMITIDAS[tipo]
    origen = Path(origen)
    for actual, dirs, nombres in os.walk(origen, followlinks=False):
        actual = Path(actual)
        for d in list(dirs):
            if (actual / d).is_symlink():
                dirs.remove(d)
                resultado.advertencias.append(f'{tipo}: enlace simbólico omitido ({(actual / d).relative_to(origen).as_posix()}).')
        dirs.sort()
        for nombre in sorted(nombres):
            ruta = actual / nombre
            relativa = ruta.relative_to(origen).as_posix()
            if es_sensible(nombre):
                raise ErrorRespaldo(f'{tipo}: archivo SENSIBLE inesperado ({relativa}). Retírelo de esa carpeta; los '
                                    'secretos y certificados se guardan aparte, nunca en el respaldo.')
            if _es_temporal(nombre):
                continue
            if Path(nombre).suffix.lower() not in permitidas:
                raise ErrorRespaldo(f'{tipo}: tipo de archivo no permitido ({relativa}). Solo se respaldan '
                                    f'{", ".join(sorted(permitidas))}.')
            if ruta.is_symlink() or not ruta.is_file():
                resultado.advertencias.append(f'{tipo}: se omitió {relativa} (no es un archivo regular).')
                continue
            logica = f'{destino_rel}/{relativa}'
            if ruta_relativa_segura(logica) is None:
                raise ErrorRespaldo(f'{tipo}: nombre de archivo no respaldable: {relativa}')
            bytes_, digest = _copiar_verificado(ruta, base / logica)
            archivos.append({'ruta': logica, 'tipo': tipo, 'bytes': bytes_, 'sha256': digest})


def _escribir_manifest(base, manifest):
    texto = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode('utf-8')
    (base / MANIFEST).write_bytes(texto)
    (base / MANIFEST_HASH).write_text(f'{hashlib.sha256(texto).hexdigest()}  {MANIFEST}\n', encoding='ascii')


def nombre_respaldo(momento=None):
    return timezone.localtime(momento or timezone.now()).strftime('%Y-%m-%d_%H%M%S')


def crear_respaldo(*, destino=None, externo=None, momento=None, aplicar_retencion=True):
    """Crea el respaldo completo. Nunca lanza: devuelve Resultado (ok=False si algo obligatorio falló)."""
    resultado = Resultado()
    try:
        raiz = raiz_controlada(destino if destino is not None else settings.FACT_KARD_BACKUP_DIR, crear=True)
    except ErrorRespaldo as exc:
        resultado.error(str(exc))
        return resultado
    nombre = nombre_respaldo(momento)
    final = raiz / nombre
    parcial = raiz / f'{PREFIJO_PARCIAL}{nombre}'
    if final.exists() or parcial.exists():
        resultado.error(f'Ya existe un respaldo con el nombre {nombre}.')
        return resultado
    archivos, componentes = [], {}
    try:
        parcial.mkdir(mode=0o700)
        # 1. Base de datos (obligatoria).
        dump = parcial / NOMBRE_DUMP
        volcar_base(dump)
        archivos.append({'ruta': NOMBRE_DUMP, 'tipo': 'database', 'bytes': dump.stat().st_size,
                         'sha256': sha256_archivo(dump)})
        componentes['database'] = {'estado': 'OK', 'archivos': 1}
        # 2. Artefactos SUNAT (obligatorios si están configurados: XML, XML firmado, ZIP, CDR, PDF).
        art = str(getattr(settings, 'SUNAT_ARTEFACTOS_PATH', '') or '').strip()
        antes = len(archivos)
        if not art:
            componentes['artefactos'] = {'estado': 'NO_CONFIGURADO', 'archivos': 0}
            resultado.advertencias.append('SUNAT_ARTEFACTOS_PATH no está configurado: no hay artefactos que respaldar.')
        elif not Path(art).is_dir():
            raise ErrorRespaldo('SUNAT_ARTEFACTOS_PATH está configurado pero no existe o no es un directorio.')
        else:
            _copiar_arbol(art, 'artefactos', parcial, 'artefactos', archivos, resultado)
            componentes['artefactos'] = {'estado': 'OK', 'archivos': len(archivos) - antes}
        # 3. MEDIA_ROOT (logos). Las capturas OCR/XML todavía no se guardan en disco (solo su hash).
        media = Path(settings.MEDIA_ROOT)
        antes = len(archivos)
        if media.is_dir():
            _copiar_arbol(media, 'media', parcial, 'media', archivos, resultado)
            componentes['media'] = {'estado': 'OK', 'archivos': len(archivos) - antes}
        else:
            componentes['media'] = {'estado': 'VACIO', 'archivos': 0}
            resultado.advertencias.append('MEDIA_ROOT no existe todavía: no hay archivos de media.')
        manifest = {'formato': FORMATO, 'version': VERSION, 'nombre': nombre,
                    'creado_en': timezone.localtime(momento or timezone.now()).isoformat(),
                    'componentes': componentes, 'archivos': archivos,
                    'total_bytes': sum(a['bytes'] for a in archivos)}
        _escribir_manifest(parcial, manifest)
        verificacion = verificar_respaldo(parcial, nombre_esperado=nombre)
        if not verificacion.ok:
            raise ErrorRespaldo('El respaldo recién creado no pasó la verificación: ' + '; '.join(verificacion.errores))
        os.replace(parcial, final)
    except (ErrorRespaldo, OSError) as exc:
        resultado.error(f'Respaldo NO creado: {exc}')
        if parcial.exists():
            _borrar_dentro(parcial, raiz)
        return resultado
    resultado.ruta = final
    resultado.local_ok = True
    # 4. Copia externa (opcional, pero si está configurada su fallo se reporta como error).
    externo = settings.FACT_KARD_BACKUP_EXTERNAL_PATH if externo is None else externo
    if str(externo or '').strip():
        _copia_externa(final, externo, resultado, aplicar_retencion=aplicar_retencion)
    else:
        resultado.advertencias.append('NO existe copia externa: FACT_KARD_BACKUP_EXTERNAL_PATH no está configurada. '
                                      'Si se pierde este servidor, se pierden también los respaldos.')
    # 5. Retención local (solo después de un respaldo correcto).
    if aplicar_retencion:
        aplicar_politica_retencion(raiz, resultado)
    return resultado


def _copia_externa(respaldo, externo, resultado, *, aplicar_retencion):
    try:
        raiz_ext = raiz_controlada(externo, crear=True)
        if _dentro(raiz_ext, respaldo.parent) or _dentro(respaldo.parent, raiz_ext):
            raise ErrorRespaldo('La copia externa no puede estar en el mismo directorio que los respaldos locales.')
        final = raiz_ext / respaldo.name
        parcial = raiz_ext / f'{PREFIJO_PARCIAL}{respaldo.name}'
        if final.exists() or parcial.exists():
            raise ErrorRespaldo(f'Ya existe {respaldo.name} en la copia externa.')
        try:
            parcial.mkdir(mode=0o700)
            for actual, _dirs, nombres in os.walk(respaldo, followlinks=False):
                for n in nombres:
                    origen = Path(actual) / n
                    _copiar_verificado(origen, parcial / origen.relative_to(respaldo))
            verificacion = verificar_respaldo(parcial, nombre_esperado=respaldo.name)
            if not verificacion.ok:
                raise ErrorRespaldo('; '.join(verificacion.errores))
            os.replace(parcial, final)
        except BaseException:
            if parcial.exists():
                _borrar_dentro(parcial, raiz_ext)
            raise
        resultado.copia_externa = 'OK'
        if aplicar_retencion:
            aplicar_politica_retencion(raiz_ext, resultado)
    except (ErrorRespaldo, OSError) as exc:
        resultado.copia_externa = 'FALLIDA'
        resultado.error(f'La COPIA EXTERNA falló (el respaldo local sí está completo): {exc}')


# ---- Retención ------------------------------------------------------------------------------------
def politica_retencion():
    valores = {}
    for clave, minimo in (('DIARIOS', 1), ('SEMANALES', 0), ('MENSUALES', 0)):
        valor = getattr(settings, f'FACT_KARD_BACKUP_RETENCION_{clave}', None)
        if not isinstance(valor, int) or isinstance(valor, bool) or valor < minimo or valor > 3650:
            raise ErrorRespaldo(f'FACT_KARD_BACKUP_RETENCION_{clave} inválido ({valor!r}): no se elimina ningún respaldo.')
        valores[clave.lower()] = valor
    return valores


def respaldos_en(raiz):
    """[(fecha, ruta)] de respaldos finales (nombre exacto, directorio real), más reciente primero."""
    salida = []
    for hijo in Path(raiz).iterdir():
        m = PATRON_NOMBRE.match(hijo.name)
        if not m or hijo.is_symlink() or not hijo.is_dir():
            continue
        try:
            fecha = datetime.strptime(hijo.name, '%Y-%m-%d_%H%M%S')
        except ValueError:
            continue
        salida.append((fecha, hijo))
    return sorted(salida, reverse=True)


def a_conservar(respaldos, politica):
    conservar = set()
    if not respaldos:
        return conservar
    conservar.add(respaldos[0][1])  # el más reciente NUNCA se elimina
    for clave, cantidad in (('diarios', politica['diarios']), ('semanales', politica['semanales']),
                            ('mensuales', politica['mensuales'])):
        vistos = []
        for fecha, ruta in respaldos:
            grupo = (fecha.date() if clave == 'diarios' else tuple(fecha.isocalendar())[:2] if clave == 'semanales'
                     else (fecha.year, fecha.month))
            if grupo in vistos:
                continue
            if len(vistos) >= cantidad:
                break
            vistos.append(grupo)
            conservar.add(ruta)
    return conservar


def aplicar_politica_retencion(raiz, resultado, *, simular=False):
    try:
        raiz = raiz_controlada(raiz, crear=False)
        politica = politica_retencion()
    except ErrorRespaldo as exc:
        resultado.error(f'Retención no aplicada: {exc}')
        return
    respaldos = respaldos_en(raiz)
    conservar = a_conservar(respaldos, politica)
    for _fecha, ruta in respaldos:
        if ruta in conservar:
            continue
        if not simular:
            try:
                _borrar_dentro(ruta, raiz)
            except (ErrorRespaldo, OSError) as exc:
                resultado.error(f'No se pudo eliminar {ruta.name}: {exc}')
                continue
        resultado.eliminados.append(ruta.name)


# ---- Verificar (solo lectura) ---------------------------------------------------------------------
def leer_manifest(ruta, resultado):
    texto_path = Path(ruta) / MANIFEST
    if not texto_path.is_file() or texto_path.is_symlink():
        resultado.error('Falta manifest.json.')
        return None
    texto = texto_path.read_bytes()
    hash_path = Path(ruta) / MANIFEST_HASH
    if not hash_path.is_file() or hash_path.is_symlink():
        resultado.error('Falta manifest.json.sha256.')
    elif hash_path.read_text(encoding='ascii', errors='replace').split()[:1] != [hashlib.sha256(texto).hexdigest()]:
        resultado.error('manifest.json no coincide con su SHA-256: el manifest fue alterado o está dañado.')
    try:
        manifest = json.loads(texto.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        resultado.error('manifest.json no es JSON válido.')
        return None
    if not isinstance(manifest, dict) or manifest.get('formato') != FORMATO or manifest.get('version') != VERSION:
        resultado.error('manifest.json no es de un respaldo de FACT-KARD compatible (formato/versión).')
        return None
    if not isinstance(manifest.get('archivos'), list):
        resultado.error('manifest.json no lista archivos.')
        return None
    return manifest


def verificar_respaldo(ruta, *, nombre_esperado=None, comprobar_dump=False):
    """No modifica nada. Comprueba manifest, archivos, tamaños, SHA-256 y consistencia mínima."""
    resultado = Resultado(ruta=Path(ruta))
    ruta = Path(ruta)
    if not ruta.is_dir() or ruta.is_symlink():
        resultado.error(f'{ruta} no es un directorio de respaldo.')
        return resultado
    manifest = leer_manifest(ruta, resultado)
    if manifest is None:
        return resultado
    if nombre_esperado and manifest.get('nombre') != nombre_esperado:
        resultado.error('El nombre del manifest no corresponde al respaldo.')
    esperados = set()
    tipos = {t: 0 for t in TIPOS}
    for i, entrada in enumerate(manifest['archivos']):
        if not isinstance(entrada, dict):
            resultado.error(f'Entrada {i} del manifest inválida.')
            continue
        relativa = ruta_relativa_segura(entrada.get('ruta'))
        tipo = entrada.get('tipo')
        if relativa is None or tipo not in TIPOS or relativa.parts[0] != tipo:
            resultado.error(f'Ruta o tipo inválido en el manifest: {str(entrada.get("ruta"))[:120]}')
            continue
        if relativa.as_posix() in esperados:
            resultado.error(f'Archivo duplicado en el manifest: {relativa}')
            continue
        esperados.add(relativa.as_posix())
        tipos[tipo] += 1
        archivo = ruta.joinpath(*relativa.parts)
        if archivo.is_symlink() or not archivo.is_file():
            resultado.error(f'Falta el archivo {relativa}.')
            continue
        if not _dentro(archivo, ruta):
            resultado.error(f'Archivo fuera del respaldo: {relativa}')
            continue
        if archivo.stat().st_size != entrada.get('bytes'):
            resultado.error(f'Tamaño distinto en {relativa}.')
            continue
        if sha256_archivo(archivo) != entrada.get('sha256'):
            resultado.error(f'SHA-256 distinto en {relativa}: el archivo fue alterado o está dañado.')
    if tipos['database'] != 1 or NOMBRE_DUMP not in esperados:
        resultado.error('El respaldo no contiene el volcado de la base de datos.')
    for nombre, comp in (manifest.get('componentes') or {}).items():
        if isinstance(comp, dict) and nombre in tipos and comp.get('estado') == 'OK' and comp.get('archivos') != tipos[nombre]:
            resultado.error(f'El componente {nombre} declara {comp.get("archivos")} archivos y hay {tipos[nombre]}.')
    # Archivos presentes que el manifest no declara (inyectados o restos).
    for actual, _dirs, nombres in os.walk(ruta, followlinks=False):
        for n in nombres:
            rel = (Path(actual) / n).relative_to(ruta).as_posix()
            if rel not in esperados and rel not in (MANIFEST, MANIFEST_HASH):
                resultado.error(f'Archivo no declarado en el manifest: {rel}')
    if comprobar_dump and resultado.ok:
        try:
            validar_dump(ruta / NOMBRE_DUMP)
        except ErrorRespaldo as exc:
            resultado.error(str(exc))
    return resultado


# ---- Restaurar ------------------------------------------------------------------------------------
PREFIJO_RESTORE = '.parcial-restore-'


def _es_reparse(ruta):
    """Enlace simbólico, junction o cualquier reparse point de Windows (sin seguirlo)."""
    try:
        st = os.lstat(ruta)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    atributos = getattr(st, 'st_file_attributes', 0)
    return bool(atributos & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)) if atributos else False


def _rutas_protegidas():
    """Carpetas en las que nunca se restaura: producción, código, home y raíz."""
    protegidas = []
    for valor in (getattr(settings, 'MEDIA_ROOT', None), getattr(settings, 'SUNAT_ARTEFACTOS_PATH', None)):
        if valor and str(valor).strip():
            protegidas.append(Path(str(valor)).resolve())
    protegidas.append(Path(settings.BASE_DIR).resolve().parent)  # el repositorio completo
    return protegidas


def validar_destino_restore(destino, nombre, *, respaldo):
    """
    Destino de archivos: ruta absoluta que NO existe, cuyo padre existe y ninguno de sus
    componentes es un enlace/junction/reparse point. No puede ser (ni estar dentro, ni contener)
    MEDIA_ROOT, SUNAT_ARTEFACTOS_PATH, el repositorio o el respaldo; tampoco el home ni la raíz.
    """
    texto = str(destino or '').strip()
    if not texto or not Path(texto).is_absolute():
        raise ErrorRespaldo(f'El destino de {nombre} debe ser una ruta absoluta.')
    d = Path(os.path.abspath(texto))
    actual = Path(d.anchor)
    for parte in d.parts[1:]:
        actual = actual / parte
        if _es_reparse(actual):
            raise ErrorRespaldo(f'El destino de {nombre} pasa por un enlace simbólico o reparse point ({actual}): rechazado.')
    real = d.parent.resolve() / d.name if d != Path(d.anchor) else d
    if real == Path(real.anchor) or real == Path.home().resolve():
        raise ErrorRespaldo(f'Destino de {nombre} no permitido: {real}')
    for protegida in _rutas_protegidas() + [Path(respaldo).resolve()]:
        if real == protegida or _dentro(real, protegida) or _dentro(protegida, real):
            raise ErrorRespaldo(f'El destino de {nombre} no puede ser ni estar dentro de una carpeta productiva, del '
                                f'repositorio o del respaldo ({protegida}).')
    if d.exists():
        raise ErrorRespaldo(f'El destino de {nombre} ({d}) ya existe: la restauración solo crea carpetas nuevas.')
    if not d.parent.is_dir():
        raise ErrorRespaldo(f'La carpeta padre del destino de {nombre} no existe: {d.parent}')
    return real


def _limpiar_staging(staging):
    if staging is not None and staging.exists() and staging.name.startswith(PREFIJO_RESTORE) and not _es_reparse(staging):
        shutil.rmtree(staging, ignore_errors=True)


def _preparar_staging(ruta, manifest, tipo, destino):
    """Copia el componente a <padre>/.parcial-restore-<destino>-<hex> y lo verifica contra el manifest."""
    staging = destino.parent / f'{PREFIJO_RESTORE}{destino.name}-{os.urandom(4).hex()}'
    staging.mkdir(mode=0o700)
    try:
        for entrada in manifest['archivos']:
            if entrada['tipo'] != tipo:
                continue
            partes = PurePosixPath(entrada['ruta'])
            _bytes, digest = _copiar_verificado(ruta.joinpath(*partes.parts), staging.joinpath(*partes.relative_to(tipo).parts))
            if digest != entrada['sha256']:
                raise ErrorRespaldo(f'SHA-256 distinto al restaurar {entrada["ruta"]}: ABORTADO.')
        for entrada in manifest['archivos']:  # verificación final del staging completo
            if entrada['tipo'] == tipo:
                copia = staging.joinpath(*PurePosixPath(entrada['ruta']).relative_to(tipo).parts)
                if sha256_archivo(copia) != entrada['sha256']:
                    raise ErrorRespaldo(f'La copia preparada de {entrada["ruta"]} no coincide: ABORTADO.')
    except BaseException:
        _limpiar_staging(staging)
        raise
    return staging


def restaurar_respaldo(ruta, *, confirmar, base_datos=None, artefactos=None, media=None, permitir_base_actual=False):
    """
    Restaura SOLO lo pedido, sin sobrescribir nunca:
      1. verificación completa del respaldo (cualquier SHA-256 distinto aborta antes de tocar nada);
      2. confirmación = nombre exacto del respaldo; destinos nuevos y fuera de producción/repositorio;
      3. archivos a un staging hermano (.parcial-restore-…), verificado contra el manifest;
      4. base de datos con pg_restore --single-transaction --exit-on-error (todo o nada);
      5. solo si todo lo anterior salió bien, rename atómico de cada staging a su destino final.
    Ante cualquier fallo se eliminan los staging y el destino final no aparece.
    """
    resultado = Resultado(ruta=Path(ruta))
    stagings = {}
    try:
        ruta = Path(ruta)
        if not any((base_datos, artefactos, media)):
            raise ErrorRespaldo('Indique al menos un destino (--base-datos, --artefactos o --media).')
        verificacion = verificar_respaldo(ruta)
        if not verificacion.ok:
            raise ErrorRespaldo('Verificación previa fallida, restauración ABORTADA: ' + '; '.join(verificacion.errores))
        manifest = json.loads((ruta / MANIFEST).read_text(encoding='utf-8'))
        if confirmar != manifest['nombre']:
            raise ErrorRespaldo(f'Confirmación incorrecta: escriba exactamente el nombre del respaldo ({manifest["nombre"]}).')
        destinos = {tipo: validar_destino_restore(d, tipo, respaldo=ruta)
                    for tipo, d in (('artefactos', artefactos), ('media', media)) if d}
        if len({str(d) for d in destinos.values()}) != len(destinos):
            raise ErrorRespaldo('Los destinos de artefactos y media deben ser distintos.')
        if base_datos:
            actual = connections['default'].settings_dict['NAME']
            if base_datos == actual and not permitir_base_actual:
                raise ErrorRespaldo(f'La base destino es la base configurada ({actual}): restaure en una base nueva o '
                                    'use --permitir-base-actual de forma explícita.')
        for tipo, destino in destinos.items():
            stagings[tipo] = _preparar_staging(ruta, manifest, tipo, destino)
        if base_datos:
            _nombre, args, env = _entorno_pg()
            # --single-transaction: un fallo revierte TODO (compatible con --exit-on-error; no con --jobs).
            codigo, err = ejecutar([settings.FACT_KARD_PG_RESTORE, '--no-owner', '--no-privileges', '--exit-on-error',
                                    '--single-transaction', '--no-password', f'--dbname={base_datos}', *args,
                                    str(ruta / NOMBRE_DUMP)], env=env)
            if codigo != 0:
                raise ErrorRespaldo(f'pg_restore falló (código {codigo}): {err or "sin detalle"}')
        for tipo, staging in list(stagings.items()):
            destino = destinos[tipo]
            if destino.exists() or _es_reparse(destino):
                raise ErrorRespaldo(f'El destino de {tipo} apareció durante la restauración: ABORTADO.')
            os.rename(staging, destino)  # mismo directorio padre → atómico
            stagings.pop(tipo)
    except (ErrorRespaldo, OSError, ValueError, KeyError) as exc:
        resultado.error(str(exc))
    finally:
        for staging in stagings.values():
            _limpiar_staging(staging)
    return resultado
