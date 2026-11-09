"""
Bloque 6 — seguridad de tokens: revocación en logout, usuario desactivado, duración
configurable, throttling de login y respuesta que no revela si el usuario existe.
"""
import time
from unittest import mock

from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.usuarios.authentication import TOKEN_SALT
from apps.usuarios.models import TokenRevocado, Usuario

CLAVE = 'ClaveSegura-2026!'


class TokensTests(TestCase):
    def setUp(self):
        cache.clear()  # contador del throttling
        self.usuario = Usuario(username='qa_tokens', email='qa_tokens@test.pe')
        self.usuario.set_password(CLAVE)
        self.usuario.save()
        self.client = APIClient()

    def login(self, username='qa_tokens', password=CLAVE):
        return self.client.post(reverse('usuarios:login'), {'username': username, 'password': password}, format='json')

    def me(self, token):
        return self.client.get(reverse('usuarios:me'), HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_token_despues_de_logout_no_sirve(self):
        token = self.login().data['token']
        otro = self.login().data['token']  # otra sesión del mismo usuario
        self.assertEqual(self.me(token).status_code, 200)
        resp = self.client.post(reverse('usuarios:logout'), HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(self.me(token).status_code, 401)
        self.assertEqual(self.me(otro).status_code, 200)  # solo se revoca la sesión cerrada
        self.assertEqual(TokenRevocado.objects.filter(usuario=self.usuario).count(), 1)
        # Logout repetido con el token revocado: 401, sin error de servidor.
        self.assertEqual(self.client.post(reverse('usuarios:logout'), HTTP_AUTHORIZATION=f'Bearer {token}').status_code, 401)

    def test_usuario_desactivado_no_puede_seguir_usando_su_token(self):
        token = self.login().data['token']
        Usuario.objects.filter(pk=self.usuario.pk).update(activo=False)
        self.assertEqual(self.me(token).status_code, 401)

    def test_token_sin_identificador_anterior_al_bloque_6_se_rechaza(self):
        legado = signing.dumps({'user_id': self.usuario.id, 'username': 'qa_tokens'}, salt=TOKEN_SALT)
        self.assertEqual(self.me(legado).status_code, 401)

    @override_settings(TOKEN_MAX_AGE_SECONDS=60)
    def test_duracion_configurable(self):
        token = self.login().data['token']
        self.assertEqual(self.me(token).status_code, 200)
        ahora = time.time()
        with mock.patch('django.core.signing.time.time', return_value=ahora + 120):
            resp = self.me(token)
        self.assertEqual(resp.status_code, 401)
        self.assertIn('expirado', str(resp.data))

    def test_credenciales_incorrectas_no_revelan_si_el_usuario_existe(self):
        inexistente = self.login(username='no_existe_qa', password='x')
        clave_mala = self.login(password='otra')
        self.assertEqual((inexistente.status_code, inexistente.data), (clave_mala.status_code, clave_mala.data))
        self.assertEqual(inexistente.status_code, 401)
        # Usuario inactivo con clave incorrecta: mismo 401 genérico (antes 403 revelaba la cuenta).
        Usuario.objects.filter(pk=self.usuario.pk).update(activo=False)
        inactivo = self.login(password='otra')
        self.assertEqual((inactivo.status_code, inactivo.data), (401, clave_mala.data))
        self.assertEqual(self.login().status_code, 403)  # con la clave correcta sí se informa

    @override_settings(LOGIN_THROTTLE_RATE='3/min')
    def test_login_repetido_se_limita(self):
        codigos = [self.login(password='mala').status_code for _ in range(3)]
        self.assertEqual(codigos, [401, 401, 401])
        bloqueado = self.login()  # incluso con la clave correcta, hasta que pase la ventana
        self.assertEqual(bloqueado.status_code, 429)
        self.assertNotIn('qa_tokens', str(bloqueado.data))
