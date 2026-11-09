"""
Bloque 17C — consulta RUC. Solo datos FICTICIOS y proveedores simulados: ninguna prueba se
conecta a SUNAT ni a terceros.
"""
import json
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.auditoria.models import Auditoria
from apps.catalogos.models import Moneda
from apps.documentos.reglas_tributarias import validar_emisor
from apps.empresas.models import Empresa
from apps.inventario.documentos_identidad import digito_verificador_ruc
from apps.usuarios.models import Usuario, UsuarioEmpresa
from config.seguridad import Secreto

from . import providers
from .providers import (
    DATOS_DEMO, RUC_DEMO_ACTIVO, RUC_DEMO_BAJA, RUC_DEMO_CAIDO, RUC_DEMO_PARCIAL, ProveedorMockDesarrollo,
    ProveedorNoConfigurado, ProveedorRuc, obtener_proveedor,
)
from .schemas import (
    ProveedorNoConfigurado as ErrorNoConfigurado, RespuestaIncompleta, RucInvalido, RucNoEncontrado,
    ServicioNoDisponible, normalizar,
)
from .service import consultar_ruc


def ruc(base10):
    return base10 + str(digito_verificador_ruc(base10))


class ProveedorEspia(ProveedorRuc):
    """Proveedor de prueba que registra cada llamada y responde lo que se le indique."""
    nombre = 'ESPIA'

    def __init__(self, respuesta=None, error=None):
        self.respuesta, self.error, self.llamadas = respuesta, error, []

    def consultar(self, ruc, *, timeout):
        self.llamadas.append((ruc, timeout))
        if self.error:
            raise self.error
        return self.respuesta


COMPLETO = {
    'ruc': ruc('2055555501'), 'razon_social': '  ACME   FICTICIA  S.A.C. ', 'nombre_comercial': 'ACME',
    'direccion': 'AV. PRUEBA 100', 'ubigeo': '150122', 'departamento': 'lima', 'provincia': 'Lima',
    'distrito': 'miraflores', 'estado': 'activo', 'condicion': 'habido',
}


# =============================================================================================
class ServicioTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    # 1 y 8: RUC válido y normalización correcta
    def test_ruc_valido_normalizado(self):
        espia = ProveedorEspia(dict(COMPLETO))
        r = consultar_ruc(f' {COMPLETO["ruc"]} ', proveedor=espia)
        self.assertEqual(r['datos'], {
            'ruc': COMPLETO['ruc'], 'razon_social': 'ACME FICTICIA S.A.C.', 'nombre_comercial': 'ACME',
            'direccion': 'AV. PRUEBA 100', 'ubigeo': '150122', 'departamento': 'LIMA', 'provincia': 'LIMA',
            'distrito': 'MIRAFLORES', 'estado': 'ACTIVO', 'condicion': 'HABIDO'})
        self.assertEqual((r['proveedor'], r['oficial'], r['desde_cache'], r['advertencias']), ('ESPIA', False, False, []))

    # 2, 3 y 14: RUC inválido o dígito verificador incorrecto → el proveedor no recibe nada
    def test_ruc_invalido_no_llega_al_proveedor(self):
        espia = ProveedorEspia(dict(COMPLETO))
        valido = COMPLETO['ruc']
        for malo in ('123', '2055555501X', '30555555011', valido[:10] + str((int(valido[10]) + 1) % 10), '', None):
            with self.assertRaises(RucInvalido) as ctx:
                consultar_ruc(malo, proveedor=espia)
            self.assertEqual(ctx.exception.codigo, 'RUC_INVALIDO')
        self.assertIn('dígito verificador', str(RucInvalido('El RUC no es válido (dígito verificador incorrecto).')))
        self.assertEqual(espia.llamadas, [])

    # 4: proveedor no configurado
    def test_proveedor_no_configurado(self):
        with override_settings(CONSULTA_RUC_PROVEEDOR=''):
            self.assertIsInstance(obtener_proveedor(), ProveedorNoConfigurado)
            with self.assertRaises(ErrorNoConfigurado) as ctx:
                consultar_ruc(COMPLETO['ruc'])
        self.assertEqual(ctx.exception.codigo, 'PROVEEDOR_RUC_NO_CONFIGURADO')
        with override_settings(CONSULTA_RUC_PROVEEDOR='inexistente'):
            self.assertIsInstance(obtener_proveedor(), ProveedorNoConfigurado)
        # El mock de desarrollo no se acepta fuera de DEBUG/tests.
        with override_settings(CONSULTA_RUC_PROVEEDOR='mock', DEBUG=False, EJECUTANDO_TESTS=False):
            self.assertIsInstance(obtener_proveedor(), ProveedorNoConfigurado)
        with override_settings(CONSULTA_RUC_PROVEEDOR='mock', DEBUG=True):
            self.assertIsInstance(obtener_proveedor(), ProveedorMockDesarrollo)

    # 5: no encontrado
    def test_ruc_no_encontrado(self):
        with self.assertRaises(RucNoEncontrado) as ctx:
            consultar_ruc(COMPLETO['ruc'], proveedor=ProveedorEspia(None))
        self.assertEqual((ctx.exception.codigo, ctx.exception.http_status), ('RUC_NO_ENCONTRADO', 404))

    # 6 y 18: servicio caído / timeout → respuesta controlada, sin trazas
    def test_servicio_caido_y_timeout(self):
        for error in (TimeoutError('read timeout 10.0.0.1:443 secret=xyz'), ConnectionError('boom'), ValueError('json')):
            with self.assertRaises(ServicioNoDisponible) as ctx:
                consultar_ruc(COMPLETO['ruc'], proveedor=ProveedorEspia(error=error))
            self.assertEqual(ctx.exception.codigo, 'SERVICIO_NO_DISPONIBLE')
            self.assertNotIn('10.0.0.1', ctx.exception.mensaje)
            self.assertNotIn('secret', ctx.exception.mensaje)
        with self.assertRaises(ServicioNoDisponible):
            consultar_ruc(RUC_DEMO_CAIDO, proveedor=ProveedorMockDesarrollo())
        espia = ProveedorEspia(dict(COMPLETO))
        with override_settings(CONSULTA_RUC_TIMEOUT_SEGUNDOS=3.5):
            consultar_ruc(COMPLETO['ruc'], proveedor=espia)
        self.assertEqual(espia.llamadas, [(COMPLETO['ruc'], 3.5)])

    # 7: respuesta parcial / incompleta
    def test_respuesta_incompleta(self):
        for crudo in ({'ruc': COMPLETO['ruc']}, {'ruc': COMPLETO['ruc'], 'razon_social': ' - '},
                      {**COMPLETO, 'ruc': ruc('2066666601')}, 'texto', []):
            with self.assertRaises(RespuestaIncompleta) as ctx:
                consultar_ruc(COMPLETO['ruc'], proveedor=ProveedorEspia(crudo))
            self.assertEqual(ctx.exception.codigo, 'RESPUESTA_INCOMPLETA')

    # 9 y 10: ubigeo válido / inválido y campos opcionales nulos (sin inventar)
    def test_ubigeo_y_opcionales_nulos(self):
        datos, adv = normalizar({'ruc': COMPLETO['ruc'], 'razon_social': 'X SAC', 'ubigeo': '150122'}, COMPLETO['ruc'])
        self.assertEqual((datos.ubigeo, adv), ('150122', []))
        datos, adv = normalizar({'ruc': COMPLETO['ruc'], 'razon_social': 'X SAC', 'ubigeo': '999999',
                                 'direccion': 'CALLE 1'}, COMPLETO['ruc'])
        self.assertIsNone(datos.ubigeo)
        self.assertTrue(any('no es un código INEI válido' in a for a in adv))
        self.assertIsNone(datos.departamento)  # solo dirección textual: no se inventa ubigeo ni distrito
        r = consultar_ruc(RUC_DEMO_PARCIAL, proveedor=ProveedorMockDesarrollo())
        self.assertEqual(r['datos'], {'ruc': RUC_DEMO_PARCIAL, 'razon_social': 'PERSONA FICTICIA DE PRUEBA',
                                      'nombre_comercial': None, 'direccion': None, 'ubigeo': None, 'departamento': None,
                                      'provincia': None, 'distrito': None, 'estado': 'ACTIVO', 'condicion': 'HABIDO'})

    def test_estado_y_condicion_oficiales_se_advierten(self):
        r = consultar_ruc(RUC_DEMO_BAJA, proveedor=ProveedorMockDesarrollo())
        self.assertEqual((r['datos']['estado'], r['datos']['condicion'], r['datos']['nombre_comercial']),
                         ('BAJA DE OFICIO', 'NO HABIDO', None))
        self.assertEqual(len(r['advertencias']), 2)

    # 15: caché de consultas exitosas
    def test_cache_solo_de_exitos(self):
        espia = ProveedorEspia(dict(COMPLETO))
        primera = consultar_ruc(COMPLETO['ruc'], proveedor=espia)
        segunda = consultar_ruc(COMPLETO['ruc'], proveedor=espia)
        self.assertEqual((primera['desde_cache'], segunda['desde_cache'], len(espia.llamadas)), (False, True, 1))
        self.assertEqual(primera['datos'], segunda['datos'])
        consultar_ruc(COMPLETO['ruc'], proveedor=espia, usar_cache=False)
        self.assertEqual(len(espia.llamadas), 2)
        fallido = ProveedorEspia(None)
        fallido.nombre = 'OTRO'
        for _ in range(2):
            with self.assertRaises(RucNoEncontrado):
                consultar_ruc(COMPLETO['ruc'], proveedor=fallido)
        self.assertEqual(len(fallido.llamadas), 2)  # los errores no se cachean

    def test_cache_caida_no_impide_consultar(self):
        espia = ProveedorEspia(dict(COMPLETO))
        with mock.patch('apps.consulta_ruc.service.cache') as rota:
            rota.get.side_effect = ConnectionError('redis caído')
            rota.set.side_effect = ConnectionError('redis caído')
            self.assertEqual(consultar_ruc(COMPLETO['ruc'], proveedor=espia)['datos']['ruc'], COMPLETO['ruc'])

    def test_datos_demo_son_ficticios_y_validos(self):
        for numero, datos in DATOS_DEMO.items():
            self.assertEqual(numero, datos['ruc'])
            consultar_ruc(numero, proveedor=ProveedorMockDesarrollo())  # dígito verificador correcto
        self.assertTrue(all('FICTICI' in d['razon_social'] for d in DATOS_DEMO.values()))
        self.assertFalse(ProveedorMockDesarrollo.oficial)
        # Sin terceros: solo el mock y (Bloque 17D) la copia local del padrón oficial de SUNAT.
        self.assertEqual(providers.PROVEEDORES, {'mock': ProveedorMockDesarrollo,
                                                 'padron_reducido': providers.ProveedorPadronReducido})


# =============================================================================================
@override_settings(CONSULTA_RUC_PROVEEDOR='mock', CONSULTA_RUC_THROTTLE_RATE='1000/min')
class EndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        pen = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(ruc=ruc('2010010010'), razon_social='EMPRESA 17C', moneda_base_codigo=pen)
        self.otra = Empresa.objects.create(ruc=ruc('2020020020'), razon_social='OTRA 17C', moneda_base_codigo=pen)
        self.admin = Usuario.objects.create(username='admin17c', email='a17c@test.pe', password_hash='x')
        self.lector = Usuario.objects.create(username='lector17c', email='l17c@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=self.admin, empresa=self.empresa, rol='ADMIN')
        UsuarioEmpresa.objects.create(usuario=self.lector, empresa=self.empresa, rol='USUARIO')
        self.client = APIClient()
        self.h = {'HTTP_X_EMPRESA_ID': str(self.empresa.id)}

    def get(self, numero, headers=None):
        return self.client.get(reverse('consulta-ruc', args=[numero]), **(headers or self.h))

    # 11: requiere autenticación
    def test_requiere_autenticacion(self):
        self.assertEqual(self.get(RUC_DEMO_ACTIVO).status_code, 401)

    # 12: permisos (solo ADMIN de la empresa activa)
    def test_permisos(self):
        self.client.force_authenticate(user=self.lector)
        self.assertEqual(self.get(RUC_DEMO_ACTIVO).status_code, 403)
        self.client.force_authenticate(user=self.admin)
        r = self.get(RUC_DEMO_ACTIVO)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['datos']['razon_social'], 'EMPRESA FICTICIA DEMO S.A.C.')

    # 17: multiempresa (no puede operar con una empresa ajena) y la respuesta no trae datos internos
    def test_multiempresa(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.get(RUC_DEMO_ACTIVO, headers={'HTTP_X_EMPRESA_ID': str(self.otra.id)}).status_code, 403)
        # Consultar el RUC de otra empresa del sistema NO devuelve sus datos internos (solo la fuente).
        r = self.get(self.otra.ruc)
        self.assertEqual((r.status_code, r.data['codigo']), (404, 'RUC_NO_ENCONTRADO'))
        self.assertNotIn('OTRA 17C', r.content.decode())

    def test_codigos_de_error(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual((self.get('123').status_code, self.get('123').data['codigo']), (400, 'RUC_INVALIDO'))
        r = self.get(RUC_DEMO_CAIDO)
        self.assertEqual((r.status_code, r.data['codigo']), (503, 'SERVICIO_NO_DISPONIBLE'))
        with override_settings(CONSULTA_RUC_PROVEEDOR=''):
            r = self.get(RUC_DEMO_ACTIVO)
        self.assertEqual((r.status_code, r.data['codigo']), (503, 'PROVEEDOR_RUC_NO_CONFIGURADO'))
        self.assertEqual(set(r.data), {'codigo', 'mensaje'})  # sin trazas

    # 13: no expone secretos
    @override_settings(SUNAT_USUARIO_SOL=Secreto('20100100100SOLFALSO'), SUNAT_CLAVE_SOL=Secreto('ClaveSolFalsa-17C'),
                       SUNAT_CERTIFICADO_PASSWORD=Secreto('PfxFalso-17C'))
    def test_no_expone_secretos(self):
        self.client.force_authenticate(user=self.admin)
        for numero in (RUC_DEMO_ACTIVO, RUC_DEMO_CAIDO, '123'):
            texto = self.get(numero).content.decode()
            for prohibido in ('SOLFALSO', 'ClaveSolFalsa', 'PfxFalso', 'Traceback', 'password', 'clave_sol', 'token'):
                self.assertNotIn(prohibido, texto)

    # 16: auditoría (útil: RUC, resultado, usuario; sin la respuesta completa)
    def test_auditoria(self):
        self.client.force_authenticate(user=self.admin)
        self.get(RUC_DEMO_ACTIVO)
        self.get(RUC_DEMO_ACTIVO)  # desde caché
        self.get(ruc('2077777701'))  # no encontrado
        self.get('123')  # inválido: no es una consulta, no se audita
        auds = list(Auditoria.objects.filter(accion='CONSULTA_RUC').order_by('id'))
        self.assertEqual([(a.valor_nuevo['ruc'], a.valor_nuevo['resultado'], a.valor_nuevo['desde_cache']) for a in auds],
                         [(RUC_DEMO_ACTIVO, 'EXITO', False), (RUC_DEMO_ACTIVO, 'EXITO', True),
                          (ruc('2077777701'), 'RUC_NO_ENCONTRADO', None)])
        self.assertTrue(all(a.usuario_id == self.admin.id and a.empresa_id == self.empresa.id for a in auds))
        self.assertNotIn('razon_social', json.dumps([a.valor_nuevo for a in auds]))

    def test_limite_de_uso(self):
        self.client.force_authenticate(user=self.admin)
        with override_settings(CONSULTA_RUC_THROTTLE_RATE='2/min'):
            codigos = [self.get(RUC_DEMO_ACTIVO).status_code for _ in range(3)]
        self.assertEqual(codigos, [200, 200, 429])

    # 18 (integración pre-SUNAT): consulta → aplicar en datos fiscales → validación existente
    def test_integracion_con_validacion_del_emisor(self):
        self.client.force_authenticate(user=self.admin)
        self.assertFalse(validar_emisor(self.empresa)[0] == [])
        datos = self.get(RUC_DEMO_ACTIVO).data['datos']
        aplicar = {k: datos[k] for k in ('razon_social', 'nombre_comercial', 'direccion', 'ubigeo', 'departamento',
                                         'provincia', 'distrito') if datos[k]}
        r = self.client.patch(reverse('empresa-datos-fiscales'), aplicar, format='json', **self.h)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['validacion']['listo'], r.data['ubigeo'], r.data['ruc']),
                         (True, '150101', self.empresa.ruc))  # el RUC de la empresa no cambia
