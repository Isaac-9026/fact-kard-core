"""
Bloque 24 — auditoría de acceso (login/logout) y empresa INACTIVA en solo lectura.
"""
import json

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from django.conf import settings
from apps.auditoria.models import Auditoria
from apps.documentos.models import Documento, PagoDocumento
from apps.documentos.tests_b16_finanzas import ruc
from apps.documentos.tests_b17a_tributario import TributarioFixture
try:
    from apps.emision_electronica.models import EmisionElectronica
except ImportError:
    EmisionElectronica = None
from apps.inventario.models import Tercero
from apps.kardex.models import Movimiento, Recalculo
from apps.usuarios.models import Usuario, UsuarioEmpresa
from apps.usuarios.permissions import MENSAJE_EMPRESA_INACTIVA

CLAVE = 'Clave-Secreta-B24!'


# ---- Auditoría de login / logout ------------------------------------------------------------------
class AuditoriaAccesoTests(TestCase):
    def setUp(self):
        cache.clear()  # contador del throttling de login
        self.usuario = Usuario.objects.create(username='leo_b24', email='leo_b24@test.pe', password_hash='x')
        self.usuario.set_password(CLAVE)
        self.usuario.save()
        self.client = APIClient(HTTP_USER_AGENT='Mozilla/5.0 (Prueba B24)')

    def login(self, username, password):
        return self.client.post(reverse('usuarios:login'), {'username': username, 'password': password}, format='json')

    def accesos(self, accion):
        return list(Auditoria.objects.filter(accion=accion).order_by('id'))

    def sin_secretos(self, token=None):
        volcado = json.dumps([{'v': a.valor_nuevo, 'a': a.valor_anterior, 'm': a.motivo}
                              for a in Auditoria.objects.all()], ensure_ascii=False)
        for prohibido in (CLAVE, 'Bearer', 'Authorization', 'password', 'Cookie', 'csrftoken'):
            self.assertNotIn(prohibido, volcado)
        if token:
            self.assertNotIn(token, volcado)

    def test_login_exitoso_auditado(self):
        r = self.login('leo_b24', CLAVE)
        self.assertEqual(r.status_code, 200)
        (a,) = self.accesos('LOGIN_EXITOSO')
        self.assertEqual((a.usuario_id, a.empresa_id, a.entidad, a.registro_id), (self.usuario.id, None, 'usuario', self.usuario.id))
        self.assertEqual(a.valor_nuevo['resultado'], 'EXITOSO')
        self.assertTrue(a.valor_nuevo['ip'])
        self.assertIn('Prueba B24', a.valor_nuevo['user_agent'])
        self.sin_secretos(token=r.data.get('token'))

    def test_login_fallido_auditado_sin_revelar_si_existe(self):
        r1 = self.login('leo_b24', 'mala-clave')
        r2 = self.login('no_existe_b24', 'otra-clave')
        self.assertEqual((r1.status_code, r2.status_code), (401, 401))
        self.assertEqual(r1.data, r2.data)  # misma respuesta exista o no
        fallidos = self.accesos('LOGIN_FALLIDO')
        self.assertEqual(len(fallidos), 2)
        for a in fallidos:
            self.assertEqual((a.usuario_id, a.valor_nuevo['resultado'], a.valor_nuevo['motivo_fallo']),
                             (None, 'FALLIDO', 'CREDENCIALES'))  # la auditoría tampoco distingue
        self.assertEqual([a.valor_nuevo['username'] for a in fallidos], ['leo_b24', 'no_existe_b24'])
        self.assertFalse(self.accesos('LOGIN_EXITOSO'))
        self.sin_secretos()
        for a in fallidos:
            self.assertNotIn('mala-clave', json.dumps(a.valor_nuevo))
            self.assertNotIn('otra-clave', json.dumps(a.valor_nuevo))

    def test_username_intentado_acotado(self):
        self.login('x' * 300 + '\nINYECTADO', 'clave')
        (a,) = self.accesos('LOGIN_FALLIDO')
        self.assertLessEqual(len(a.valor_nuevo['username']), 64)
        self.assertNotIn('\n', a.valor_nuevo['username'])

    def test_usuario_inactivo_auditado(self):
        self.usuario.activo = False
        self.usuario.save(update_fields=['activo'])
        self.assertEqual(self.login('leo_b24', CLAVE).status_code, 403)
        (a,) = self.accesos('LOGIN_FALLIDO')
        self.assertEqual((a.usuario_id, a.valor_nuevo['motivo_fallo']), (self.usuario.id, 'USUARIO_INACTIVO'))

    def test_rate_limit_acota_la_auditoria(self):
        codigos = [self.login('leo_b24', f'mala-{i}').status_code for i in range(15)]
        self.assertIn(429, codigos)  # el throttling corta antes de la vista
        self.assertEqual(len(self.accesos('LOGIN_FALLIDO')), codigos.count(401))
        self.assertLess(len(self.accesos('LOGIN_FALLIDO')), 15)

    def test_logout_auditado_sin_token(self):
        token = self.login('leo_b24', CLAVE).data['token']
        cliente = APIClient(HTTP_AUTHORIZATION=f'Bearer {token}')
        r = cliente.post(reverse('usuarios:logout'))
        self.assertEqual(r.status_code, 204)
        (a,) = self.accesos('LOGOUT')
        self.assertEqual((a.usuario_id, a.valor_nuevo['token_revocado']), (self.usuario.id, True))
        self.sin_secretos(token=token)
        self.assertEqual(cliente.get(reverse('usuarios:me')).status_code, 401)  # el token quedó revocado


# ---- Empresa INACTIVA ------------------------------------------------------------------------------
class EmpresaInactivaTests(TributarioFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.factura_id = self.emitir_factura()

    def inactivar(self, empresa=None):
        (empresa or self.empresa).__class__.objects.filter(pk=(empresa or self.empresa).pk).update(estado='INACTIVA')

    def assertInactiva(self, r):
        self.assertEqual(r.status_code, 403, getattr(r, 'data', r))
        self.assertEqual(str(r.data['detail']), MENSAJE_EMPRESA_INACTIVA)
        self.assertNotIn('Traceback', str(r.data))

    def test_documento_nuevo_y_anulacion_bloqueados(self):
        self.inactivar()
        antes = Documento.objects.count()
        self.assertInactiva(self.venta(serie=self.serie_f['id'], esperado=403))
        self.assertEqual(Documento.objects.count(), antes)
        r = self.client.post(reverse('documento-anular', args=[self.factura_id]), {'motivo': 'Prueba'},
                             format='json', **self.headers)
        self.assertInactiva(r)
        self.assertEqual(Documento.objects.get(pk=self.factura_id).estado, 'CONFIRMADO')

    def test_pago_bloqueado(self):
        self.inactivar()
        self.assertInactiva(self.pagar(self.factura_id, '10', esperado=403))
        self.assertFalse(PagoDocumento.objects.filter(documento_id=self.factura_id).exists())

    def test_kardex_e_inventario_bloqueados(self):
        self.inactivar()
        movimientos = Movimiento.objects.count()
        r = self.client.post(reverse('kardex-recalculos'), {'producto': self.producto.id, 'fecha_desde': '2026-01-01'},
                             format='json', **self.headers)
        self.assertInactiva(r)
        self.assertFalse(Recalculo.objects.exists())
        r = self.client.post(reverse('tercero-list-create'), {'tipo_documento': '6', 'numero_documento': ruc('2060333333'),
                                                              'razon_social': 'NUEVO', 'es_cliente': True},
                             format='json', **self.headers)
        self.assertInactiva(r)
        self.assertEqual(Movimiento.objects.count(), movimientos)

    def test_cierre_y_configuracion_bloqueados(self):
        self.inactivar()
        periodo = Documento.objects.get(pk=self.factura_id).periodo_id
        self.assertInactiva(self.client.post(reverse('periodo-cerrar', args=[periodo]), {}, format='json', **self.headers))
        self.assertInactiva(self.client.patch(reverse('empresa-config'), {'decimales_calculo': 4}, format='json',
                                              **self.headers))
        self.assertInactiva(self.client.patch(reverse('empresa-detail', args=[self.empresa.id]),
                                              {'razon_social': 'CAMBIO'}, format='json', **self.headers))

    def test_emision_electronica_bloqueada(self):
        if 'apps.emision_electronica' not in settings.INSTALLED_APPS:
            return
        self.inactivar()
        for nombre in ('documento-preparar-emision', 'documento-generar-xml', 'documento-firmar-xml',
                       'documento-enviar-sunat', 'documento-generar-pdf'):
            with self.subTest(nombre=nombre):
                self.assertInactiva(self.client.post(reverse(nombre, args=[self.factura_id]), {}, format='json',
                                                     **self.headers))
        self.assertFalse(EmisionElectronica.objects.filter(documento_id=self.factura_id).exists())

    def test_consulta_historica_permitida(self):
        self.inactivar()
        for url in (reverse('documento-list-create'), reverse('documento-detail', args=[self.factura_id]),
                    reverse('kardex-movimientos'), reverse('pago-documento-list-create'),
                    reverse('producto-list-create'), reverse('auditoria:auditoria-list')):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, **self.headers).status_code, 200)

    def test_otra_empresa_activa_del_mismo_usuario_funciona(self):
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=self.otra_empresa, rol='ADMIN')
        self.inactivar()
        headers_b = {'HTTP_X_EMPRESA_ID': str(self.otra_empresa.id)}
        r = self.client.post(reverse('tercero-list-create'), {'tipo_documento': '6', 'numero_documento': ruc('2060444444'),
                                                              'razon_social': 'CLIENTE EMPRESA B', 'es_cliente': True},
                             format='json', **headers_b)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Tercero.objects.get(pk=r.data['id']).empresa_id, self.otra_empresa.id)
        # Volver al contexto de la empresa inactiva: sigue en solo lectura.
        self.assertEqual(self.client.get(reverse('documento-list-create'), **self.headers).status_code, 200)
        self.assertInactiva(self.pagar(self.factura_id, '10', esperado=403))

    def test_idor_y_empresa_inexistente(self):
        # Sin asignación en la otra empresa: 403 aunque esté activa; no se confía en el header.
        r = self.client.get(reverse('documento-list-create'), HTTP_X_EMPRESA_ID=str(self.otra_empresa.id))
        self.assertEqual(r.status_code, 403)
        self.inactivar()
        r = self.client.get(reverse('documento-detail', args=[self.factura_id]),
                            HTTP_X_EMPRESA_ID=str(self.otra_empresa.id))
        self.assertEqual(r.status_code, 403)
        admin = Usuario.objects.create(username='global_b24', email='g_b24@test.pe', password_hash='x', es_admin_global=True)
        c = APIClient()
        c.force_authenticate(user=admin)
        self.assertEqual(c.get(reverse('documento-list-create'), HTTP_X_EMPRESA_ID='999999').status_code, 403)

    def test_reactivacion_solo_admin_global_y_auditada(self):
        url = reverse('empresa-estado', args=[self.empresa.id])
        # Un ADMIN de la empresa no puede cambiar su estado.
        self.assertEqual(self.client.post(url, {'estado': 'INACTIVA', 'motivo': 'Prueba'}, format='json').status_code, 403)
        admin = Usuario.objects.create(username='global2_b24', email='g2_b24@test.pe', password_hash='x', es_admin_global=True)
        c = APIClient()
        c.force_authenticate(user=admin)
        self.assertEqual(c.post(url, {'estado': 'INACTIVA'}, format='json').status_code, 400)  # motivo obligatorio
        r = c.post(url, {'estado': 'INACTIVA', 'motivo': 'Cese de operaciones'}, format='json')
        self.assertEqual((r.status_code, r.data['estado']), (200, 'INACTIVA'))
        self.assertInactiva(self.pagar(self.factura_id, '10', esperado=403))
        r = c.post(url, {'estado': 'ACTIVA', 'motivo': 'Reanuda operaciones'}, format='json')
        self.assertEqual((r.status_code, r.data['estado']), (200, 'ACTIVA'))
        self.pagar(self.factura_id, '10', esperado=201)
        cambios = Auditoria.objects.filter(accion='CAMBIAR_ESTADO_EMPRESA', registro_id=self.empresa.id).order_by('id')
        self.assertEqual([(a.valor_anterior['estado'], a.valor_nuevo['estado']) for a in cambios],
                         [('ACTIVA', 'INACTIVA'), ('INACTIVA', 'ACTIVA')])
        self.assertEqual(Documento.objects.filter(empresa=self.empresa).count() > 0, True)  # nada histórico se borra


# ---- Corrección Bloque 24: tipo de cambio con empresa INACTIVA -----------------------------------
class TipoCambioEmpresaInactivaTests(TributarioFixture, TestCase):
    def setUp(self):
        super().setUp()
        from apps.catalogos.models import Moneda
        Moneda.objects.get_or_create(codigo='USD', defaults={'nombre': 'Dólares'})
        self.url = reverse('tipo-cambio-list-create')

    def tc(self, fecha='2026-10-01'):
        return {'moneda_codigo': 'USD', 'fecha_publicacion': fecha, 'compra': '3.70000000', 'venta': '3.71000000',
                'fuente': 'SBS'}

    def inactivar(self, empresa):
        type(empresa).objects.filter(pk=empresa.pk).update(estado='INACTIVA')

    def test_admin_solo_de_empresa_inactiva_no_puede_registrar(self):
        from apps.catalogos.models import TipoCambio
        self.inactivar(self.empresa)
        r = self.client.post(self.url, self.tc(), format='json', **self.headers)  # con header de la inactiva
        self.assertEqual(r.status_code, 403)
        self.assertEqual(str(r.data['detail']), MENSAJE_EMPRESA_INACTIVA)
        r = self.client.post(self.url, self.tc('2026-10-02'), format='json')     # sin header
        self.assertEqual(r.status_code, 403)
        self.assertFalse(TipoCambio.objects.exists())
        self.assertEqual(self.client.get(self.url, **self.headers).status_code, 200)  # consultar sí

    def test_admin_global_mantiene_la_excepcion(self):
        self.inactivar(self.empresa)
        admin = Usuario.objects.create(username='global_tc_b24', email='gtc_b24@test.pe', password_hash='x',
                                       es_admin_global=True)
        c = APIClient()
        c.force_authenticate(user=admin)
        self.assertEqual(c.post(self.url, self.tc(), format='json', **self.headers).status_code, 201)

    def test_empresa_activa_funciona_y_otra_activa_no_se_rompe(self):
        self.assertEqual(self.client.post(self.url, self.tc(), format='json', **self.headers).status_code, 201)
        # ADMIN en una inactiva y en otra activa: desde la activa (o sin header) puede; desde la inactiva no.
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=self.otra_empresa, rol='ADMIN')
        self.inactivar(self.empresa)
        headers_b = {'HTTP_X_EMPRESA_ID': str(self.otra_empresa.id)}
        self.assertEqual(self.client.post(self.url, self.tc('2026-10-03'), format='json', **headers_b).status_code, 201)
        self.assertEqual(self.client.post(self.url, self.tc('2026-10-04'), format='json').status_code, 201)
        self.assertEqual(self.client.post(self.url, self.tc('2026-10-05'), format='json', **self.headers).status_code, 403)


# ---- Corrección Bloque 24: auditoría global (eventos sin empresa) --------------------------------
class AuditoriaGlobalTests(TributarioFixture, TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.url = reverse('auditoria:auditoria-global')
        self.global_admin = Usuario.objects.create(username='global_aud_b24', email='ga_b24@test.pe', password_hash='x',
                                                   es_admin_global=True)
        self.c_global = APIClient()
        self.c_global.force_authenticate(user=self.global_admin)
        self.leo = Usuario.objects.create(username='leo_aud_b24', email='la_b24@test.pe', password_hash='x')
        self.leo.set_password(CLAVE)
        self.leo.save()
        anon = APIClient()
        token = anon.post(reverse('usuarios:login'), {'username': 'leo_aud_b24', 'password': CLAVE}, format='json').data['token']
        anon.post(reverse('usuarios:login'), {'username': 'leo_aud_b24', 'password': 'mala'}, format='json')
        APIClient(HTTP_AUTHORIZATION=f'Bearer {token}').post(reverse('usuarios:logout'))

    def test_admin_global_consulta_eventos_globales(self):
        r = self.c_global.get(self.url)
        self.assertEqual(r.status_code, 200)
        acciones = [e['accion'] for e in r.data]
        for accion in ('LOGIN_EXITOSO', 'LOGIN_FALLIDO', 'LOGOUT'):
            self.assertIn(accion, acciones)
        self.assertTrue(all(e['empresa_id'] is None for e in r.data))
        r = self.c_global.get(self.url, {'accion': 'login_fallido'})
        self.assertEqual({e['accion'] for e in r.data}, {'LOGIN_FALLIDO'})
        r = self.c_global.get(self.url, {'usuario': self.leo.id})
        self.assertEqual({e['accion'] for e in r.data}, {'LOGIN_EXITOSO', 'LOGOUT'})
        self.assertEqual(self.c_global.get(self.url, {'usuario': 'x'}).status_code, 400)
        r = self.c_global.get(self.url, {'page': 1, 'page_size': 2})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['results']), 2)
        self.assertNotIn(CLAVE, json.dumps(r.data, default=str))

    def test_admin_normal_y_usuario_no_pueden(self):
        self.assertEqual(self.client.get(self.url, **self.headers).status_code, 403)  # ADMIN de empresa
        lector = APIClient()
        lector.force_authenticate(user=self.leo)
        self.assertEqual(lector.get(self.url).status_code, 403)
        self.assertIn(APIClient().get(self.url).status_code, (401, 403))

    def test_eventos_globales_no_se_mezclan_con_la_auditoria_de_empresa(self):
        r = self.client.get(reverse('auditoria:auditoria-list'), **self.headers)
        self.assertEqual(r.status_code, 200)
        filas = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertFalse({'LOGIN_EXITOSO', 'LOGIN_FALLIDO', 'LOGOUT'} & {e['accion'] for e in filas})
        self.assertTrue(all(e['empresa_id'] == self.empresa.id for e in filas))
        # Y la vista global no devuelve eventos de empresas.
        self.assertFalse(any(e['empresa_id'] for e in self.c_global.get(self.url).data))
        self.assertTrue(Auditoria.objects.filter(empresa=self.empresa).exists())
