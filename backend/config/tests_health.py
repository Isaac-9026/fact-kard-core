"""Bloque 8 — health check: 200 sano, 503 sin PostgreSQL o sin caché, sin datos sensibles."""
import json
from unittest import mock

from django.conf import settings
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_sano_200_sin_autenticacion(self):
        resp = self.client.get('/api/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'ok', 'database': 'ok', 'cache': 'ok'})
        self.assertIn('no-cache', resp['Cache-Control'])

    def test_postgresql_caido_503(self):
        with mock.patch('config.health.connection.cursor', side_effect=OperationalError('host=10.0.0.5 password=x')):
            with self.assertLogs('fact_kard.health', level='ERROR'):
                resp = self.client.get('/api/health/')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json(), {'status': 'error', 'database': 'error', 'cache': 'ok'})
        self.assertNotIn('10.0.0.5', resp.content.decode())
        self.assertNotIn('password', resp.content.decode())

    def test_cache_caida_503(self):
        with mock.patch('config.health.cache.set', side_effect=ConnectionError('redis://:clave@127.0.0.1')):
            with self.assertLogs('fact_kard.health', level='ERROR'):
                resp = self.client.get('/api/health/')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()['cache'], 'error')
        self.assertNotIn('clave', resp.content.decode())

    def test_no_expone_configuracion_sensible(self):
        cuerpo = self.client.get('/api/health/').content.decode()
        for secreto in [settings.SECRET_KEY, settings.DATABASES['default']['PASSWORD'],
                        settings.DATABASES['default']['NAME'], 'Django', 'PostgreSQL']:
            if secreto:
                self.assertNotIn(str(secreto), cuerpo)
        self.assertEqual(set(json.loads(cuerpo)), {'status', 'database', 'cache'})

    def test_solo_get(self):
        self.assertEqual(self.client.post('/api/health/').status_code, 405)

    @override_settings(ALLOWED_HOSTS=['sistema.ejemplo.test'])
    def test_respeta_allowed_hosts(self):
        self.assertEqual(self.client.get('/api/health/', HTTP_HOST='sistema.ejemplo.test').status_code, 200)
