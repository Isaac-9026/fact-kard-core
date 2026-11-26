"""
Gestión segura de archivos temporales (staging) para trabajos de importación Excel.

Almacena los archivos subidos en un directorio compartido entre el backend HTTP y el worker
`tareas` (configurable vía `settings.IMPORTACION_STAGING_DIR`), protegiendo contra path traversal
y verificando la integridad SHA-256 al reconstruir los streams.
"""
import hashlib
import io
import re
import shutil
from pathlib import Path, PurePosixPath

from django.conf import settings
from rest_framework.exceptions import ValidationError

DEFAULT_STAGING_DIR = '/app/storage/importaciones'
_RE_CARACTERES_SEGUROS = re.compile(r'[^A-Za-z0-9._-]+')


def _staging_root() -> Path:
    base = getattr(settings, 'IMPORTACION_STAGING_DIR', DEFAULT_STAGING_DIR) or DEFAULT_STAGING_DIR
    root = Path(base).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _leer_bytes_stream(archivo) -> bytes:
    if hasattr(archivo, 'seek'):
        archivo.seek(0)
    if hasattr(archivo, 'read'):
        datos = archivo.read()
        return datos if isinstance(datos, (bytes, bytearray)) else bytes(datos)
    return bytes(archivo)


def sanitizar_nombre_archivo(nombre: str) -> str:
    """Devuelve un nombre de archivo seguro sin rutas ni secuencias de path traversal."""
    limpio = PurePosixPath((nombre or '').replace('\\', '/')).name
    limpio = _RE_CARACTERES_SEGUROS.sub('_', limpio).strip('._')
    if not limpio:
        return 'archivo.xlsx'
    if len(limpio) > 180:
        ruta = PurePosixPath(limpio)
        ext = ruta.suffix[:16]
        stem = ruta.stem[: 180 - len(ext)] or 'archivo'
        limpio = f'{stem}{ext}'
    return limpio


def guardar_archivos_staging(trabajo_id: int, archivos) -> tuple[str, list[dict]]:
    """
    Guarda los archivos `.xlsx` de un `ImportacionTrabajo` dentro de `IMPORTACION_STAGING_DIR/trabajo_<id>`.
    Devuelve `(staging_dir_relativo, archivos_meta)` con nombre original, ruta relativa, tamaño y SHA-256.
    """
    if not isinstance(trabajo_id, int) or trabajo_id <= 0:
        raise ValueError('trabajo_id debe ser un entero positivo.')
    if not archivos:
        raise ValidationError({'archivos': 'Adjunte al menos un archivo Excel (.xlsx).'})

    root = _staging_root()
    rel_dir = f'trabajo_{trabajo_id}'
    dir_trabajo = (root / rel_dir).resolve()
    if dir_trabajo == root or not dir_trabajo.is_relative_to(root):
        raise ValueError('Ruta de staging fuera del directorio permitido.')
    dir_trabajo.mkdir(parents=True, exist_ok=True)

    meta = []
    try:
        for idx, (nombre_original, archivo) in enumerate(archivos, start=1):
            nombre_seguro = sanitizar_nombre_archivo(nombre_original)
            nombre_disco = f'{idx:02d}_{nombre_seguro}'
            destino = (dir_trabajo / nombre_disco).resolve()
            if not destino.is_relative_to(dir_trabajo):
                raise ValueError('Ruta destino inválida en staging.')

            datos = _leer_bytes_stream(archivo)
            tamano = len(datos)
            sha256 = hashlib.sha256(datos).hexdigest()
            destino.write_bytes(datos)

            meta.append({
                'nombre': str(nombre_original or nombre_seguro)[:255],
                'ruta_relativa': f'{rel_dir}/{nombre_disco}',
                'tamano': tamano,
                'sha256': sha256,
            })
    except Exception:
        shutil.rmtree(dir_trabajo, ignore_errors=True)
        raise

    return rel_dir, meta


def leer_archivos_staging(trabajo) -> list[tuple[str, io.BytesIO]]:
    """
    Reconstruye streams `(nombre_original, BytesIO)` desde staging verificando que la ruta esté
    confinada en `IMPORTACION_STAGING_DIR` y que tamaño y SHA-256 coincidan con `archivos_meta_json`.
    """
    archivos_meta = getattr(trabajo, 'archivos_meta_json', None) or []
    if not archivos_meta:
        raise ValidationError({'archivos': 'El trabajo no tiene archivos registrados en staging.'})

    root = _staging_root()
    dir_esperado = None
    staging_rel = (getattr(trabajo, 'staging_dir', '') or '').strip()
    if staging_rel:
        dir_esperado = (root / staging_rel).resolve()
        if dir_esperado == root or not dir_esperado.is_relative_to(root):
            raise ValidationError({'archivos': 'Directorio de staging inválido.'})

    streams = []
    for item in archivos_meta:
        ruta_relativa = (item.get('ruta_relativa') or '').strip()
        nombre = item.get('nombre') or 'archivo.xlsx'
        sha_esperado = (item.get('sha256') or '').strip()
        tamano_esperado = item.get('tamano')

        if not ruta_relativa:
            raise ValidationError({'archivos': f'Falta la ruta de staging para "{nombre}".'})

        ruta = (root / ruta_relativa).resolve()
        if not ruta.is_relative_to(root) or (dir_esperado is not None and not ruta.is_relative_to(dir_esperado)):
            raise ValidationError({'archivos': f'Ruta de staging fuera de rango para "{nombre}".'})
        if not ruta.is_file():
            raise ValidationError({'archivos': f'No se encontró el archivo en staging: "{nombre}".'})

        datos = ruta.read_bytes()
        if tamano_esperado is not None and len(datos) != tamano_esperado:
            raise ValidationError({'archivos': f'Tamaño alterado en staging para "{nombre}".'})
        if not sha_esperado or hashlib.sha256(datos).hexdigest() != sha_esperado:
            raise ValidationError({'archivos': f'Integridad SHA-256 inválida en staging para "{nombre}".'})

        streams.append((nombre, io.BytesIO(datos)))

    return streams


def limpiar_staging(trabajo) -> bool:
    """
    Elimina de forma segura el subdirectorio de staging del trabajo dentro de `IMPORTACION_STAGING_DIR`.
    Devuelve True si el directorio existía y estaba dentro del prefijo permitido.
    """
    rel_dir = (getattr(trabajo, 'staging_dir', '') or '').strip()
    if not rel_dir:
        return False

    base = getattr(settings, 'IMPORTACION_STAGING_DIR', DEFAULT_STAGING_DIR) or DEFAULT_STAGING_DIR
    root = Path(base).resolve()
    objetivo = (root / rel_dir).resolve()
    if objetivo == root or not objetivo.is_relative_to(root):
        return False
    if not objetivo.exists():
        return False

    shutil.rmtree(objetivo, ignore_errors=True)
    return True
