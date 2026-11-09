"""Bloque 17C — resultado normalizado y errores de la consulta RUC."""
import re
from dataclasses import asdict, dataclass

CAMPOS = ('ruc', 'razon_social', 'nombre_comercial', 'direccion', 'ubigeo', 'departamento', 'provincia',
          'distrito', 'estado', 'condicion')
VACIOS = {'', '-', '--', '---', 'NULL', 'NONE', 'N/A', 'NA'}
MAX_TEXTO = 300


class ErrorConsultaRuc(Exception):
    codigo = 'SERVICIO_NO_DISPONIBLE'
    http_status = 503
    mensaje = 'El servicio de consulta RUC no está disponible temporalmente. Puede registrar los datos manualmente.'

    def __init__(self, mensaje=None):
        super().__init__(mensaje or self.mensaje)
        self.mensaje = mensaje or self.mensaje


class RucInvalido(ErrorConsultaRuc):
    codigo, http_status = 'RUC_INVALIDO', 400
    mensaje = 'El RUC no es válido.'


class RucNoEncontrado(ErrorConsultaRuc):
    codigo, http_status = 'RUC_NO_ENCONTRADO', 404
    mensaje = 'El RUC no se encontró en la fuente de consulta.'


class ServicioNoDisponible(ErrorConsultaRuc):
    codigo, http_status = 'SERVICIO_NO_DISPONIBLE', 503


class RespuestaIncompleta(ErrorConsultaRuc):
    codigo, http_status = 'RESPUESTA_INCOMPLETA', 502
    mensaje = 'La fuente de consulta devolvió una respuesta incompleta. Complete los datos manualmente.'


class ProveedorNoConfigurado(ErrorConsultaRuc):
    codigo, http_status = 'PROVEEDOR_RUC_NO_CONFIGURADO', 503
    mensaje = ('No hay una fuente de consulta RUC configurada en el servidor. '
               'Puede registrar los datos manualmente.')


class PadronNoCargado(ErrorConsultaRuc):
    """Proveedor padron_reducido configurado pero sin versión activa: NO es "RUC no encontrado"."""
    codigo, http_status = 'PADRON_RUC_NO_CARGADO', 503
    mensaje = 'El padrón SUNAT todavía no ha sido importado. Puede registrar los datos manualmente.'


@dataclass(frozen=True)
class DatosRuc:
    ruc: str
    razon_social: str
    nombre_comercial: str | None = None
    direccion: str | None = None
    ubigeo: str | None = None
    departamento: str | None = None
    provincia: str | None = None
    distrito: str | None = None
    estado: str | None = None
    condicion: str | None = None

    def a_dict(self):
        return asdict(self)


def texto(valor, *, mayusculas=False):
    """Limpia espacios; los marcadores de vacío ('-', '', 'NULL') pasan a None. No inventa nada."""
    if valor is None:
        return None
    limpio = re.sub(r'\s+', ' ', str(valor)).strip()
    if limpio.upper() in VACIOS:
        return None
    limpio = limpio[:MAX_TEXTO]
    return limpio.upper() if mayusculas else limpio


def normalizar(crudo, ruc_consultado):
    """
    (DatosRuc, advertencias) desde el dict del proveedor. Lanza RespuestaIncompleta si falta lo
    mínimo (RUC coincidente y razón social). Campos ausentes quedan en None.
    """
    from apps.documentos.reglas_tributarias import ubigeo_valido
    if not isinstance(crudo, dict):
        raise RespuestaIncompleta()
    ruc = re.sub(r'\D', '', str(crudo.get('ruc') or ''))
    if ruc != ruc_consultado:
        raise RespuestaIncompleta('La fuente devolvió datos de otro RUC; no se usan.')
    razon_social = texto(crudo.get('razon_social'))
    if not razon_social:
        raise RespuestaIncompleta('La fuente no devolvió la razón social del RUC.')
    advertencias = []
    ubigeo = texto(crudo.get('ubigeo'))
    if ubigeo is not None and not ubigeo_valido(ubigeo):
        advertencias.append(f"El ubigeo recibido ('{ubigeo[:10]}') no es un código INEI válido; no se usa.")
        ubigeo = None
    datos = DatosRuc(
        ruc=ruc, razon_social=razon_social, nombre_comercial=texto(crudo.get('nombre_comercial')),
        direccion=texto(crudo.get('direccion')), ubigeo=ubigeo,
        departamento=texto(crudo.get('departamento'), mayusculas=True),
        provincia=texto(crudo.get('provincia'), mayusculas=True),
        distrito=texto(crudo.get('distrito'), mayusculas=True),
        estado=texto(crudo.get('estado'), mayusculas=True), condicion=texto(crudo.get('condicion'), mayusculas=True),
    )
    if datos.estado and datos.estado != 'ACTIVO':
        advertencias.append(f'El contribuyente figura con estado {datos.estado}.')
    if datos.condicion and datos.condicion != 'HABIDO':
        advertencias.append(f'El contribuyente figura con condición de domicilio {datos.condicion}.')
    return datos, advertencias
