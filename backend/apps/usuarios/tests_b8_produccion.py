"""
Bloque 8 — logs seguros, IP real detrás de Nginx para el throttling, documentación de la
API apagada por defecto y validaciones adicionales de producción.
"""
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from apps.usuarios.authentication import LoginRateThrottle
from apps.usuarios.models import Usuario
from config.registro import ENMASCARADO, FiltroDatosSensibles, construir_logging, enmascarar
from config.seguridad import permisos_docs_api, resolver_docs_api, validar_configuracion_produccion

CLAVE = 'ClaveSegura-2026!'
TOKEN = 'eyJ1c2VyX2lkIjoxLCJqdGkiOiJhYmMifQ:1vXyZq:Q2xhdmVGaXJtYWRhRGVQcnVlYmExMjM0NTY3OA'


class EnmascaradoTests(SimpleTestCase):
    def test_tokens_contrasenas_y_urls(self):
        casos = [
            (f'Authorization: Bearer {TOKEN}', TOKEN),
            (f'token recibido {TOKEN}', TOKEN),
            ('password=MiClave123 user=ana', 'MiClave123'),
            ('{"username": "ana", "password": "MiClave123"}', 'MiClave123'),
            ('DB_PASSWORD: supersecreta', 'supersecreta'),
            ('fallo redis://:claveRedis@127.0.0.1:6379/0', 'claveRedis'),
            ('postgres://fk:claveBD@localhost/fact_kard', 'claveBD'),
        ]
        for texto, secreto in casos:
            with self.subTest(texto=texto):
                limpio = enmascarar(texto)
                self.assertNotIn(secreto, limpio)
                self.assertIn(ENMASCARADO, limpio)
        self.assertEqual(enmascarar('Login correcto: usuario id=3 ip=1.2.3.4'), 'Login correcto: usuario id=3 ip=1.2.3.4')

    def test_filtro_oculta_secret_key_en_mensaje_y_traza(self):
        registro = logging.LogRecord('fact_kard', logging.ERROR, __file__, 1, 'clave %s', (settings.SECRET_KEY,), None)
        try:
            raise ValueError(f'conexión con password={settings.SECRET_KEY}')
        except ValueError:
            import sys
            registro.exc_info = sys.exc_info()
        FiltroDatosSensibles().filter(registro)
        self.assertNotIn(settings.SECRET_KEY, registro.getMessage())
        self.assertNotIn(settings.SECRET_KEY, registro.exc_text)

    def test_configuracion_con_archivo_rotativo(self):
        conf = construir_logging(nivel='INFO', archivo='/var/log/fact-kard/app.log', max_mb=5, respaldos=3)
        self.assertEqual(conf['handlers']['archivo']['class'], 'logging.handlers.RotatingFileHandler')
        self.assertEqual(conf['handlers']['archivo']['maxBytes'], 5 * 1024 * 1024)
        self.assertEqual(conf['loggers']['django.request']['level'], 'WARNING')
        self.assertEqual(conf['loggers']['django.db.backends']['level'], 'WARNING')  # sin SQL
        self.assertNotIn('archivo', construir_logging()['handlers'])  # por defecto: stdout/journald


class EventosAutenticacionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.usuario = Usuario(username='qa_logs', email='qa_logs@test.pe')
        self.usuario.set_password(CLAVE)
        self.usuario.save()
        self.client = APIClient()

    def login(self, password=CLAVE, **extra):
        return self.client.post(reverse('usuarios:login'), {'username': 'qa_logs', 'password': password}, format='json', **extra)

    def test_login_logout_y_fallos_se_registran_sin_secretos(self):
        with self.assertLogs('fact_kard.auth', level='INFO') as logs:
            self.login(password='ClaveEquivocada!')
            token = self.login().data['token']
            self.client.post(reverse('usuarios:logout'), HTTP_AUTHORIZATION=f'Bearer {token}')
        texto = '\n'.join(logs.output)
        self.assertIn('Login fallido: usuario=qa_logs existe=si', texto)
        self.assertIn(f'Login correcto: usuario id={self.usuario.id}', texto)
        self.assertIn(f'Logout: usuario id={self.usuario.id}', texto)
        for secreto in (CLAVE, 'ClaveEquivocada!', token):
            self.assertNotIn(secreto, texto)

    @override_settings(LOGIN_THROTTLE_RATE='1/min')
    def test_bloqueo_por_intentos_se_registra(self):
        with self.assertLogs('fact_kard.auth', level='WARNING') as logs:
            self.login(password='mala')
            self.assertEqual(self.login().status_code, 429)
        self.assertTrue(any('Login bloqueado por exceso de intentos' in linea for linea in logs.output))


class IpDetrasDeProxyTests(TestCase):
    """Antes (NUM_PROXIES=None) el cliente podía falsear X-Forwarded-For y evadir el límite."""

    def setUp(self):
        cache.clear()
        Usuario.objects.create(username='qa_ip', email='qa_ip@test.pe')

    def intentos(self, xffs, **extra):
        cliente = APIClient()
        return [cliente.post(reverse('usuarios:login'), {'username': 'qa_ip', 'password': 'x'}, format='json',
                             HTTP_X_FORWARDED_FOR=xff, **extra).status_code for xff in xffs]

    @override_settings(LOGIN_THROTTLE_RATE='2/min')
    def test_sin_proxy_se_ignora_x_forwarded_for(self):
        self.assertEqual(api_settings.NUM_PROXIES, 0)
        self.assertEqual(self.intentos(['1.1.1.1', '2.2.2.2', '3.3.3.3']), [401, 401, 429])

    @override_settings(LOGIN_THROTTLE_RATE='2/min')
    def test_con_nginx_se_usa_la_ip_que_agrega_el_proxy(self):
        from django.test import override_settings as ov
        rf = {**settings.REST_FRAMEWORK, 'NUM_PROXIES': 1}
        with ov(REST_FRAMEWORK=rf):
            # El atacante cambia la primera IP; Nginx siempre agrega la real al final.
            codigos = self.intentos(['1.1.1.1, 9.9.9.9', '2.2.2.2, 9.9.9.9', '3.3.3.3, 9.9.9.9'])
            self.assertEqual(codigos, [401, 401, 429])
            # Otro cliente real (otra IP agregada por Nginx) no queda bloqueado.
            self.assertEqual(self.intentos(['8.8.8.8, 7.7.7.7']), [401])
            self.assertEqual(LoginRateThrottle().get_ident(type('R', (), {
                'headers': {'x-forwarded-for': 'a, 5.5.5.5'}, 'META': {'REMOTE_ADDR': '127.0.0.1'}})()), '5.5.5.5')


class DocumentacionApiTests(SimpleTestCase):
    """La regla se prueba con la función que usa settings.py, sin depender del .env local."""

    def test_sin_variable_sigue_a_debug(self):
        self.assertTrue(resolver_docs_api(debug=True, valor=''))     # desarrollo: encendida
        self.assertFalse(resolver_docs_api(debug=False, valor=''))   # producción: apagada por defecto
        self.assertFalse(resolver_docs_api(debug=False, valor=None))

    def test_decision_explicita(self):
        self.assertTrue(resolver_docs_api(debug=False, valor='True'))   # encendida a propósito en producción
        self.assertFalse(resolver_docs_api(debug=True, valor='false'))  # apagada a propósito en desarrollo
        self.assertTrue(resolver_docs_api(debug=False, valor=' TRUE '))

    def test_valor_ambiguo_es_error(self):
        for valor in ('si', 'enabled', '2'):
            with self.subTest(valor=valor), self.assertRaises(ImproperlyConfigured):
                resolver_docs_api(debug=False, valor=valor)

    def test_en_produccion_exige_autenticacion(self):
        self.assertEqual(permisos_docs_api(debug=False), ['rest_framework.permissions.IsAuthenticated'])
        self.assertEqual(permisos_docs_api(debug=True), ['rest_framework.permissions.AllowAny'])

    def test_rutas_coinciden_con_la_configuracion_activa(self):
        # Sea cual sea el .env del desarrollador, las rutas existen solo si la regla las habilita.
        if settings.API_DOCS_ENABLED:
            self.assertEqual(reverse('swagger-ui'), '/api/docs/')
        else:
            with self.assertRaises(NoReverseMatch):
                reverse('swagger-ui')


BASE = dict(
    debug=False, token_max_age=43200, cors_origins=['https://sistema.ejemplo.test'],
    csrf_trusted_origins=['https://sistema.ejemplo.test'], session_cookie_secure=True, csrf_cookie_secure=True,
    sin_https=False, auth_cookie_enabled=False, auth_cookie_secure=True, auth_cookie_samesite='Lax',
    db_password='Pg-Prod-Larga-2026!', num_proxies=1, proxy_ssl_header=True,
)


class ValidacionProduccionBloque8Tests(SimpleTestCase):
    def validar(self, **cambios):
        validar_configuracion_produccion(**{**BASE, **cambios})

    def test_configuracion_vps_completa_pasa(self):
        self.validar()

    def test_rechazos(self):
        for cambios, texto in [
            ({'db_password': ''}, 'DB_PASSWORD'),
            ({'db_password': 'cambiar_esto'}, 'DB_PASSWORD'),
            ({'num_proxies': 0}, 'NUM_PROXIES=1'),
            ({'num_proxies': -1}, 'negativo'),
        ]:
            with self.subTest(cambios=cambios), self.assertRaisesRegex(ImproperlyConfigured, texto):
                self.validar(**cambios)

    def test_desarrollo_no_exige_contrasena_de_bd(self):
        self.validar(debug=True, db_password='cambiar_esto', num_proxies=0)

    def test_cookie_httponly_activable_en_el_vps(self):
        # Lo que habrá que poner en el .env del VPS cuando se migre el frontend.
        self.validar(auth_cookie_enabled=True, auth_cookie_secure=True, auth_cookie_samesite='Lax')
        with self.assertRaises(ImproperlyConfigured):
            self.validar(auth_cookie_enabled=True, auth_cookie_secure=False)


class PlantillaProduccionTests(SimpleTestCase):
    """deploy/env.produccion.example debe pasar las validaciones al completarse, y el código
    no debe tener fijo el dominio ni una IP pública."""

    def leer_plantilla(self):
        from pathlib import Path
        ruta = Path(settings.BASE_DIR).parent / 'deploy' / 'env.produccion.example'
        valores = {}
        for linea in ruta.read_text(encoding='utf-8').splitlines():
            linea = linea.strip()
            if linea and not linea.startswith('#') and '=' in linea:
                clave, valor = linea.split('=', 1)
                valores[clave.strip()] = valor.strip()
        return valores

    def test_plantilla_completada_es_valida(self):
        from decouple import Csv
        v = self.leer_plantilla()
        self.assertTrue(v['SECRET_KEY'].startswith('<') and v['DB_PASSWORD'].startswith('<'))  # sin secretos reales
        self.assertEqual(v['DEBUG'], 'False')
        self.assertEqual(v['AUTH_COOKIE_ENABLED'], 'False')  # cookie HttpOnly aún apagada
        validar_configuracion_produccion(
            debug=False, token_max_age=int(v['TOKEN_MAX_AGE_SECONDS']),
            cors_origins=Csv()(v['CORS_ALLOWED_ORIGINS']), csrf_trusted_origins=Csv()(v['CSRF_TRUSTED_ORIGINS']),
            session_cookie_secure=True, csrf_cookie_secure=True, sin_https=False,
            auth_cookie_enabled=False, auth_cookie_secure=True, auth_cookie_samesite='Lax',
            db_password='Pg-Prod-Completada-2026!', num_proxies=int(v['NUM_PROXIES']),
            proxy_ssl_header=v['SECURE_PROXY_SSL_HEADER_HTTPS'] == 'True',
        )
        self.assertTrue(v['CACHE_URL'].startswith('redis://127.0.0.1'))
        self.assertEqual(v['GUNICORN_BIND'], '127.0.0.1:8001')
        self.assertEqual(v['DB_HOST'], '127.0.0.1')

    def test_sin_dominio_ni_ip_fijos_en_el_codigo(self):
        import re
        from pathlib import Path
        base = Path(settings.BASE_DIR)
        archivos = [p for p in (base / 'config').glob('*.py') if not p.name.startswith('tests')]
        archivos += [base / 'gunicorn.conf.py']
        for archivo in archivos:
            texto = archivo.read_text(encoding='utf-8')
            self.assertFalse('asescon' in texto.lower(), f'dominio fijo en {archivo.name}')
            ips = [ip for ip in re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', texto) if not ip.startswith('127.')]
            self.assertEqual(ips, [], archivo.name)
