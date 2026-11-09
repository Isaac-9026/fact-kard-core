"""
Bloque 24 — respaldo completo, verificación, copia externa, retención y restauración.

pg_dump / pg_restore se simulan (servicio.ejecutar) salvo en RespaldoPostgresRealTests, que usa los
programas reales contra la base de pruebas y se omite si no están instalados (p. ej. en Windows sin
el cliente de PostgreSQL en el PATH). Todo ocurre en directorios temporales fuera del repositorio.
"""
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.respaldo import servicio as s

DUMP_FALSO = b'PGDMP' + b'\x00' * 64 + b'volcado de prueba'


def pg_falso(comando, *, env):
    """Simula pg_dump (escribe --file=) y pg_restore --list / restauración (éxito)."""
    assert 'PGPASSWORD' not in ' '.join(map(str, comando))  # la clave nunca va en la línea de comandos
    for arg in comando:
        if str(arg).startswith('--file='):
            Path(str(arg)[len('--file='):]).write_bytes(DUMP_FALSO)
    return 0, ''


class Entorno:
    """Raíz temporal con artefactos SUNAT, MEDIA_ROOT y directorios de respaldo local/externo."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix='fk_b24_'))
        self.artefactos = self.dir / 'artefactos'
        self.media = self.dir / 'media'
        self.respaldos = self.dir / 'respaldos'
        self.externo = self.dir / 'externo'
        base = self.artefactos / 'empresa_1' / '2026' / '11' / 'F001'
        base.mkdir(parents=True)
        (base / '20100100100-01-F001-1-sin-firma.xml').write_bytes(b'<Invoice>sin firma</Invoice>')
        (base / '20100100100-01-F001-1.xml').write_bytes(b'<Invoice>firmado</Invoice>')
        (base / '20100100100-01-F001-1.zip').write_bytes(b'PK\x03\x04zip-envio')
        (base / 'R-20100100100-01-F001-1.zip').write_bytes(b'PK\x03\x04cdr')
        (base / '20100100100-01-F001-1.pdf').write_bytes(b'%PDF-1.4 prueba')
        (base / '.20100100100-01-F001-2.xml.0123abcd.tmp').write_bytes(b'temporal')  # no se respalda
        (self.media / 'logos').mkdir(parents=True)
        (self.media / 'logos' / 'empresa_1.png').write_bytes(b'\x89PNG logo')
        self.override = override_settings(
            SUNAT_ARTEFACTOS_PATH=str(self.artefactos), MEDIA_ROOT=str(self.media),
            FACT_KARD_BACKUP_DIR=str(self.respaldos), FACT_KARD_BACKUP_EXTERNAL_PATH='',
            FACT_KARD_BACKUP_RETENCION_DIARIOS=7, FACT_KARD_BACKUP_RETENCION_SEMANALES=4,
            FACT_KARD_BACKUP_RETENCION_MENSUALES=0)

    def __enter__(self):
        self.override.enable()
        return self

    def __exit__(self, *exc):
        self.override.disable()
        shutil.rmtree(self.dir, ignore_errors=True)


def instantanea(raiz):
    """{ruta: (bytes, sha256, mtime)} de todo el árbol: para comprobar que nada cambió."""
    return {p.relative_to(raiz).as_posix(): (p.stat().st_size, s.sha256_archivo(p), p.stat().st_mtime_ns)
            for p in Path(raiz).rglob('*') if p.is_file()}


class BaseRespaldo(SimpleTestCase):
    databases = {'default'}  # _entorno_pg lee la configuración de la conexión (sin consultas)

    def setUp(self):
        self.e = Entorno().__enter__()
        self.addCleanup(self.e.__exit__)
        p = mock.patch.object(s, 'ejecutar', side_effect=pg_falso)
        self.pg = p.start()
        self.addCleanup(p.stop)

    def crear(self, **kw):
        r = s.crear_respaldo(**kw)
        self.assertTrue(r.ok, r.errores)
        return r

    def manifest(self, ruta):
        return json.loads((Path(ruta) / s.MANIFEST).read_text(encoding='utf-8'))


# ---- 1–6. Crear --------------------------------------------------------------------------------------
class CrearRespaldoTests(BaseRespaldo):
    def test_respaldo_completo_con_base_artefactos_y_media(self):
        r = self.crear()
        self.assertTrue(r.local_ok)
        ruta = r.ruta
        self.assertRegex(ruta.name, s.PATRON_NOMBRE)
        self.assertEqual(ruta.parent, self.e.respaldos.resolve())
        self.assertTrue((self.e.respaldos / s.MARCA).is_file())
        self.assertEqual((ruta / s.NOMBRE_DUMP).read_bytes(), DUMP_FALSO)                    # 2. base
        art = 'artefactos/empresa_1/2026/11/F001/'
        for nombre in ('20100100100-01-F001-1-sin-firma.xml', '20100100100-01-F001-1.xml', '20100100100-01-F001-1.zip',
                       'R-20100100100-01-F001-1.zip', '20100100100-01-F001-1.pdf'):
            self.assertTrue((ruta / (art + nombre)).is_file(), nombre)                        # 3. artefactos
        self.assertFalse(list(ruta.rglob('*.tmp')))                                           # sin temporales
        self.assertEqual((ruta / 'media/logos/empresa_1.png').read_bytes(), b'\x89PNG logo')  # 4. media
        self.assertFalse(list(self.e.respaldos.glob(f'{s.PREFIJO_PARCIAL}*')))               # sin parciales
        llamados = [c.args[0][0] for c in self.pg.call_args_list]
        self.assertEqual(llamados, ['pg_dump', 'pg_restore'])                                  # volcado + validación

    def test_manifest_y_sha256(self):
        ruta = self.crear().ruta
        m = self.manifest(ruta)
        self.assertEqual((m['formato'], m['version'], m['nombre']), (s.FORMATO, s.VERSION, ruta.name))
        self.assertTrue(m['creado_en'])
        self.assertEqual(m['componentes']['database'], {'estado': 'OK', 'archivos': 1})
        self.assertEqual(m['componentes']['artefactos'], {'estado': 'OK', 'archivos': 5})
        self.assertEqual(m['componentes']['media'], {'estado': 'OK', 'archivos': 1})
        self.assertEqual(len(m['archivos']), 7)
        for a in m['archivos']:
            self.assertEqual(set(a), {'ruta', 'tipo', 'bytes', 'sha256'})
            archivo = ruta / a['ruta']
            self.assertEqual(a['bytes'], archivo.stat().st_size)
            self.assertEqual(a['sha256'], hashlib.sha256(archivo.read_bytes()).hexdigest())
            self.assertFalse(Path(a['ruta']).is_absolute())
            self.assertEqual(a['ruta'].split('/')[0], a['tipo'])
        texto = (ruta / s.MANIFEST).read_bytes()
        self.assertEqual((ruta / s.MANIFEST_HASH).read_text().split()[0], hashlib.sha256(texto).hexdigest())
        # Sin secretos ni rutas absolutas del servidor en el manifest.
        db = connection.settings_dict
        for prohibido in (str(self.e.dir), str(db.get('PASSWORD') or 'sin-clave-configurada'), 'PGPASSWORD'):
            self.assertNotIn(prohibido, texto.decode('utf-8'))

    def test_clave_de_base_solo_en_el_entorno_del_proceso(self):
        with mock.patch.dict(connection.settings_dict, {'PASSWORD': 'Clave-PG-B24'}):
            _nombre, args, env = s._entorno_pg()
        self.assertEqual(env['PGPASSWORD'], 'Clave-PG-B24')
        self.assertNotIn('Clave-PG-B24', ' '.join(args))

    def test_fallo_de_pg_dump_no_deja_respaldo_y_falla(self):
        self.pg.side_effect = lambda comando, env: (1, 'conexión rechazada')
        r = s.crear_respaldo()
        self.assertFalse(r.ok)
        self.assertFalse(r.local_ok)
        self.assertIn('pg_dump falló', r.errores[0])
        self.assertEqual(s.respaldos_en(self.e.respaldos), [])
        self.assertFalse(list(self.e.respaldos.glob(f'{s.PREFIJO_PARCIAL}*')))

    def test_artefactos_configurados_pero_ausentes_falla(self):
        shutil.rmtree(self.e.artefactos)
        r = s.crear_respaldo()
        self.assertFalse(r.ok)
        self.assertIn('SUNAT_ARTEFACTOS_PATH', ' '.join(r.errores))
        self.assertEqual(s.respaldos_en(self.e.respaldos), [])

    def test_sin_copia_externa_lo_informa(self):
        r = self.crear()
        self.assertEqual(r.copia_externa, 'NO_CONFIGURADA')
        self.assertTrue(any('NO existe copia externa' in a for a in r.advertencias))

    def test_directorio_con_contenido_ajeno_no_se_usa(self):
        self.e.respaldos.mkdir()
        (self.e.respaldos / 'documento_personal.txt').write_text('no tocar')
        r = s.crear_respaldo()
        self.assertFalse(r.ok)
        self.assertEqual(os.listdir(self.e.respaldos), ['documento_personal.txt'])

    def test_rutas_peligrosas_rechazadas(self):
        for ruta in ('', '   ', 'relativa/respaldos', '/', str(Path.home())):
            with self.subTest(ruta=ruta), self.assertRaises(s.ErrorRespaldo):
                s.raiz_controlada(ruta, crear=True)
        with self.assertRaises(s.ErrorRespaldo):  # dentro de los artefactos
            s.raiz_controlada(str(self.e.artefactos / 'respaldos'), crear=True)

    def test_comando_crear_y_codigos_de_salida(self):
        out = StringIO()
        call_command('respaldo', 'crear', stdout=out, stderr=StringIO())
        self.assertIn('Respaldo creado', out.getvalue())
        self.assertIn('NO existe copia externa', out.getvalue())
        self.pg.side_effect = lambda comando, env: (1, 'x')
        with self.assertRaises(SystemExit) as ctx:
            call_command('respaldo', 'crear', '--destino', str(self.e.dir / 'otros'), stdout=StringIO(), stderr=StringIO())
        self.assertEqual(ctx.exception.code, 1)


# ---- 7, 8, 13. Verificar ----------------------------------------------------------------------------
class VerificarTests(BaseRespaldo):
    def test_respaldo_integro_verifica(self):
        self.assertTrue(s.verificar_respaldo(self.crear().ruta).ok)

    def test_archivo_alterado_falla(self):
        ruta = self.crear().ruta
        (ruta / 'artefactos/empresa_1/2026/11/F001/R-20100100100-01-F001-1.zip').write_bytes(b'PK\x03\x04CDR CAMBIADO')
        r = s.verificar_respaldo(ruta)
        self.assertFalse(r.ok)
        self.assertTrue(any('R-20100100100-01-F001-1.zip' in e for e in r.errores), r.errores)

    def test_mismo_tamano_distinto_contenido_falla(self):
        ruta = self.crear().ruta
        dump = ruta / s.NOMBRE_DUMP
        datos = bytearray(dump.read_bytes())
        datos[-1] ^= 0xFF
        dump.write_bytes(bytes(datos))
        r = s.verificar_respaldo(ruta)
        self.assertTrue(any('SHA-256 distinto' in e for e in r.errores), r.errores)

    def test_archivo_faltante_falla(self):
        ruta = self.crear().ruta
        (ruta / 'media/logos/empresa_1.png').unlink()
        r = s.verificar_respaldo(ruta)
        self.assertFalse(r.ok)
        self.assertTrue(any('Falta el archivo media/logos/empresa_1.png' in e for e in r.errores), r.errores)

    def test_manifest_alterado_o_inyeccion_falla(self):
        ruta = self.crear().ruta
        (ruta / 'artefactos' / 'intruso.xml').write_bytes(b'<x/>')
        self.assertTrue(any('no declarado' in e for e in s.verificar_respaldo(ruta).errores))
        (ruta / 'artefactos' / 'intruso.xml').unlink()
        m = self.manifest(ruta)
        m['archivos'][0]['ruta'] = '../../etc/passwd'
        (ruta / s.MANIFEST).write_text(json.dumps(m), encoding='utf-8')
        errores = s.verificar_respaldo(ruta).errores
        self.assertTrue(any('SHA-256' in e and 'manifest' in e for e in errores), errores)
        self.assertTrue(any('Ruta o tipo inválido' in e for e in errores), errores)

    def test_verificar_no_modifica_nada(self):
        ruta = self.crear().ruta
        (ruta / 'media/logos/empresa_1.png').write_bytes(b'alterado')  # aunque falle, no "repara" nada
        antes = instantanea(self.e.dir)
        r = s.verificar_respaldo(ruta)
        self.assertFalse(r.ok)
        self.assertEqual(instantanea(self.e.dir), antes)
        out = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command('respaldo', 'verificar', str(ruta), stdout=out, stderr=StringIO())
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(instantanea(self.e.dir), antes)


# ---- 9, 10. Copia externa ----------------------------------------------------------------------------
class CopiaExternaTests(BaseRespaldo):
    def test_copia_externa_configurada_se_copia_y_verifica(self):
        r = self.crear(externo=str(self.e.externo))
        self.assertEqual(r.copia_externa, 'OK')
        copia = self.e.externo / r.ruta.name
        self.assertTrue(s.verificar_respaldo(copia).ok)
        self.assertEqual(instantanea(copia).keys(), instantanea(r.ruta).keys())
        self.assertTrue((self.e.externo / s.MARCA).is_file())

    def test_fallo_de_copia_externa_se_reporta(self):
        self.e.externo.mkdir()
        (self.e.externo / 'ajeno.txt').write_text('no es un directorio de respaldos')
        r = s.crear_respaldo(externo=str(self.e.externo))
        self.assertFalse(r.ok)
        self.assertTrue(r.local_ok)  # el respaldo local sí quedó completo
        self.assertEqual(r.copia_externa, 'FALLIDA')
        self.assertTrue(any('COPIA EXTERNA falló' in e for e in r.errores))
        self.assertTrue(s.verificar_respaldo(r.ruta).ok)
        with override_settings(FACT_KARD_BACKUP_EXTERNAL_PATH=str(self.e.externo)), \
                self.assertRaises(SystemExit) as ctx:
            call_command('respaldo', 'crear', '--destino', str(self.e.dir / 'r2'), stdout=StringIO(), stderr=StringIO())
        self.assertEqual(ctx.exception.code, 2)

    def test_copia_externa_alterada_durante_la_copia_falla(self):
        # Portable (Windows/Linux): se comparan rutas RESUELTAS por componentes, no texto. Se corrompe
        # el logo copiado en el staging externo (.parcial-…) DESPUÉS de su copia verificada; la
        # verificación final de la copia externa debe detectarlo.
        original = s._copiar_verificado
        externo_real = self.e.externo.resolve()
        corrompidos = []

        def en_staging_externo(destino):
            try:
                relativa = Path(destino).resolve().relative_to(externo_real)
            except ValueError:
                return False
            return relativa.parts[0].startswith(s.PREFIJO_PARCIAL)

        def corrompe(origen, destino):
            res = original(origen, destino)
            if en_staging_externo(destino) and Path(destino).suffix == '.png':
                datos = bytearray(Path(destino).read_bytes())  # mismo tamaño, contenido distinto
                datos[-1] ^= 0xFF
                Path(destino).write_bytes(bytes(datos))
                corrompidos.append(Path(destino).name)
            return res
        with mock.patch.object(s, '_copiar_verificado', side_effect=corrompe):
            r = s.crear_respaldo(externo=str(self.e.externo))
        self.assertEqual(corrompidos, ['empresa_1.png'])  # la alteración realmente ocurrió en la copia externa
        self.assertEqual(r.copia_externa, 'FALLIDA')
        self.assertTrue(r.local_ok)
        self.assertTrue(any('SHA-256 distinto' in e and 'empresa_1.png' in e for e in r.errores), r.errores)
        self.assertFalse((self.e.externo / r.ruta.name).exists())
        self.assertFalse(list(self.e.externo.glob(f'{s.PREFIJO_PARCIAL}*')))
        self.assertTrue(s.verificar_respaldo(r.ruta).ok)  # el local no se tocó


# ---- Política de archivos (secretos) ----------------------------------------------------------------
class PoliticaArchivosTests(BaseRespaldo):
    def assertFallaPor(self, archivo, fragmento):
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_bytes(b'SECRETO-B24')
        r = s.crear_respaldo()
        self.assertFalse(r.ok)
        self.assertFalse(r.local_ok)
        self.assertTrue(any(fragmento in e for e in r.errores), r.errores)
        self.assertEqual(s.respaldos_en(self.e.respaldos), [])  # no hay respaldo "exitoso" parcial
        self.assertFalse(list(self.e.respaldos.glob(f'{s.PREFIJO_PARCIAL}*')))
        for p in self.e.respaldos.rglob('*'):
            if p.is_file():
                self.assertNotIn(b'SECRETO-B24', p.read_bytes())
        archivo.unlink()

    def test_env_en_media_aborta(self):
        self.assertFallaPor(self.e.media / '.env', 'SENSIBLE')
        self.assertFallaPor(self.e.media / 'logos' / 'produccion.env', 'SENSIBLE')

    def test_certificados_y_claves_en_artefactos_abortan(self):
        for nombre in ('certificado.pfx', 'firma.p12', 'clave.pem', 'privada.key', 'emisor.crt', 'raiz.cer',
                       'almacen.jks', 'firma.keystore'):
            with self.subTest(nombre=nombre):
                self.assertFallaPor(self.e.artefactos / 'empresa_1' / nombre, 'SENSIBLE')

    def test_nombres_que_sugieren_secretos_abortan_aunque_la_extension_sea_valida(self):
        for nombre in ('password.xml', 'token_sunat.zip', 'credenciales.pdf', 'client_secret.png'):
            with self.subTest(nombre=nombre):
                destino = self.e.media if nombre.endswith('.png') else self.e.artefactos
                self.assertFallaPor(destino / nombre, 'SENSIBLE')

    def test_tipos_no_esperados_abortan(self):
        self.assertFallaPor(self.e.artefactos / 'notas.txt', 'tipo de archivo no permitido')
        self.assertFallaPor(self.e.media / 'logos' / 'logo.svg', 'tipo de archivo no permitido')
        self.assertFallaPor(self.e.media / 'script.js', 'tipo de archivo no permitido')

    def test_tipos_validos_se_respaldan(self):
        (self.e.media / 'empresas' / '7' / 'logos').mkdir(parents=True)
        for nombre in ('a.webp', 'b.jpg', 'c.jpeg', 'd.PNG'):
            (self.e.media / 'empresas' / '7' / 'logos' / nombre).write_bytes(b'img ' + nombre.encode())
        ruta = self.crear().ruta
        m = self.manifest(ruta)
        rutas = {a['ruta'] for a in m['archivos']}
        for esperado in ('artefactos/empresa_1/2026/11/F001/20100100100-01-F001-1.xml',
                         'artefactos/empresa_1/2026/11/F001/20100100100-01-F001-1-sin-firma.xml',
                         'artefactos/empresa_1/2026/11/F001/20100100100-01-F001-1.zip',
                         'artefactos/empresa_1/2026/11/F001/R-20100100100-01-F001-1.zip',
                         'artefactos/empresa_1/2026/11/F001/20100100100-01-F001-1.pdf',
                         'media/logos/empresa_1.png', 'media/empresas/7/logos/a.webp', 'media/empresas/7/logos/b.jpg',
                         'media/empresas/7/logos/c.jpeg', 'media/empresas/7/logos/d.PNG'):
            self.assertIn(esperado, rutas)

    def test_es_sensible(self):
        for nombre in ('.env', '.env.production', 'prod.env', 'x.pfx', 'X.PEM', 'llave.key', 'id_rsa', 'mi_password.xml',
                       'Credentials.zip', 'clave_privada.pdf'):
            self.assertTrue(s.es_sensible(nombre), nombre)
        for nombre in ('20100100100-01-F001-1.xml', 'R-20100100100-01-F001-1.zip', 'logo.webp', 'envio.zip'):
            self.assertFalse(s.es_sensible(nombre), nombre)


# ---- Normalización Unicode de nombres sensibles -------------------------------------------------
COMBINANTE = 'contra\u0301sena.xml'  # "contrásena" con acento COMBINADO (a + U+0301)


class NombresUnicodeTests(BaseRespaldo):
    BLOQUEADOS = {
        'fullwidth': 'ｐａｓｓｗｏｒｄ.xml',
        'mayusculas': 'PASSWORD.XML',
        'acento combinado': COMBINANTE,
        'contraseña precompuesta': 'contraseña.xml',
        'credential con ⅼ (U+217C)': 'credentiaⅼ.xml',
        'credencial con ⅼ (U+217C)': 'credenciaⅼ.xml',
        'token con extensión permitida': 'export_token.zip',
        'zero-width dentro de password': 'pass\u200bword.pdf',
        'clave': 'clave_sol.xml',
        'secret fullwidth mixto': 'ＳＥＣＲＥＴ.pdf',
        '.PFX mayúsculas': 'FIRMA.PFX',
        '.pfx fullwidth': 'firma.ｐｆｘ',
        '.Pem': 'cert.Pem',
        '.KEY': 'emisor.KEY',
        '.CRT': 'raiz.CRT',
        '.Cer': 'sunat.Cer',
        '.JKS': 'almacen.JKS',
        '.KeyStore': 'firma.KeyStore',
        '.P12': 'firma.P12',
        '.ENV': 'PRODUCCION.ENV',
        '.Env.local': '.Env.local',
    }
    PERMITIDOS = ('20100100100-01-F001-1.xml', '20100100100-01-F001-1-sin-firma.xml', 'R-20100100100-01-F001-1.zip',
                  '20100100100-01-F001-1.pdf', 'logo.png', 'logo.JPG', 'foto.jpeg', '0a1b2c3d4e5f.webp',
                  'envio.zip', 'documento-electrónico.pdf')

    def test_variantes_unicode_y_mayusculas_se_detectan(self):
        for caso, nombre in self.BLOQUEADOS.items():
            with self.subTest(caso=caso):
                self.assertTrue(s.es_sensible(nombre), nombre)
        for nombre in self.PERMITIDOS:
            with self.subTest(permitido=nombre):
                self.assertFalse(s.es_sensible(nombre), nombre)

    def test_normalizacion_nfkc_casefold(self):
        n, sin = s.normalizar_nombre('ｐａｓｓｗｏｒｄ.XML')
        self.assertEqual(n, 'password.xml')
        self.assertEqual(s.normalizar_nombre(COMBINANTE)[1], 'contrasena.xml')
        self.assertEqual(s.normalizar_nombre('contraseña.xml')[1], 'contrasena.xml')
        self.assertEqual(s.normalizar_nombre('credenciaⅼ.xml')[0], 'credencial.xml')
        self.assertEqual(s.normalizar_nombre('pass\u200bword')[0], 'password')

    def test_archivo_sensible_unicode_aborta_sin_parcial_ni_copia_externa(self):
        casos = (('artefactos', 'ｐａｓｓｗｏｒｄ.xml'), ('artefactos', COMBINANTE), ('artefactos', 'contraseña.xml'),
                 ('artefactos', 'credenciaⅼ.xml'), ('artefactos', 'export_token.zip'), ('artefactos', 'FIRMA.PFX'),
                 ('media', 'PASSWORD.PNG'), ('media', 'clave.webp'))
        for componente, nombre in casos:
            with self.subTest(nombre=nombre):
                carpeta = (self.e.artefactos / 'empresa_1') if componente == 'artefactos' else (self.e.media / 'logos')
                archivo = carpeta / nombre
                archivo.write_bytes(b'SECRETO-UNICODE-B24')
                r = s.crear_respaldo(externo=str(self.e.externo))
                archivo.unlink()
                self.assertFalse(r.ok)
                self.assertFalse(r.local_ok)
                self.assertEqual(r.copia_externa, 'NO_CONFIGURADA')  # nunca se intentó la copia externa
                self.assertTrue(any('SENSIBLE' in e for e in r.errores), r.errores)
                self.assertEqual(s.respaldos_en(self.e.respaldos), [])
                self.assertFalse(list(self.e.respaldos.glob(f'{s.PREFIJO_PARCIAL}*')))
                for raiz in (self.e.respaldos, self.e.externo):
                    if raiz.exists():
                        for p in raiz.rglob('*'):
                            self.assertFalse(p.is_file() and b'SECRETO-UNICODE-B24' in p.read_bytes(), p)
                self.assertFalse(self.e.externo.exists() and s.respaldos_en(self.e.externo))

    def test_legitimos_se_respaldan(self):
        base = self.e.artefactos / 'empresa_1' / '2026' / '11' / 'F001'
        (base / 'documento-electrónico.pdf').write_bytes(b'%PDF legitimo')
        for nombre in ('logo.JPG', 'foto.jpeg', '0a1b2c3d4e5f.webp'):
            (self.e.media / 'logos' / nombre).write_bytes(b'img')
        r = self.crear(externo=str(self.e.externo))
        self.assertEqual(r.copia_externa, 'OK')
        rutas = {a['ruta'] for a in self.manifest(r.ruta)['archivos']}
        for esperado in ('artefactos/empresa_1/2026/11/F001/20100100100-01-F001-1.xml',
                         'artefactos/empresa_1/2026/11/F001/20100100100-01-F001-1.pdf',
                         'artefactos/empresa_1/2026/11/F001/documento-electrónico.pdf',
                         'media/logos/empresa_1.png', 'media/logos/logo.JPG', 'media/logos/foto.jpeg',
                         'media/logos/0a1b2c3d4e5f.webp'):
            self.assertIn(esperado, rutas)

    def test_allowlist_no_se_debilita_con_extension_fullwidth(self):
        (self.e.artefactos / 'empresa_1' / 'comprobante.ｘｍｌ').write_bytes(b'<x/>')
        r = s.crear_respaldo()
        self.assertFalse(r.ok)
        self.assertTrue(any('tipo de archivo no permitido' in e for e in r.errores), r.errores)


# ---- 11. Retención --------------------------------------------------------------------------------
class RetencionTests(BaseRespaldo):
    def respaldos_viejos(self, dias):
        ahora = timezone.now()
        return [self.crear(momento=ahora - timedelta(days=d), aplicar_retencion=False).ruta.name for d in dias]

    def test_politica_diaria_y_semanal(self):
        nombres = self.respaldos_viejos(range(0, 60, 3))  # 20 respaldos, cada 3 días
        with override_settings(FACT_KARD_BACKUP_RETENCION_DIARIOS=3, FACT_KARD_BACKUP_RETENCION_SEMANALES=2):
            r = s.Resultado()
            s.aplicar_politica_retencion(self.e.respaldos, r)
        quedan = [p.name for _f, p in s.respaldos_en(self.e.respaldos)]
        self.assertIn(nombres[0], quedan)                 # el más reciente siempre
        self.assertLessEqual(len(quedan), 5)
        self.assertEqual(sorted(quedan + r.eliminados), sorted(nombres))

    def test_no_borra_fuera_del_scope(self):
        self.respaldos_viejos(range(0, 30, 5))
        ajeno_dentro = self.e.respaldos / 'notas-del-admin'            # no tiene nombre de respaldo
        ajeno_dentro.mkdir()
        (ajeno_dentro / 'x.txt').write_text('no tocar')
        parecido = self.e.respaldos / '2020-01-01_000000.txt'           # archivo, no directorio
        parecido.write_text('no tocar')
        afuera = self.e.dir / '2020-01-01_000000'                         # fuera de la raíz
        afuera.mkdir()
        enlace = self.e.respaldos / '2019-01-01_000000'
        try:
            enlace.symlink_to(afuera, target_is_directory=True)
        except (OSError, NotImplementedError):
            enlace = None
        with override_settings(FACT_KARD_BACKUP_RETENCION_DIARIOS=1, FACT_KARD_BACKUP_RETENCION_SEMANALES=0):
            r = s.Resultado()
            s.aplicar_politica_retencion(self.e.respaldos, r)
        self.assertTrue(ajeno_dentro.is_dir() and parecido.is_file() and afuera.is_dir())
        if enlace is not None:
            self.assertTrue(enlace.is_symlink())
        self.assertEqual(len(s.respaldos_en(self.e.respaldos)), 1)
        with self.assertRaises(s.ErrorRespaldo):
            s._borrar_dentro(afuera, self.e.respaldos)

    def test_configuracion_invalida_no_borra_nada(self):
        nombres = self.respaldos_viejos(range(0, 20, 2))
        for valor in (0, -1, 'siete', None):
            with self.subTest(valor=valor), override_settings(FACT_KARD_BACKUP_RETENCION_DIARIOS=valor):
                r = s.Resultado()
                s.aplicar_politica_retencion(self.e.respaldos, r)
                self.assertFalse(r.ok)
                self.assertEqual(r.eliminados, [])
        self.assertEqual(len(s.respaldos_en(self.e.respaldos)), len(nombres))

    def test_raiz_sin_marca_no_se_toca(self):
        otro = self.e.dir / 'sin_marca'
        (otro / '2020-01-01_000000').mkdir(parents=True)
        r = s.Resultado()
        s.aplicar_politica_retencion(otro, r)
        self.assertFalse(r.ok)
        self.assertTrue((otro / '2020-01-01_000000').is_dir())

    def test_a_conservar_siempre_el_mas_reciente(self):
        base = datetime(2026, 11, 2)
        lista = [(base - timedelta(days=i), Path(f'/x/{i}')) for i in range(10)]
        self.assertIn(Path('/x/0'), s.a_conservar(lista, {'diarios': 1, 'semanales': 0, 'mensuales': 0}))
        self.assertEqual(len(s.a_conservar(lista, {'diarios': 3, 'semanales': 0, 'mensuales': 0})), 3)


# ---- 12. Restaurar -------------------------------------------------------------------------------
class RestaurarTests(BaseRespaldo):
    def setUp(self):
        super().setUp()
        self.ruta = self.crear().ruta
        self.pg.reset_mock()

    def restaurar(self, **kw):
        return s.restaurar_respaldo(self.ruta, confirmar=kw.pop('confirmar', self.ruta.name), **kw)

    def assertRechazado(self, fragmento, **kw):
        r = self.restaurar(**kw)
        self.assertFalse(r.ok)
        self.assertTrue(any(fragmento in e for e in r.errores), r.errores)
        self.pg.assert_not_called()
        self.assertFalse(list(self.e.dir.rglob(f'{s.PREFIJO_RESTORE}*')))
        return r

    def test_hash_invalido_aborta_y_no_crea_destino(self):
        (self.ruta / 'artefactos/empresa_1/2026/11/F001/20100100100-01-F001-1.xml').write_bytes(b'<Invoice>otro</Invoice>')
        destino = self.e.dir / 'restaurado_art'
        self.assertRechazado('ABORTADA', artefactos=str(destino), base_datos='fk_restaurada')
        self.assertFalse(destino.exists())

    def test_confirmacion_destino_existente_y_base_actual(self):
        self.assertRechazado('Confirmación incorrecta', confirmar='si', media=str(self.e.dir / 'm'))
        self.assertRechazado('al menos un destino')
        (self.e.dir / 'ya_existe').mkdir()
        self.assertRechazado('ya existe', media=str(self.e.dir / 'ya_existe'))
        self.assertRechazado('base configurada', base_datos=connection.settings_dict['NAME'])
        self.assertRechazado('debe ser una ruta absoluta', media='relativa/media')

    def test_destinos_productivos_rechazados(self):
        casos = {'MEDIA_ROOT': self.e.media, 'dentro de MEDIA_ROOT': self.e.media / 'nueva',
                 'SUNAT_ARTEFACTOS_PATH': self.e.artefactos, 'dentro de artefactos': self.e.artefactos / 'nueva',
                 'repositorio': Path(settings.BASE_DIR).parent / 'restaurado_b24',
                 'dentro del respaldo': self.ruta / 'nuevo'}
        for nombre, destino in casos.items():
            with self.subTest(nombre=nombre):
                self.assertRechazado('', media=str(destino))
                if nombre.startswith('dentro') or nombre == 'repositorio':
                    self.assertFalse(destino.exists())
        self.assertRechazado('no permitido', media=str(Path.home()))
        self.assertRechazado('', media=Path(self.e.dir.anchor).as_posix() if os.name != 'nt' else self.e.dir.anchor)
        self.assertEqual((self.e.media / 'logos/empresa_1.png').read_bytes(), b'\x89PNG logo')  # producción intacta

    def test_destino_symlink_rechazado(self):
        real = self.e.dir / 'real'
        real.mkdir()
        enlace = self.e.dir / 'enlace'
        try:
            enlace.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:  # Windows sin privilegio de enlaces
            self.skipTest(f'No se pueden crear enlaces simbólicos aquí: {exc}')
        self.assertRechazado('enlace simbólico', media=str(enlace / 'media'))  # componente intermedio enlazado
        self.assertRechazado('', media=str(enlace))  # el propio destino es un enlace (existe)
        self.assertEqual(list(real.iterdir()), [])

    def test_reparse_point_detectado(self):
        # En Windows un junction/reparse point se marca con FILE_ATTRIBUTE_REPARSE_POINT; se simula ese atributo.
        normal = self.e.dir / 'junction'
        normal.mkdir()
        st = os.lstat(normal)
        falso = mock.Mock(st_mode=st.st_mode, st_file_attributes=0x400)
        real_lstat = os.lstat
        with mock.patch.object(s.os, 'lstat', side_effect=lambda p, *a, **k: falso if Path(p) == normal else real_lstat(p, *a, **k)):
            self.assertTrue(s._es_reparse(normal))
            self.assertRechazado('reparse point', media=str(normal / 'media'))
        self.assertFalse(s._es_reparse(normal))

    def test_restore_usa_staging_y_rename_atomico(self):
        art, media = self.e.dir / 'rest_art', self.e.dir / 'rest_media'
        vistos = []
        rename = os.rename

        def espia(origen, destino):
            vistos.append((Path(origen).name, Path(destino).name, Path(destino).exists()))
            return rename(origen, destino)
        with mock.patch.object(s.os, 'rename', side_effect=espia):
            r = self.restaurar(artefactos=str(art), media=str(media), base_datos='fk_restaurada_b24')
        self.assertTrue(r.ok, r.errores)
        self.assertEqual(len(vistos), 2)
        for origen, destino, existia in vistos:
            self.assertTrue(origen.startswith(s.PREFIJO_RESTORE + destino))
            self.assertFalse(existia)  # el destino final no existía hasta el rename
        esperados = {k for k in instantanea(self.e.artefactos) if not k.endswith('.tmp')}
        self.assertEqual(set(instantanea(art)), esperados)
        self.assertEqual((media / 'logos/empresa_1.png').read_bytes(), b'\x89PNG logo')
        self.assertFalse(list(self.e.dir.glob(f'{s.PREFIJO_RESTORE}*')))
        comando = self.pg.call_args_list[-1].args[0]
        self.assertEqual(comando[0], 'pg_restore')
        for opcion in ('--dbname=fk_restaurada_b24', '--exit-on-error', '--single-transaction', '--no-owner'):
            self.assertIn(opcion, comando)
        self.assertNotIn('--jobs', ' '.join(comando))

    def test_fallo_durante_la_copia_no_deja_destino_final(self):
        destino = self.e.dir / 'rest_art'
        original = s._copiar_verificado
        llamadas = []

        def falla(origen, dest):
            llamadas.append(dest)
            if len(llamadas) == 3:
                raise OSError('disco lleno (simulado)')
            return original(origen, dest)
        with mock.patch.object(s, '_copiar_verificado', side_effect=falla):
            r = self.restaurar(artefactos=str(destino))
        self.assertFalse(r.ok)
        self.assertIn('disco lleno', r.errores[0])
        self.assertFalse(destino.exists())
        self.assertFalse(list(self.e.dir.glob(f'{s.PREFIJO_RESTORE}*')))  # staging limpiado

    def test_fallo_de_pg_restore_no_publica_archivos(self):
        self.pg.side_effect = lambda comando, env: (1, 'error en la base')
        art = self.e.dir / 'rest_art'
        r = self.restaurar(artefactos=str(art), base_datos='fk_restaurada_b24')
        self.assertFalse(r.ok)
        self.assertIn('pg_restore falló', r.errores[0])
        self.assertFalse(art.exists())  # los archivos solo se publican si la base se restauró completa
        self.assertFalse(list(self.e.dir.glob(f'{s.PREFIJO_RESTORE}*')))


# ---- PostgreSQL real (se omite si no hay pg_dump/pg_restore) ---------------------------------------
@skipUnless(shutil.which('pg_dump') and shutil.which('pg_restore'), 'pg_dump/pg_restore no instalados')
class RespaldoPostgresRealTests(TestCase):
    def test_volcado_real_de_la_base_de_pruebas(self):
        with Entorno():
            r = s.crear_respaldo()
            self.assertTrue(r.ok, r.errores)
            self.assertTrue(s.verificar_respaldo(r.ruta, comprobar_dump=True).ok)
            self.assertGreater((r.ruta / s.NOMBRE_DUMP).stat().st_size, 1000)

    def test_restore_real_en_base_nueva_con_single_transaction(self):
        import psycopg
        db = connection.settings_dict
        datos = {k: v for k, v in (('host', db.get('HOST')), ('port', db.get('PORT')), ('user', db.get('USER')),
                                   ('password', db.get('PASSWORD'))) if v}
        nueva = f'fk_b24_restore_{os.getpid()}'
        try:
            admin = psycopg.connect(dbname='postgres', autocommit=True, **datos)
        except psycopg.Error as exc:
            self.skipTest(f'Sin permiso para crear bases: {exc}')
        try:
            admin.execute(f'DROP DATABASE IF EXISTS "{nueva}"')
            admin.execute(f'CREATE DATABASE "{nueva}"')
            with Entorno() as e:
                r = s.crear_respaldo()
                self.assertTrue(r.ok, r.errores)
                res = s.restaurar_respaldo(r.ruta, confirmar=r.ruta.name, base_datos=nueva,
                                           artefactos=str(e.dir / 'rest_art'))
                self.assertTrue(res.ok, res.errores)
                with psycopg.connect(dbname=nueva, **datos) as c:
                    tablas = c.execute("select count(*) from information_schema.tables where table_schema='public'").fetchone()[0]
                self.assertGreater(tablas, 20)
                # Una base ya ocupada falla entera (single transaction) y no publica los archivos.
                res = s.restaurar_respaldo(r.ruta, confirmar=r.ruta.name, base_datos=nueva,
                                           artefactos=str(e.dir / 'rest_art_2'))
                self.assertFalse(res.ok)
                self.assertFalse((e.dir / 'rest_art_2').exists())
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{nueva}" WITH (FORCE)')
            admin.close()
