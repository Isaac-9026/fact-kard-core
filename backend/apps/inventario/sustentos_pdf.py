import hashlib
import os
from pathlib import Path

from django.conf import settings
from django.http import Http404
from rest_framework.exceptions import ValidationError

MAX_SUSTENTO_PDF_BYTES = 5 * 1024 * 1024  # 5 MB
SEPARADOR_PDF = ' ||PDF||'


def codificar_sustento(referencia: str | None, ruta_relativa: str, nombre_original: str, sha256: str) -> str:
    referencia_limpia = (referencia or '').replace('|', '_').strip()[:200]
    return f"{referencia_limpia}{SEPARADOR_PDF}{ruta_relativa}|{nombre_original}|{sha256}"


def decodificar_sustento(cadena: str | None) -> tuple[str, dict | None]:
    if not cadena:
        return ('', None)
    if SEPARADOR_PDF in cadena:
        partes = cadena.split(SEPARADOR_PDF, 1)
        referencia = partes[0].strip()
        bloque_meta = partes[1].split('|')
        if len(bloque_meta) == 3:
            ruta_relativa, nombre_original, sha256 = bloque_meta
            return (
                referencia,
                {
                    'tiene_pdf': True,
                    'nombre_archivo': nombre_original,
                    'sha256': sha256,
                    'ruta_relativa': ruta_relativa,
                    'referencia_legal': referencia,
                },
            )
    return (cadena.strip(), None)


def preservar_sustento_existente(nuevo_texto: str | None, valor_actual: str | None) -> str | None:
    if not valor_actual or SEPARADOR_PDF not in valor_actual:
        return nuevo_texto
    _, meta = decodificar_sustento(valor_actual)
    if not meta:
        return nuevo_texto
    return codificar_sustento(
        nuevo_texto,
        meta['ruta_relativa'],
        meta['nombre_archivo'],
        meta['sha256'],
    )


def guardar_sustento_pdf(archivo, empresa_id: int, categoria: str) -> dict:
    if not archivo:
        raise ValidationError({'archivo': 'Debe adjuntar un archivo PDF.'})

    nombre = getattr(archivo, 'name', '') or ''
    if not nombre.lower().endswith('.pdf'):
        raise ValidationError({'archivo': 'El archivo debe ser un documento PDF válido (máx. 5 MB).'})

    size = getattr(archivo, 'size', None)
    if size is not None and (size <= 0 or size > MAX_SUSTENTO_PDF_BYTES):
        raise ValidationError({'archivo': 'El archivo debe ser un documento PDF válido (máx. 5 MB).'})

    try:
        content = archivo.read()
    except Exception as exc:
        raise ValidationError({'archivo': 'Error al leer el archivo adjunto.'}) from exc

    if not content or len(content) > MAX_SUSTENTO_PDF_BYTES or not content.startswith(b'%PDF-'):
        raise ValidationError({'archivo': 'El archivo debe ser un documento PDF válido (máx. 5 MB).'})

    sha256 = hashlib.sha256(content).hexdigest()
    categoria_segura = 'notas' if categoria == 'notas' else 'cierres'
    ruta_relativa = f"sustentos/empresa_{empresa_id}/{categoria_segura}/{sha256}.pdf"

    media_root = Path(settings.MEDIA_ROOT).resolve()
    ruta_absoluta = (media_root / ruta_relativa).resolve()

    try:
        ruta_absoluta.relative_to(media_root)
    except ValueError as exc:
        raise ValidationError({'archivo': 'Ruta de archivo no permitida.'}) from exc

    ruta_absoluta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_absoluta, 'wb') as f:
        f.write(content)

    nombre_limpio = os.path.basename(nombre).replace('|', '_')[:100]
    return {
        'ruta_relativa': ruta_relativa,
        'nombre_original': nombre_limpio,
        'sha256': sha256,
    }


def abrir_sustento_pdf(ruta_relativa: str, empresa_id: int):
    prefijo_esperado = f"sustentos/empresa_{empresa_id}/"
    if not ruta_relativa or not ruta_relativa.startswith(prefijo_esperado):
        raise Http404('El archivo de sustento no pertenece a la empresa activa o la ruta es inválida.')

    media_root = Path(settings.MEDIA_ROOT).resolve()
    ruta_absoluta = (media_root / ruta_relativa).resolve()

    try:
        ruta_absoluta.relative_to(media_root)
    except ValueError:
        raise Http404('Ruta de archivo inválida.')

    if not ruta_absoluta.is_file():
        raise Http404('El archivo de sustento no fue encontrado en el servidor.')

    return open(ruta_absoluta, 'rb')
