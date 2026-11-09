"""
Afectación del IGV por línea — Bloque 3 (mínimo necesario, no es un módulo tributario).

Cada línea se clasifica en GRAVADO, EXONERADO, INAFECTO, EXPORTACION o GRATUITO.
Opcionalmente guarda el código del Catálogo 07 de SUNAT ("Códigos de tipo de
afectación del IGV", Anexo E de la R.S. 245-2017/SUNAT) del que se derivó.

La validación vive en el backend; el frontend solo ayuda.
"""
from decimal import ROUND_HALF_UP, Decimal

from rest_framework.exceptions import ValidationError

TOLERANCIA_IGV = Decimal('0.01')
CIEN = Decimal('100')

GRAVADO, EXONERADO, INAFECTO, EXPORTACION, GRATUITO = (
    'GRAVADO', 'EXONERADO', 'INAFECTO', 'EXPORTACION', 'GRATUITO',
)
AFECTACIONES = (
    (GRAVADO, 'Gravado'),
    (EXONERADO, 'Exonerado'),
    (INAFECTO, 'Inafecto'),
    (EXPORTACION, 'Exportación'),
    (GRATUITO, 'Gratuito / bonificación'),
)
SIN_IGV = {EXONERADO, INAFECTO, EXPORTACION}

# Catálogo 07 → afectación. 11-16, 21 y 31-36 son transferencias gratuitas
# (retiros, premios, donaciones, bonificaciones, muestras, publicidad).
CATALOGO_07 = {
    '10': GRAVADO,
    **{c: GRATUITO for c in ('11', '12', '13', '14', '15', '16')},
    '20': EXONERADO,
    '21': GRATUITO,
    '30': INAFECTO,
    **{c: GRATUITO for c in ('31', '32', '33', '34', '35', '36')},
    '40': EXPORTACION,
}
# 17 (Gravado – IVAP) usa otra tasa; no se soporta en este bloque.
CODIGOS_NO_SOPORTADOS = {'17': 'Gravado – IVAP (tasa distinta del IGV general)'}

# Bloque 17A (B17A-QA-001): descripciones oficiales del Catálogo 07 (Anexo E, R.S. 245-2017/SUNAT),
# en esta misma fuente canónica. Las expone la API (catalogos/afectaciones-igv/) para que el
# frontend no mantenga una copia.
DESCRIPCIONES_CATALOGO_07 = {
    '10': 'Gravado - Operación Onerosa',
    '11': 'Gravado – Retiro por premio',
    '12': 'Gravado – Retiro por donación',
    '13': 'Gravado – Retiro',
    '14': 'Gravado – Retiro por publicidad',
    '15': 'Gravado – Bonificaciones',
    '16': 'Gravado – Retiro por entrega a trabajadores',
    '17': 'Gravado – IVAP',
    '20': 'Exonerado - Operación Onerosa',
    '21': 'Exonerado – Transferencia Gratuita',
    '30': 'Inafecto - Operación Onerosa',
    '31': 'Inafecto – Retiro por Bonificación',
    '32': 'Inafecto – Retiro',
    '33': 'Inafecto – Retiro por Muestras Médicas',
    '34': 'Inafecto - Retiro por Convenio Colectivo',
    '35': 'Inafecto – Retiro por premio',
    '36': 'Inafecto - Retiro por publicidad',
    '40': 'Exportación',
}
# Códigos de transferencia gratuita (11-16, 21, 31-36), derivados del propio CATALOGO_07.
CODIGOS_GRATUITOS = tuple(sorted(c for c, a in CATALOGO_07.items() if a == GRATUITO))


def catalogo_07():
    """Catálogo 07 completo: código, descripción oficial, afectación interna y si está soportado."""
    return [
        {'codigo': codigo, 'descripcion': descripcion, 'afectacion': CATALOGO_07.get(codigo),
         'soportado': codigo in CATALOGO_07}
        for codigo, descripcion in sorted(DESCRIPCIONES_CATALOGO_07.items())
    ]


def validar_codigo_gratuito(codigo):
    """Error (str) si el código no es de transferencia gratuita del Catálogo 07, o None."""
    if codigo not in CODIGOS_GRATUITOS:
        return (f"El código '{codigo}' no corresponde a una operación gratuita del Catálogo 07 "
                f"(use {', '.join(CODIGOS_GRATUITOS)}).")
    return None


def resolver_afectacion(*, afectacion, codigo, es_bonificacion, linea_num):
    """Devuelve (afectacion, codigo) normalizados o lanza ValidationError (400)."""
    codigo = (codigo or '').strip() or None
    afectacion = (afectacion or '').strip().upper() or None
    if codigo is not None:
        if codigo in CODIGOS_NO_SOPORTADOS:
            raise ValidationError({'detalles': (
                f"Línea {linea_num}: afectación {codigo} ({CODIGOS_NO_SOPORTADOS[codigo]}) no soportada; "
                'registre el comprobante manualmente.'
            )})
        if codigo not in CATALOGO_07:
            raise ValidationError({'detalles': (
                f"Línea {linea_num}: el código de afectación del IGV '{codigo}' no existe en el Catálogo 07 de SUNAT."
            )})
        derivada = CATALOGO_07[codigo]
        if afectacion is not None and afectacion != derivada:
            raise ValidationError({'detalles': (
                f"Línea {linea_num}: la afectación {afectacion} no coincide con el código SUNAT {codigo} ({derivada})."
            )})
        afectacion = derivada
    if afectacion is None:
        afectacion = GRATUITO if es_bonificacion else GRAVADO
    if afectacion not in dict(AFECTACIONES):
        raise ValidationError({'detalles': f"Línea {linea_num}: afectación del IGV '{afectacion}' no válida."})
    if es_bonificacion and afectacion != GRATUITO:
        raise ValidationError({'detalles': (
            f"Línea {linea_num}: una bonificación es una transferencia gratuita; su afectación debe ser GRATUITO."
        )})
    return afectacion, codigo


def tasa_igv(empresa_id, fecha=None):
    """
    Tasa del IGV (fracción, p. ej. 0.18) aplicable a una operación de `fecha` (hoy si se
    omite), desde una única fuente:
    1) Bloque 5: TasaIgvVigencia con mayor vigente_desde <= fecha;
    2) ConfigEmpresa.tasa_igv_pct (Bloque 4);
    3) TASA_IGV_POR_DEFECTO_PCT.
    """
    from django.utils import timezone

    from apps.empresas.models import TASA_IGV_POR_DEFECTO_PCT, ConfigEmpresa, TasaIgvVigencia

    fecha = fecha or timezone.localdate()
    pct = TasaIgvVigencia.objects.filter(empresa_id=empresa_id, vigente_desde__lte=fecha).order_by(
        '-vigente_desde',
    ).values_list('tasa_pct', flat=True).first()
    if pct is None:
        pct = ConfigEmpresa.objects.filter(empresa_id=empresa_id).values_list('tasa_igv_pct', flat=True).first()
    return (pct if pct is not None else TASA_IGV_POR_DEFECTO_PCT) / CIEN


def igv_esperado(base, tasa):
    return (base * tasa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def validar_igv_linea(*, igv, base, afectacion, linea_num, tasa):
    """
    GRAVADO: IGV = base × tasa configurada (± S/ 0.01); con base > 0 el IGV 0 se rechaza.
    EXONERADO / INAFECTO / EXPORTACION: IGV 0.
    GRATUITO: se conserva la lógica previa (sin validación de tasa; el IGV de una
    transferencia gratuita es referencial o no existe).
    """
    if afectacion == GRATUITO:
        return
    if afectacion in SIN_IGV:
        if igv != Decimal('0'):
            raise ValidationError({'detalles': (
                f"Línea {linea_num}: una línea {afectacion.lower()} no lleva IGV (recibido {igv.normalize():f})."
            )})
        return
    esperado = igv_esperado(base, tasa)
    if abs(igv - esperado) > TOLERANCIA_IGV:
        raise ValidationError({'detalles': (
            f"Línea {linea_num}: el IGV {igv.normalize():f} no corresponde a la base gravada "
            f"{base.normalize():f} ({(tasa * CIEN).normalize():f} % = {esperado:f}). Si la línea es "
            'exonerada, inafecta o de exportación indique su afectación.'
        )})
