"""
Despliegue con Docker de Fact-Kard Core: verificación ESTÁTICA de deploy/docker y del entorno de desarrollo.

No construye imágenes ni levanta contenedores (eso se prueba con Docker en la laptop / VPS). Aquí
se comprueba lo que, si se rompe, expone el servidor o impide arrancar:
  - ningún servicio publica puertos en producción (Docker se salta UFW); las pruebas locales solo en 127.0.0.1;
  - PostgreSQL y Redis solo en la red interna; el web es el único en proxy_net (alias factkard-core-web);
  - rutas de datos FUERA del código (/srv/fact-kard/app);
  - los .env de ejemplo pasan las validaciones de producción;
  - .dockerignore deja fuera secretos, datos y dependencias locales;
  - el docker-compose.yml de desarrollo no trae contraseñas escritas;
  - los comandos demo se niegan a correr con DEBUG=False.
Si deploy/ no existe (p. ej. dentro de la imagen del backend) las pruebas de archivos se omiten.
"""
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from unittest import skipUnless

import yaml
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from config.seguridad import validar_configuracion_produccion

REPO = Path(__file__).resolve().parent.parent.parent
DOCKER = REPO / 'deploy' / 'docker'
HAY_DEPLOY = (DOCKER / 'compose.yaml').is_file()


def _cargar(ruta):
    return yaml.safe_load(ruta.read_text(encoding='utf-8'))


def _env(ruta, reemplazos=None):
    datos = {}
    for linea in ruta.read_text(encoding='utf-8').splitlines():
        linea = linea.strip()
        if not linea or linea.startswith('#') or '=' not in linea:
            continue
        clave, valor = linea.split('=', 1)
        datos[clave.strip()] = valor.strip()
    for clave, valor in (reemplazos or {}).items():
        datos[clave] = valor
    return datos


def _bool(valor):
    return str(valor).strip().lower() in ('1', 'true', 'yes', 'on')


def _validar(env):
    """Las mismas reglas que settings.py aplica al arrancar con DEBUG=False."""
    debug = _bool(env.get('DEBUG', 'False'))
    lista = lambda v: [x.strip() for x in (v or '').split(',') if x.strip()]  # noqa: E731
    validar_configuracion_produccion(
        debug=debug,
        token_max_age=int(env['TOKEN_MAX_AGE_SECONDS']),
        cors_origins=lista(env.get('CORS_ALLOWED_ORIGINS')),
        csrf_trusted_origins=lista(env.get('CSRF_TRUSTED_ORIGINS')),
        session_cookie_secure=_bool(env.get('SESSION_COOKIE_SECURE', str(not debug))),
        csrf_cookie_secure=_bool(env.get('CSRF_COOKIE_SECURE', str(not debug))),
        sin_https=_bool(env.get('PRODUCCION_SIN_HTTPS', 'False')),
        auth_cookie_enabled=_bool(env.get('AUTH_COOKIE_ENABLED', 'False')),
        auth_cookie_secure=_bool(env.get('AUTH_COOKIE_SECURE', str(not debug))),
        auth_cookie_samesite=env.get('AUTH_COOKIE_SAMESITE', 'Lax'),
        db_password=env.get('DB_PASSWORD'),
        num_proxies=int(env.get('NUM_PROXIES', '0')),
        proxy_ssl_header=_bool(env.get('SECURE_PROXY_SSL_HEADER_HTTPS', 'False')),
    )


@skipUnless(HAY_DEPLOY, 'deploy/docker no está disponible (p. ej. dentro de la imagen)')
class ComposeCoreTests(SimpleTestCase):
    def setUp(self):
        self.compose = _cargar(DOCKER / 'compose.yaml')
        self.servicios = self.compose['services']

    def test_produccion_no_publica_puertos(self):
        for nombre, servicio in self.servicios.items():
            self.assertNotIn('ports', servicio, f'{nombre} no debe publicar puertos (Docker se salta UFW)')

    def test_redes_aisladas(self):
        redes = self.compose['networks']
        self.assertTrue(redes['datos']['internal'])
        self.assertTrue(redes['proxy_net']['external'])
        self.assertEqual(self.servicios['db']['networks'], ['datos'])
        self.assertEqual(self.servicios['redis']['networks'], ['datos'])
        self.assertEqual(set(self.servicios['backend']['networks']), {'datos', 'app'})   # app: salida a Internet (consulta RUC)
        web = self.servicios['web']['networks']
        self.assertEqual(set(web), {'app', 'proxy_net'})
        self.assertEqual(web['proxy_net']['aliases'], ['factkard-core-web'])
        for nombre in ('db', 'redis', 'backend', 'tareas'):
            self.assertNotIn('proxy_net', self.servicios[nombre]['networks'], nombre)
        self.assertEqual(self.servicios['tareas']['networks'], ['datos'])           # sin salida a Internet

    def test_tareas_respaldo_diario(self):
        tareas = self.servicios['tareas']
        self.assertEqual(tareas['command'], ['fk-tareas'])
        self.assertEqual(tareas['image'], self.servicios['backend']['image'])   # misma imagen del backend
        self.assertEqual(tareas['environment']['FACT_KARD_BACKUP_DIR'], '/srv/fact-kard/datos/respaldos')
        volumenes = tareas['volumes']
        self.assertIn('media:/srv/fact-kard/datos/media:ro', volumenes)  # solo lee lo que respalda
        self.assertTrue(any(v.endswith(':/srv/fact-kard/datos/respaldos') for v in volumenes))
        script = (DOCKER / 'backend-tareas.sh').read_text(encoding='utf-8')
        self.assertIn('python manage.py respaldo crear', script)
        self.assertIn("FK_RESPALDO_HORA:-04:00", script)

    @skipUnless(shutil.which('sh') and os.name != 'nt', 'requiere sh (Linux)')
    def test_tareas_rechaza_hora_invalida(self):
        for hora in ('25:00', '3:30', '03:60', 'x'):
            r = subprocess.run(['sh', str(DOCKER / 'backend-tareas.sh')], env={'PATH': os.environ.get('PATH', ''),
                               'FK_RESPALDO_HORA': hora}, capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 1, hora)

    def test_datos_fuera_del_codigo(self):
        backend = self.servicios['backend']
        env = backend['environment']
        codigo = PurePosixPath('/srv/fact-kard/app')
        for clave in ('MEDIA_ROOT', 'FACT_KARD_BACKUP_DIR', 'STATIC_ROOT'):
            ruta = PurePosixPath(env[clave])
            self.assertTrue(ruta.is_absolute(), clave)
            self.assertNotEqual(codigo, ruta)
            self.assertNotIn(codigo, ruta.parents, f'{clave} no puede estar dentro del código')
        self.assertEqual(env['DB_HOST'], 'db')
        self.assertEqual(env['CACHE_URL'], 'redis://redis:6379/0')
        self.assertEqual(self.servicios['db']['environment']['POSTGRES_PASSWORD'],
                         '${DB_PASSWORD:?Define DB_PASSWORD en deploy/docker/.env}')

    def test_limites_de_memoria_y_reinicio(self):
        for nombre, servicio in self.servicios.items():
            self.assertIn('mem_limit', servicio, nombre)
            self.assertEqual(servicio['restart'], 'unless-stopped', nombre)
        self.assertEqual(self.servicios['db']['image'], 'postgres:16-alpine')

    def test_nombres_propios_para_convivir_con_fact_kard(self):
        self.assertEqual(self.compose['name'], 'factkard-core')
        for nombre in ('backend', 'tareas', 'web'):
            self.assertTrue(self.servicios[nombre]['image'].startswith('factkard-core-'), nombre)
        self.assertEqual(self.servicios['db']['environment']['POSTGRES_DB'], '${DB_NAME:-fact_kard_core}')

    def test_prueba_local_solo_en_localhost(self):
        local = _cargar(DOCKER / 'compose.local.yaml')
        puertos = [p for s in local['services'].values() for p in s.get('ports', [])]
        self.assertTrue(puertos)
        for p in puertos:
            self.assertTrue(p.startswith('127.0.0.1:'), p)


@skipUnless(HAY_DEPLOY, 'deploy/docker no está disponible')
class EnvEjemploTests(SimpleTestCase):
    REEMPLAZOS = {'SECRET_KEY': 'x' * 60, 'DB_PASSWORD': 'Clave-Larga-De-Prueba-2026'}

    def test_produccion_pasa_las_validaciones(self):
        env = _env(DOCKER / 'env.produccion.example', self.REEMPLAZOS)
        for clave, valor in list(env.items()):
            env[clave] = valor.replace('<kardex.asescon.net>', 'kardex.asescon.net')
        _validar(env)
        self.assertEqual(env['DEBUG'], 'False')
        self.assertEqual(env['NUM_PROXIES'], '2')                 # proxy compartido + Nginx web
        self.assertEqual(env['SECURE_PROXY_SSL_HEADER_HTTPS'], 'True')
        self.assertEqual(env['SECURE_SSL_REDIRECT'], 'True')
        self.assertTrue(env['CORS_ALLOWED_ORIGINS'].startswith('https://'))
        self.assertNotIn('PRODUCCION_SIN_HTTPS', env)
        for clave in ('DB_HOST', 'CACHE_URL', 'MEDIA_ROOT', 'STATIC_ROOT'):
            self.assertNotIn(clave, env, f'{clave} lo fija compose.yaml')

    def test_produccion_sin_completar_no_arranca(self):
        env = _env(DOCKER / 'env.produccion.example', {'SECRET_KEY': 'x' * 60, 'DB_PASSWORD': ''})
        with self.assertRaises(ImproperlyConfigured):
            _validar(env)

    def test_local_pasa_solo_con_la_excepcion_explicita(self):
        env = _env(DOCKER / 'env.local.example', self.REEMPLAZOS)
        _validar(env)
        self.assertEqual(env['PRODUCCION_SIN_HTTPS'], 'True')
        env['PRODUCCION_SIN_HTTPS'] = 'False'
        with self.assertRaises(ImproperlyConfigured):              # http:// sin la excepción: no arranca
            _validar(env)


@skipUnless(HAY_DEPLOY, 'deploy/docker no está disponible')
class DockerignoreTests(SimpleTestCase):
    def test_excluye_secretos_datos_y_dependencias(self):
        reglas = {l.strip() for l in (REPO / '.dockerignore').read_text(encoding='utf-8').splitlines()}
        for regla in ('**/.env', '**/.env.*', 'backend/.secret_key.dev', '**/*.pfx', '**/*.p12', '**/*.pem',
                      '**/*.key', 'backend/.venv', '**/node_modules', 'backend/media', 'backups', 'padron_sunat',
                      'deploy/docker/datos', '.git'):
            self.assertIn(regla, reglas, regla)
        self.assertIn('!frontend/.env.production', reglas)          # VITE_API_URL=/api para el build

    def test_imagen_backend_sin_root_y_con_pg_dump_16(self):
        dockerfile = (DOCKER / 'backend.Dockerfile').read_text(encoding='utf-8')
        self.assertIn('USER factkard', dockerfile)
        self.assertIn('postgresql-client-16', dockerfile)
        self.assertIn('WORKDIR /srv/fact-kard/app/backend', dockerfile)
        self.assertNotRegex(dockerfile, r'(?im)^\s*(ENV|ARG)\s+.*(SECRET_KEY|PASSWORD|CLAVE)')


@skipUnless(HAY_DEPLOY, 'deploy/docker no está disponible')
class ProduccionSinSunatTests(SimpleTestCase):
    def test_sin_variables_ni_volumenes_sunat(self):
        textos = [(DOCKER / n).read_text(encoding='utf-8') for n in
                  ('compose.yaml', 'env.produccion.example', 'env.local.example', 'backend.Dockerfile')]
        for texto in textos:
            self.assertNotIn('SUNAT_', texto)
            self.assertNotIn('secretos', texto)


@skipUnless((REPO / 'docker-compose.yml').is_file(), 'docker-compose.yml no está disponible')
class ComposeDesarrolloTests(SimpleTestCase):
    def setUp(self):
        self.compose = _cargar(REPO / 'docker-compose.yml')

    def test_puertos_solo_en_localhost(self):
        for nombre, servicio in self.compose['services'].items():
            for puerto in servicio.get('ports', []):
                self.assertTrue(str(puerto).startswith('127.0.0.1:'), f'{nombre}: {puerto}')

    def test_sin_contrasenas_escritas(self):
        db = self.compose['services']['db']['environment']
        backend = self.compose['services']['backend']['environment']
        self.assertTrue(db['POSTGRES_PASSWORD'].startswith('${DEV_DB_PASSWORD:?'))
        self.assertTrue(backend['DB_PASSWORD'].startswith('${DEV_DB_PASSWORD:?'))
        self.assertEqual(backend['DEMO_PASSWORD'], '${DEMO_PASSWORD:-}')


class ComandosDemoTests(TestCase):
    @override_settings(DEBUG=False)
    def test_init_demo_no_corre_en_produccion(self):
        with self.assertRaisesMessage(CommandError, 'DEBUG=True'):
            call_command('init_demo')

    @override_settings(DEBUG=False)
    def test_seed_demo_ventas_no_corre_en_produccion(self):
        with self.assertRaisesMessage(CommandError, 'DEBUG=True'):
            call_command('seed_demo_ventas')

    @override_settings(DEBUG=True)
    def test_init_demo_exige_contrasena(self):
        anterior = os.environ.pop('DEMO_PASSWORD', None)
        try:
            with self.assertRaisesMessage(CommandError, 'DEMO_PASSWORD'):
                call_command('init_demo')
        finally:
            if anterior is not None:
                os.environ['DEMO_PASSWORD'] = anterior
