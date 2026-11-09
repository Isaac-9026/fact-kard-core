"""
Bloque 7 — configuración de producción: caché compatible con Redis, validaciones que
bloquean una configuración insegura, advertencias de despliegue y sesión por cookie
HttpOnly (preparada, desactivada por defecto).
"""
import os
from unittest import skipUnless

from django.core.cache import cache
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.usuarios.models import TokenRevocado, Usuario
from config.cache import BACKEND_LOCAL, BACKEND_REDIS, configurar_caches
from config.seguridad import validar_configuracion_produccion

CLAVE = 'ClaveSegura-2026!'


class SecretKeyBloque7Tests(SimpleTestCase):
    def test_clave_larga_con_pocos_caracteres_distintos_se_rechaza_en_produccion(self):
        from pathlib import Path
        from config.seguridad import resolver_secret_key
        with self.assertRaises(ImproperlyConfigured):
            resolver_secret_key(valor='x9Z!' * 20, debug=False, ejecutando_tests=False, ruta_clave_dev=Path('/nonexistent'))


class CacheTests(SimpleTestCase):
    def test_sin_url_usa_memoria_local_sin_redis(self):
        caches = configurar_caches('', redis_disponible=lambda: False)
        self.assertEqual(caches['default']['BACKEND'], BACKEND_LOCAL)

    def test_url_redis(self):
        caches = configurar_caches('redis://cache.interno:6379/1', prefijo='fk-prod', redis_disponible=lambda: True)
        self.assertEqual(caches['default'], {
            'BACKEND': BACKEND_REDIS, 'LOCATION': 'redis://cache.interno:6379/1', 'KEY_PREFIX': 'fk-prod',
        })
        self.assertEqual(configurar_caches('rediss://h:6380/0', redis_disponible=lambda: True)['default']['BACKEND'],
                         BACKEND_REDIS)

    def test_redis_sin_paquete_o_url_invalida_falla_al_arrancar(self):
        with self.assertRaisesRegex(ImproperlyConfigured, 'requirements-prod'):
            configurar_caches('redis://h:6379/0', redis_disponible=lambda: False)
        with self.assertRaisesRegex(ImproperlyConfigured, 'Redis'):
            configurar_caches('memcached://h:11211', redis_disponible=lambda: True)


BASE_PROD = dict(
    debug=False, token_max_age=8 * 3600, cors_origins=['https://app.ejemplo.test'],
    csrf_trusted_origins=['https://app.ejemplo.test'], session_cookie_secure=True, csrf_cookie_secure=True,
    sin_https=False, auth_cookie_enabled=False, auth_cookie_secure=True, auth_cookie_samesite='Lax',
)


class ValidacionProduccionTests(SimpleTestCase):
    def validar(self, **cambios):
        validar_configuracion_produccion(**{**BASE_PROD, **cambios})

    def test_configuracion_segura_pasa(self):
        self.validar()
        self.validar(cors_origins=['http://localhost:5173'])  # orígenes locales permitidos

    def test_configuraciones_inseguras_se_rechazan(self):
        casos = [
            ({'token_max_age': 0}, 'mayor que 0'),
            ({'token_max_age': 60 * 60 * 24 * 90}, '30 días'),
            ({'cors_origins': ['*']}, "'\\*'"),
            ({'session_cookie_secure': False}, 'SESSION_COOKIE_SECURE'),
            ({'csrf_cookie_secure': False}, 'CSRF_COOKIE_SECURE'),
            ({'cors_origins': ['http://app.ejemplo.test']}, 'http://'),
            ({'csrf_trusted_origins': ['http://app.ejemplo.test']}, 'http://'),
            ({'auth_cookie_enabled': True, 'auth_cookie_secure': False}, 'AUTH_COOKIE_SECURE'),
            ({'auth_cookie_samesite': 'lax'}, 'AUTH_COOKIE_SAMESITE'),
            ({'auth_cookie_enabled': True, 'auth_cookie_samesite': 'None', 'auth_cookie_secure': False}, 'None'),
        ]
        for cambios, texto in casos:
            with self.subTest(cambios=cambios):
                with self.assertRaisesRegex(ImproperlyConfigured, texto):
                    self.validar(**cambios)

    def test_todos_los_errores_en_un_solo_mensaje(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            self.validar(token_max_age=-1, session_cookie_secure=False, cors_origins=['*'])
        self.assertEqual(str(ctx.exception).count('|'), 2)

    def test_intranet_sin_https_es_una_excepcion_explicita(self):
        self.validar(sin_https=True, session_cookie_secure=False, csrf_cookie_secure=False,
                     cors_origins=['http://192.168.1.20:8080'])
        with self.assertRaises(ImproperlyConfigured):  # lo demás se sigue validando
            self.validar(sin_https=True, cors_origins=['*'])

    def test_desarrollo_no_exige_https(self):
        self.validar(debug=True, session_cookie_secure=False, cors_origins=['http://lan.local:5173'],
                     token_max_age=60 * 60 * 24 * 90)
        with self.assertRaises(ImproperlyConfigured):
            self.validar(debug=True, token_max_age=0)


class AdvertenciasDespliegueTests(SimpleTestCase):
    def ids(self):
        return {m.id for m in run_checks(include_deployment_checks=True) if m.id.startswith('fact_kard.')}

    @override_settings(CACHES={'default': {'BACKEND': BACKEND_LOCAL}}, TOKEN_MAX_AGE_SECONDS=7 * 86400,
                       PRODUCCION_SIN_HTTPS=True)
    def test_avisos(self):
        self.assertEqual(self.ids(), {'fact_kard.W001', 'fact_kard.W002', 'fact_kard.W003'})

    @override_settings(CACHES={'default': {'BACKEND': BACKEND_REDIS, 'LOCATION': 'redis://h:6379/0'}},
                       TOKEN_MAX_AGE_SECONDS=8 * 3600, PRODUCCION_SIN_HTTPS=False)
    def test_sin_avisos_con_redis_y_token_corto(self):
        self.assertEqual(self.ids(), set())


class _ConUsuario(TestCase):
    def setUp(self):
        cache.clear()
        self.usuario = Usuario(username='qa_b7', email='qa_b7@test.pe')
        self.usuario.set_password(CLAVE)
        self.usuario.save()
        self.client = APIClient(enforce_csrf_checks=True)

    def login(self):
        return self.client.post(reverse('usuarios:login'), {'username': 'qa_b7', 'password': CLAVE}, format='json')


class SesionPorDefectoTests(_ConUsuario):
    def test_sin_cookie_el_login_sigue_devolviendo_el_token(self):
        resp = self.login()
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.data)
        self.assertNotIn('fk_sesion', resp.cookies)

    def test_una_cookie_no_autentica_si_el_modo_cookie_esta_apagado(self):
        token = self.login().data['token']
        self.client.cookies['fk_sesion'] = token
        self.assertEqual(self.client.get(reverse('usuarios:me')).status_code, 401)


@override_settings(AUTH_COOKIE_ENABLED=True, AUTH_COOKIE_SECURE=True, AUTH_COOKIE_SAMESITE='Lax')
class SesionPorCookieTests(_ConUsuario):
    def test_login_emite_cookie_httponly_y_no_devuelve_token(self):
        resp = self.login()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('token', resp.data)  # no hay un segundo token accesible desde JS
        cookie = resp.cookies['fk_sesion']
        self.assertTrue(cookie['httponly'])
        self.assertTrue(cookie['secure'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(cookie['path'], '/api/')
        self.assertIn('csrftoken', resp.cookies)  # token CSRF nuevo tras el login

    def test_lectura_con_cookie_y_escritura_exige_csrf(self):
        self.login()
        self.assertEqual(self.client.get(reverse('usuarios:me')).status_code, 200)
        sin_csrf = self.client.post(reverse('usuarios:logout'))
        self.assertEqual(sin_csrf.status_code, 403)
        self.assertIn('CSRF', str(sin_csrf.data))
        csrf = self.client.get(reverse('usuarios:csrf')).data['csrfToken']
        resp = self.client.post(reverse('usuarios:logout'), HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.cookies['fk_sesion'].value, '')  # cookie borrada
        self.assertEqual(TokenRevocado.objects.filter(usuario=self.usuario).count(), 1)

    def test_token_revocado_en_cookie_no_sirve(self):
        self.login()
        token = self.client.cookies['fk_sesion'].value
        csrf = self.client.get(reverse('usuarios:csrf')).data['csrfToken']
        self.client.post(reverse('usuarios:logout'), HTTP_X_CSRFTOKEN=csrf)
        self.client.cookies['fk_sesion'] = token  # alguien reutiliza la cookie copiada
        self.assertEqual(self.client.get(reverse('usuarios:me')).status_code, 401)

    def test_clientes_de_api_con_encabezado_siguen_funcionando_sin_csrf(self):
        from apps.usuarios.authentication import generar_token
        token = generar_token(self.usuario)
        cliente = APIClient(enforce_csrf_checks=True)
        self.assertEqual(cliente.post(reverse('usuarios:logout'), HTTP_AUTHORIZATION=f'Bearer {token}').status_code, 204)


@skipUnless(os.environ.get('TEST_REDIS_URL'), 'Define TEST_REDIS_URL=redis://... para probar con un Redis real.')
class ThrottlingConRedisTests(_ConUsuario):
    def test_login_limitado_con_contador_en_redis(self):
        caches = configurar_caches(os.environ['TEST_REDIS_URL'], prefijo='fk-test-b7')
        with override_settings(CACHES=caches, LOGIN_THROTTLE_RATE='2/min'):
            from django.core.cache import caches as todas
            todas['default'].clear()
            from rest_framework.throttling import SimpleRateThrottle
            anterior = SimpleRateThrottle.cache
            SimpleRateThrottle.cache = todas['default']
            try:
                malos = [self.client.post(reverse('usuarios:login'), {'username': 'qa_b7', 'password': 'x'},
                                          format='json').status_code for _ in range(2)]
                self.assertEqual(malos, [401, 401])
                self.assertEqual(self.login().status_code, 429)
            finally:
                SimpleRateThrottle.cache = anterior
                todas['default'].clear()
