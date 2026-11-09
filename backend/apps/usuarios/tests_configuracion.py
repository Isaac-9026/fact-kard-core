"""
Regresión SEC-001: configuración segura de SECRET_KEY, ALLOWED_HOSTS y CORS,
y rechazo de tokens firmados con la clave pública anterior.
"""
import tempfile
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.usuarios.authentication import TOKEN_SALT, generar_token
from apps.usuarios.models import Usuario
from config.seguridad import (
    SECRET_KEYS_INSEGURAS,
    resolver_secret_key,
    validar_allowed_hosts,
)

CLAVE_PUBLICA_ANTERIOR = 'django-insecure-fact-kard-secret-key-change-in-prod'
CLAVE_FUERTE = 'k' * 20 + 'Z9$x' * 10


class ResolverSecretKeyTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self.tmp.name) / '.secret_key.dev'

    def tearDown(self):
        self.tmp.cleanup()

    def _resolver(self, valor, debug=False, tests=False):
        return resolver_secret_key(
            valor=valor, debug=debug, ejecutando_tests=tests, ruta_clave_dev=self.ruta,
        )

    def test_produccion_sin_secret_key_falla(self):
        with self.assertRaises(ImproperlyConfigured):
            self._resolver('')

    def test_produccion_rechaza_claves_publicadas_en_el_repo(self):
        for valor in SECRET_KEYS_INSEGURAS:
            with self.subTest(valor=valor), self.assertRaises(ImproperlyConfigured):
                self._resolver(valor)

    def test_produccion_rechaza_prefijo_django_insecure_y_claves_cortas(self):
        with self.assertRaises(ImproperlyConfigured):
            self._resolver('django-insecure-' + 'x' * 60)
        with self.assertRaises(ImproperlyConfigured):
            self._resolver('corta')

    def test_produccion_acepta_clave_fuerte(self):
        self.assertEqual(self._resolver(CLAVE_FUERTE), CLAVE_FUERTE)

    def test_desarrollo_sin_clave_genera_una_local_estable_y_no_publica(self):
        primera = self._resolver('', debug=True)
        segunda = self._resolver('', debug=True)
        self.assertEqual(primera, segunda)
        self.assertTrue(self.ruta.exists())
        self.assertNotIn(primera, SECRET_KEYS_INSEGURAS)
        self.assertGreaterEqual(len(primera), 50)

    def test_tests_sin_clave_usa_clave_efimera_sin_escribir_archivo(self):
        clave = self._resolver('', tests=True)
        self.assertGreaterEqual(len(clave), 50)
        self.assertFalse(self.ruta.exists())


class AllowedHostsTests(SimpleTestCase):
    def test_produccion_rechaza_comodin(self):
        with self.assertRaises(ImproperlyConfigured):
            validar_allowed_hosts(['*'], debug=False)

    def test_produccion_acepta_lista_explicita(self):
        self.assertEqual(
            validar_allowed_hosts(['api.ejemplo.pe', ' localhost '], debug=False),
            ['api.ejemplo.pe', 'localhost'],
        )

    def test_desarrollo_permite_comodin(self):
        self.assertEqual(validar_allowed_hosts(['*'], debug=True), ['*'])


class SettingsActivosTests(SimpleTestCase):
    def test_settings_no_usan_la_clave_publica_anterior(self):
        self.assertNotEqual(settings.SECRET_KEY, CLAVE_PUBLICA_ANTERIOR)
        self.assertNotIn(settings.SECRET_KEY, SECRET_KEYS_INSEGURAS)

    def test_cors_no_queda_abierto_sin_debug(self):
        if not settings.DEBUG:
            self.assertFalse(settings.CORS_ALLOW_ALL_ORIGINS)
        self.assertNotIn('*', settings.CORS_ALLOWED_ORIGINS)


class TokenFalsificadoTests(TestCase):
    def setUp(self):
        self.usuario = Usuario(username='admin_sec001', email='sec001@test.pe', es_admin_global=True)
        self.usuario.set_password('Clave-segura-123')
        self.usuario.save()
        self.client = APIClient()

    def test_token_firmado_con_clave_publica_anterior_es_rechazado(self):
        falsificado = signing.dumps(
            {'user_id': self.usuario.id, 'username': self.usuario.username},
            key=CLAVE_PUBLICA_ANTERIOR,
            salt=TOKEN_SALT,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {falsificado}')
        respuesta = self.client.get('/api/usuarios/me/')
        self.assertEqual(respuesta.status_code, 401)

    def test_token_legitimo_sigue_funcionando(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {generar_token(self.usuario)}')
        respuesta = self.client.get('/api/usuarios/me/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data['usuario']['username'], 'admin_sec001')
