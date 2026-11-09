"""
Bloque 10 — hallazgos del ensayo de staging.

B10-03: con Redis caído el login respondía 500 (traza en el log). Ahora es 503 controlado,
sigue rechazando el acceso (fail-closed) y no afecta a las sesiones ya abiertas.
"""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.usuarios.authentication import LoginRateThrottle, generar_token
from apps.usuarios.models import Usuario

CLAVE = 'ClaveSegura-2026!'


class CacheCaida:
    def get(self, *args, **kwargs):
        raise ConnectionError('Error 111 connecting to 127.0.0.1:6379. Connection refused.')

    set = get


class LoginSinCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.usuario = Usuario(username='qa_b10', email='qa_b10@test.pe')
        self.usuario.set_password(CLAVE)
        self.usuario.save()
        self.client = APIClient()

    def login(self, password=CLAVE):
        return self.client.post(reverse('usuarios:login'), {'username': 'qa_b10', 'password': password}, format='json')

    def test_cache_caida_responde_503_sin_iniciar_sesion(self):
        with mock.patch.object(LoginRateThrottle, 'cache', CacheCaida()), \
                self.assertLogs('fact_kard.auth', level='ERROR') as logs:
            resp = self.login()
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['detail'].code, 'login_no_disponible')
        self.assertNotIn('token', resp.data)
        self.assertNotIn('fk_sesion', resp.cookies)
        texto = '\n'.join(logs.output)
        self.assertIn('caché del límite de intentos no disponible (ConnectionError)', texto)
        self.assertNotIn(CLAVE, texto)
        self.assertNotIn('6379', texto)

    def test_cache_caida_no_afecta_sesiones_abiertas(self):
        token = generar_token(self.usuario)
        with mock.patch.object(LoginRateThrottle, 'cache', CacheCaida()):
            resp = self.client.get(reverse('usuarios:me'), HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(resp.status_code, 200)

    def test_cache_disponible_sigue_igual(self):
        self.assertEqual(self.login(password='mala').status_code, 401)
        self.assertEqual(self.login().status_code, 200)
