"""
Seguridad interna del Core (roles y contraseñas):

1. Rol CONSULTA: solo lectura en todo el API (ve y exporta, no modifica).
2. Confirmar con contraseña: anular comprobante, reabrir período y recalcular Kardex.
3. Sesión de 8 horas por defecto.
4. Contraseña segura (10+ caracteres, no común, no solo números, no parecida al usuario)
   y bloqueo de la cuenta 15 minutos tras 5 intentos fallidos.
"""
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento
from apps.kardex.models import Recalculo
from apps.usuarios.authentication import generar_token
from apps.usuarios.models import Usuario, UsuarioEmpresa

CLAVE = 'Clave-Segura-2026'


class RolConsultaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.consulta = Usuario.objects.create(username='dueno_consulta', email='dueno@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=self.consulta, empresa=self.empresa, rol='CONSULTA')
        self.cliente_consulta = APIClient()
        self.cliente_consulta.force_authenticate(user=self.consulta)

    def test_puede_ver_reportes(self):
        resp = self.cliente_consulta.get(reverse('kardex-report'), **self.headers)
        self.assertEqual(resp.status_code, 200)
        resp = self.cliente_consulta.get(reverse('kardex-excel-export'), **self.headers)
        self.assertEqual(resp.status_code, 200)

    def test_no_puede_registrar_ni_modificar(self):
        antes = Documento.objects.count()
        resp = self.cliente_consulta.post(
            reverse('documento-list-create'), self.payload('VENTA', [self.linea('VENTA', '1', '10')]),
            format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data['code'], 'solo_consulta')
        self.assertEqual(Documento.objects.count(), antes)

    def test_admin_global_puede_asignar_rol_consulta(self):
        global_admin = Usuario.objects.create(username='estudio', email='estudio@test.pe', password_hash='x',
                                              es_admin_global=True)
        cliente = APIClient()
        cliente.credentials(HTTP_AUTHORIZATION=f'Bearer {generar_token(global_admin)}')
        resp = cliente.post(reverse('usuarios:usuario-list-create'), {
            'username': 'contador_externo', 'email': 'contador@test.pe', 'password_inicial': 'Revision-Mensual-26',
            'asignaciones': [{'empresa_id': self.empresa.id, 'rol': 'CONSULTA', 'activo': True}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(UsuarioEmpresa.objects.get(usuario__username='contador_externo').rol, 'CONSULTA')


class ConfirmacionPasswordTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.doc = self.compra_confirmada('10', '10')

    def anular_con(self, **extra):
        return self.client.post(reverse('documento-anular', args=[self.doc]), {'motivo': 'Prueba', **extra},
                                format='json', **self.headers)

    def test_anular_sin_contrasena_se_rechaza(self):
        resp = self.anular_con()
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data['code'], 'confirmacion_password')
        self.assertEqual(Documento.objects.get(pk=self.doc).estado, 'CONFIRMADO')

    def test_anular_con_contrasena_incorrecta_se_rechaza(self):
        resp = self.anular_con(password_confirmacion='no-es-la-clave')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Documento.objects.get(pk=self.doc).estado, 'CONFIRMADO')

    def test_anular_con_contrasena_correcta(self):
        resp = self.anular_con(password_confirmacion=self.PASSWORD_PRUEBAS)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(Documento.objects.get(pk=self.doc).estado, 'ANULADO')

    def test_recalcular_exige_contrasena(self):
        datos = {'producto': self.producto.id, 'fecha_desde': '2026-01-01'}
        resp = self.client.post(reverse('kardex-recalculos'), datos, format='json', **self.headers)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Recalculo.objects.exists())
        resp = self.client.post(reverse('kardex-recalculos'), {**datos, 'password_confirmacion': self.PASSWORD_PRUEBAS},
                                format='json', **self.headers)
        self.assertEqual(resp.status_code, 201, resp.data)


class SesionYContrasenaTests(TestCase):
    def setUp(self):
        cache.clear()  # el throttling de login usa la caché
        self.usuario = Usuario.objects.create(username='operador', email='operador@test.pe', password_hash='x')
        self.usuario.set_password(CLAVE)
        self.usuario.save()
        self.client = APIClient()

    def login(self, password):
        return self.client.post(reverse('usuarios:login'), {'username': 'operador', 'password': password}, format='json')

    def test_sesion_de_8_horas_por_defecto(self):
        self.assertLessEqual(settings.TOKEN_MAX_AGE_SECONDS, 8 * 60 * 60)

    def test_cinco_intentos_fallidos_bloquean_la_cuenta(self):
        for _ in range(5):
            self.assertEqual(self.login('mala-clave').status_code, 401)
        resp = self.login(CLAVE)  # aun con la clave correcta
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data['code'], 'cuenta_bloqueada')
        self.usuario.refresh_from_db()
        self.assertGreater(self.usuario.bloqueado_hasta, timezone.now() + timedelta(minutes=14))

    def test_pasado_el_bloqueo_entra_y_reinicia_el_conteo(self):
        Usuario.objects.filter(pk=self.usuario.pk).update(
            intentos_fallidos=3, bloqueado_hasta=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.login(CLAVE).status_code, 200)
        self.usuario.refresh_from_db()
        self.assertEqual((self.usuario.intentos_fallidos, self.usuario.bloqueado_hasta), (0, None))

    def test_reseteo_del_admin_desbloquea(self):
        Usuario.objects.filter(pk=self.usuario.pk).update(bloqueado_hasta=timezone.now() + timedelta(minutes=15))
        admin = Usuario.objects.create(username='estudio', email='estudio@test.pe', password_hash='x',
                                       es_admin_global=True)
        cliente = APIClient()
        cliente.credentials(HTTP_AUTHORIZATION=f'Bearer {generar_token(admin)}')
        resp = cliente.post(reverse('usuarios:usuario-reset-password', args=[self.usuario.pk]),
                            {'password_nuevo': 'Nueva-Clave-Segura-1'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.login('Nueva-Clave-Segura-1').status_code, 200)

    def test_contrasenas_debiles_se_rechazan(self):
        token = generar_token(self.usuario)
        cliente = APIClient()
        cliente.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        for debil in ('Corta-1', '1234567890123', 'password1234', 'operador2026'):
            with self.subTest(debil=debil):
                resp = cliente.post(reverse('usuarios:cambiar-password'),
                                    {'password_actual': CLAVE, 'password_nuevo': debil}, format='json')
                self.assertEqual(resp.status_code, 400, debil)
        resp = cliente.post(reverse('usuarios:cambiar-password'),
                            {'password_actual': CLAVE, 'password_nuevo': 'Inventario-Mensual-26'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
