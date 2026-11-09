"""
Bloque 17C — proveedores de la consulta RUC.

ESTADO DE LA FUENTE OFICIAL (revisado el 31/10/2026; Bloque 17D implementa el padrón):
- Los servicios web documentados por SUNAT para sistemas (Consulta Integrada de Comprobantes
  de Pago, GRE, SIRE) NO devuelven los datos fiscales de un RUC.
- La consulta RUC pública de SUNAT es una página web para personas: NO se hace scraping.
- La única fuente oficial estructurada es el "Padrón reducido del RUC" (archivo masivo
  descargable desde el portal de SUNAT: RUC, razón social, estado, condición, ubigeo y
  dirección). Bloque 17D: `ProveedorPadronReducido` lo consulta desde una copia local en
  PostgreSQL que se importa con `python manage.py importar_padron_ruc <zip>` (ver padron.py).

Proveedores (CONSULTA_RUC_PROVEEDOR):
- '' (por defecto) → `ProveedorNoConfigurado` → PROVEEDOR_RUC_NO_CONFIGURADO.
- 'padron_reducido' → `ProveedorPadronReducido`: oficial, sin credenciales; si aún no hay una
  versión importada responde PADRON_RUC_NO_CARGADO (no "RUC no encontrado").
- 'mock' → `ProveedorMockDesarrollo`: datos FICTICIOS, solo con DEBUG=True o en tests, marcado
  como no oficial.
Ningún proveedor llama a servicios de terceros ni a SUNAT en línea.

Para agregar otro proveedor: subclase de `ProveedorRuc`, implementar `consultar()` (dict con los
CAMPOS de schemas.py, `None` si no existe, ServicioNoDisponible ante timeout o caída) y, si sus
datos cambian por versiones, `version_datos()` (entra en la clave de caché).
"""
from apps.inventario.documentos_identidad import digito_verificador_ruc

from .schemas import PadronNoCargado, ProveedorNoConfigurado as ErrorProveedorNoConfigurado, ServicioNoDisponible

NO_CONFIGURADO = 'PROVEEDOR_RUC_NO_CONFIGURADO'


class ProveedorRuc:
    nombre = 'base'
    oficial = False
    fuente = ''

    def version_datos(self):
        """Identificador de la versión de los datos (entra en la clave de caché). '' si no aplica."""
        return ''

    def actualizado_al(self):
        """Fecha (YYYY-MM-DD) de los datos consultados, si el proveedor la conoce."""
        return None

    def estado(self):
        """Metadatos para el estado administrativo (nunca filas)."""
        return {'disponible': True}

    def consultar(self, ruc: str, *, timeout: float):  # pragma: no cover - interfaz
        raise NotImplementedError


class ProveedorNoConfigurado(ProveedorRuc):
    nombre = NO_CONFIGURADO

    def __init__(self, motivo=None):
        self.motivo = motivo

    def estado(self):
        return {'disponible': False}

    def consultar(self, ruc, *, timeout):
        raise ErrorProveedorNoConfigurado(self.motivo)


def _ruc(base10):
    return base10 + str(digito_verificador_ruc(base10))


# Datos FICTICIOS para desarrollo (RUC con dígito verificador válido, empresas inexistentes).
RUC_DEMO_ACTIVO = _ruc('2099999901')
RUC_DEMO_BAJA = _ruc('2099999902')
RUC_DEMO_PARCIAL = _ruc('1099999903')
RUC_DEMO_CAIDO = _ruc('2099999904')     # simula timeout / servicio caído
DATOS_DEMO = {
    RUC_DEMO_ACTIVO: {
        'ruc': RUC_DEMO_ACTIVO, 'razon_social': 'EMPRESA FICTICIA DEMO S.A.C.', 'nombre_comercial': 'DEMO FICTICIA',
        'direccion': 'AV. FICTICIA 123 (DATO DE PRUEBA)', 'ubigeo': '150101', 'departamento': 'LIMA',
        'provincia': 'LIMA', 'distrito': 'LIMA', 'estado': 'ACTIVO', 'condicion': 'HABIDO',
    },
    RUC_DEMO_BAJA: {
        'ruc': RUC_DEMO_BAJA, 'razon_social': 'COMERCIAL FICTICIA EN BAJA S.R.L.', 'nombre_comercial': '-',
        'direccion': 'JR. DE PRUEBA 456', 'ubigeo': '040101', 'departamento': 'AREQUIPA', 'provincia': 'AREQUIPA',
        'distrito': 'AREQUIPA', 'estado': 'BAJA DE OFICIO', 'condicion': 'NO HABIDO',
    },
    RUC_DEMO_PARCIAL: {
        'ruc': RUC_DEMO_PARCIAL, 'razon_social': 'PERSONA FICTICIA DE PRUEBA', 'direccion': '-',
        'estado': 'ACTIVO', 'condicion': 'HABIDO',
    },
}


class ProveedorMockDesarrollo(ProveedorRuc):
    """Solo desarrollo y pruebas: datos ficticios, NUNCA oficiales."""
    nombre = 'MOCK_DESARROLLO'
    oficial = False
    fuente = 'Datos de prueba (no oficiales)'

    def consultar(self, ruc, *, timeout):
        if ruc == RUC_DEMO_CAIDO:
            raise ServicioNoDisponible('Tiempo de espera agotado (simulado por el proveedor de desarrollo).')
        datos = DATOS_DEMO.get(ruc)
        return dict(datos) if datos else None


class ProveedorPadronReducido(ProveedorRuc):
    """
    Bloque 17D: copia local del Padrón Reducido del RUC publicado por SUNAT (dato oficial, pero NO
    una consulta en línea: vale a la fecha de la versión importada). Busca por índice
    (version_id, ruc) en la versión ACTIVA. El padrón no trae nombre comercial ni nombres de
    departamento/provincia/distrito: esos campos quedan en null (no se deducen).
    """
    nombre = 'padron_reducido'
    oficial = True
    fuente = 'Padrón Reducido SUNAT'

    def __init__(self):
        self._version = None

    def _activa(self):
        if self._version is None:
            from .padron import version_activa
            self._version = version_activa()
            if self._version is None:
                raise PadronNoCargado()
        return self._version

    def version_datos(self):
        return f'v{self._activa().pk}'

    def actualizado_al(self):
        from django.utils import timezone
        from .padron import ZONA_SUNAT
        v = self._activa()
        return timezone.localtime(v.fecha_padron, ZONA_SUNAT).date().isoformat() if v.fecha_padron else None

    def estado(self):
        from .padron import estado_padron
        return estado_padron()

    def consultar(self, ruc, *, timeout):
        from .models import PadronRuc
        fila = PadronRuc.objects.filter(version=self._activa(), ruc=ruc).only(
            'ruc', 'razon_social', 'estado', 'condicion', 'ubigeo', 'domicilio_fiscal').first()
        if fila is None:
            return None
        return {
            'ruc': fila.ruc, 'razon_social': fila.razon_social, 'nombre_comercial': None,
            'direccion': fila.domicilio_fiscal, 'ubigeo': fila.ubigeo,
            'departamento': None, 'provincia': None, 'distrito': None,
            'estado': fila.estado or None, 'condicion': fila.condicion or None,
        }


PROVEEDORES = {'mock': ProveedorMockDesarrollo, 'padron_reducido': ProveedorPadronReducido}


def obtener_proveedor():
    """Proveedor según settings.CONSULTA_RUC_PROVEEDOR ('' → no configurado)."""
    from django.conf import settings
    nombre = (getattr(settings, 'CONSULTA_RUC_PROVEEDOR', '') or '').strip().lower()
    if not nombre:
        return ProveedorNoConfigurado()
    clase = PROVEEDORES.get(nombre)
    if clase is None:
        return ProveedorNoConfigurado(f"El proveedor de consulta RUC '{nombre[:30]}' no existe.")
    if clase is ProveedorMockDesarrollo and not (settings.DEBUG or getattr(settings, 'EJECUTANDO_TESTS', False)):
        return ProveedorNoConfigurado('El proveedor de prueba solo se permite en desarrollo.')
    return clase()
