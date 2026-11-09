"""
Bloque 16 — documento de identidad del tercero (Catálogo 06 SUNAT).

`tercero.tipo_documento` guarda SOLO el código del catálogo ('6', '1', ...). Los alias que
la pantalla o datos antiguos podían traer ('RUC', 'DNI', ...) se convierten al código antes de
validar y de buscar duplicados, para que '6'+20123456789 y 'RUC'+20123456789 sean la misma
identidad.
"""
import re

RUC, DNI, CARNET_EXTRANJERIA, PASAPORTE, CEDULA_DIPLOMATICA, SIN_RUC = '6', '1', '4', '7', 'A', '0'

TIPOS_DOCUMENTO_IDENTIDAD = (
    (SIN_RUC, 'Doc. trib. no domiciliado sin RUC'),
    (DNI, 'DNI'),
    (CARNET_EXTRANJERIA, 'Carnet de extranjería'),
    (RUC, 'RUC'),
    (PASAPORTE, 'Pasaporte'),
    (CEDULA_DIPLOMATICA, 'Cédula diplomática de identidad'),
)
CODIGOS_DOCUMENTO_IDENTIDAD = tuple(codigo for codigo, _ in TIPOS_DOCUMENTO_IDENTIDAD)

ALIAS_TIPO_DOCUMENTO = {
    'RUC': RUC, 'DNI': DNI, 'CE': CARNET_EXTRANJERIA, 'CARNET': CARNET_EXTRANJERIA,
    'CARNET DE EXTRANJERIA': CARNET_EXTRANJERIA, 'PASAPORTE': PASAPORTE, 'PAS': PASAPORTE,
    'CDI': CEDULA_DIPLOMATICA, '00': SIN_RUC, '01': DNI, '04': CARNET_EXTRANJERIA, '06': RUC, '07': PASAPORTE,
}

PESOS_RUC = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
PREFIJOS_RUC = ('10', '15', '16', '17', '20')


def normalizar_tipo_documento(valor):
    """'RUC' / ' 6 ' / '06' → '6'. Un valor desconocido se devuelve tal cual (en mayúsculas)."""
    texto = str(valor or '').strip().upper()
    if texto in CODIGOS_DOCUMENTO_IDENTIDAD:
        return texto
    return ALIAS_TIPO_DOCUMENTO.get(texto, texto)


def digito_verificador_ruc(primeros_diez):
    """Módulo 11 de SUNAT sobre los 10 primeros dígitos."""
    suma = sum(int(d) * p for d, p in zip(primeros_diez, PESOS_RUC))
    resto = 11 - (suma % 11)
    return {10: 0, 11: 1}.get(resto, resto)


def es_ruc_valido(numero):
    numero = str(numero or '').strip()
    return (
        bool(re.fullmatch(r'\d{11}', numero))
        and numero[:2] in PREFIJOS_RUC
        and digito_verificador_ruc(numero[:10]) == int(numero[10])
    )


def validar_documento_identidad(tipo, numero):
    """
    (tipo_normalizado, numero_normalizado, error | None). El número se guarda sin espacios
    y en mayúsculas (los documentos alfanuméricos).
    """
    tipo = normalizar_tipo_documento(tipo)
    numero = re.sub(r'\s+', '', str(numero or '')).upper()
    if tipo not in CODIGOS_DOCUMENTO_IDENTIDAD:
        return tipo, numero, (
            f"Tipo de documento '{tipo}' no válido. Use el catálogo 06: "
            + ', '.join(f'{c} = {d}' for c, d in TIPOS_DOCUMENTO_IDENTIDAD) + '.'
        )
    if not numero:
        return tipo, numero, 'El número de documento es obligatorio.'
    if tipo == RUC:
        if not re.fullmatch(r'\d{11}', numero):
            return tipo, numero, 'El RUC debe tener exactamente 11 dígitos.'
        if numero[:2] not in PREFIJOS_RUC:
            return tipo, numero, 'El RUC debe empezar con 10, 15, 16, 17 o 20.'
        if not es_ruc_valido(numero):
            return tipo, numero, 'El RUC no es válido (dígito verificador incorrecto).'
    elif tipo == DNI:
        if not re.fullmatch(r'\d{8}', numero):
            return tipo, numero, 'El DNI debe tener exactamente 8 dígitos.'
    elif tipo in (CARNET_EXTRANJERIA, PASAPORTE, CEDULA_DIPLOMATICA):
        if not re.fullmatch(r'[A-Z0-9]{4,12}', numero):
            return tipo, numero, 'El documento debe tener entre 4 y 12 caracteres alfanuméricos.'
    elif not re.fullmatch(r'[A-Z0-9-]{1,15}', numero):
        return tipo, numero, 'El documento debe tener hasta 15 caracteres alfanuméricos.'
    return tipo, numero, None
