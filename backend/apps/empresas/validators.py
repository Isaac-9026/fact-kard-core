import re
from PIL import Image
from django.core.files.storage import default_storage
from rest_framework.exceptions import ValidationError

MAX_LOGO_BYTES = 512 * 1024  # 512 KB
FORMATOS_PERMITIDOS = {'WEBP', 'PNG', 'JPEG'}
MAX_DIMENSION = 1024
REGEX_COLOR_HEX = re.compile(r'^#[0-9A-Fa-f]{6}$')


def validar_logo_archivo(archivo):
    """
    Validación binaria anti-spoofing con Pillow:
    1. Verifica tamaño <= 512 KB.
    2. Abre con PIL.Image.open y ejecuta img.verify().
    3. Valida que el formato real sea WEBP, PNG o JPEG.
    4. Verifica dimensiones <= 1024x1024px.
    5. Rebobina archivo.seek(0) para dejar el puntero listo para guardado.
    """
    if archivo is None:
        return None

    if archivo.size > MAX_LOGO_BYTES:
        raise ValidationError(f'El archivo no debe superar los 512 KB (recibido {archivo.size // 1024} KB).')

    try:
        archivo.seek(0)
        img = Image.open(archivo)
        img.verify()
        formato = (img.format or '').upper()
        if formato not in FORMATOS_PERMITIDOS:
            raise ValidationError(f'Formato no permitido: {formato or "DESCONOCIDO"}. Solo se admiten WEBP, PNG y JPEG.')
    except Exception as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError('El archivo no es una imagen válida o está dañado.')
    finally:
        archivo.seek(0)

    # Reabrir para chequear dimensiones (verify() agota la instancia en algunas versiones de Pillow)
    try:
        archivo.seek(0)
        img_dim = Image.open(archivo)
        ancho, alto = img_dim.size
        if ancho > MAX_DIMENSION or alto > MAX_DIMENSION:
            raise ValidationError(
                f'Las dimensiones de la imagen ({ancho}x{alto}px) no deben superar {MAX_DIMENSION}x{MAX_DIMENSION}px.'
            )
    except Exception as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError('No se pudieron verificar las dimensiones de la imagen.')
    finally:
        archivo.seek(0)

    return archivo


def validar_color_tema(valor):
    """
    Valida formato hexadecimal estricto ^#[0-9A-Fa-f]{6}$.
    """
    if valor is None or valor == '':
        return None
    valor = valor.strip()
    if not REGEX_COLOR_HEX.match(valor):
        raise ValidationError('El color de tema debe tener formato hexadecimal válido (ej. #4F46E5).')
    return valor.upper()


def eliminar_archivo_seguro(ruta_archivo):
    """
    Eliminación física segura dentro de transaction.on_commit.
    """
    if not ruta_archivo:
        return
    try:
        if default_storage.exists(ruta_archivo):
            default_storage.delete(ruta_archivo)
    except Exception:
        pass

