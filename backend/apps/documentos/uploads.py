"""
Bloque 6 — controles mínimos de archivos subidos a captura (sin almacenamiento definitivo).

- Tamaño máximo: settings.CAPTURA_MAX_BYTES (10 MB por defecto).
- Extensión y tipo MIME permitidos según el tipo de captura, y firma real del contenido
  (los primeros bytes), porque el MIME lo declara el cliente.
- XML sin DOCTYPE/ENTITY (evita entidades externas y expansión de entidades).
- Nombre seguro: sin rutas, solo caracteres válidos y longitud acotada.
"""
import os

from django.conf import settings
from django.utils.text import get_valid_filename
from rest_framework.exceptions import ValidationError

PERMITIDOS = {
    'XML': {'.xml'},
    'PDF': {'.pdf'},
    'IMAGEN': {'.jpg', '.jpeg', '.png'},
    'ESCANER': {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff'},
}
MIME_POR_EXTENSION = {
    '.xml': {'text/xml', 'application/xml'},
    '.pdf': {'application/pdf'},
    '.jpg': {'image/jpeg'}, '.jpeg': {'image/jpeg'},
    '.png': {'image/png'},
    '.tif': {'image/tiff'}, '.tiff': {'image/tiff'},
}
MIME_GENERICO = 'application/octet-stream'  # algunos navegadores/escáneres no informan el tipo


def _firma_valida(extension, inicio):
    if extension == '.xml':
        cuerpo = inicio.lstrip(b'\xef\xbb\xbf').lstrip()
        return cuerpo.startswith(b'<')
    if extension == '.pdf':
        return inicio.startswith(b'%PDF')
    if extension in ('.jpg', '.jpeg'):
        return inicio.startswith(b'\xff\xd8\xff')
    if extension == '.png':
        return inicio.startswith(b'\x89PNG\r\n\x1a\n')
    if extension in ('.tif', '.tiff'):
        return inicio[:4] in (b'II*\x00', b'MM\x00*')
    return False


def nombre_seguro(nombre):
    base = os.path.basename(str(nombre or '').replace('\\', '/'))
    raiz, extension = os.path.splitext(base)
    raiz = get_valid_filename(raiz)[:80] if raiz.strip() else 'archivo'
    return f'{raiz}{extension.lower()[:10]}'


def validar_archivo_captura(archivo, tipo):
    """Devuelve el nombre seguro del archivo o lanza ValidationError (400)."""
    maximo = int(getattr(settings, 'CAPTURA_MAX_BYTES', 10 * 1024 * 1024))
    if archivo.size == 0:
        raise ValidationError({'archivo': 'El archivo está vacío.'})
    if archivo.size > maximo:
        raise ValidationError({'archivo': f'El archivo supera el tamaño máximo permitido ({maximo // (1024 * 1024)} MB).'})

    nombre = nombre_seguro(archivo.name)
    extension = os.path.splitext(nombre)[1]
    permitidas = PERMITIDOS[tipo]
    if extension not in permitidas:
        raise ValidationError({'archivo': (
            f"Extensión '{extension or '(sin extensión)'}' no permitida para {tipo}. "
            f"Permitidas: {', '.join(sorted(permitidas))}."
        )})
    mime = (getattr(archivo, 'content_type', '') or '').split(';')[0].strip().lower()
    if mime and mime != MIME_GENERICO and mime not in MIME_POR_EXTENSION[extension]:
        raise ValidationError({'archivo': f"El tipo MIME '{mime}' no corresponde a un archivo {extension}."})

    inicio = archivo.read(2048)
    archivo.seek(0)
    if not _firma_valida(extension, inicio):
        raise ValidationError({'archivo': f'El contenido no corresponde a un archivo {extension} válido.'})
    if extension == '.xml':
        contenido = archivo.read()
        archivo.seek(0)
        if b'<!DOCTYPE' in contenido.upper() or b'<!ENTITY' in contenido.upper():
            raise ValidationError({'archivo': 'El XML no puede contener declaraciones DOCTYPE/ENTITY.'})
    return nombre
