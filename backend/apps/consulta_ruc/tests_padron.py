"""
Bloque 17D — proveedor `padron_reducido` (copia local del Padrón Reducido del RUC de SUNAT).

Fixtures PEQUEÑAS construidas en cada prueba con el MISMO formato del archivo oficial
(ISO-8859-1, separador '|', '|' final, encabezado real) y datos FICTICIOS. Ninguna prueba descarga
nada ni usa el padrón real.
"""
import io
import os
import shutil
import tempfile
import threading
import zipfile
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auditoria.models import Auditoria
from apps.catalogos.models import Moneda
from apps.empresas.models import Empresa
from apps.inventario.documentos_identidad import digito_verificador_ruc
from apps.usuarios.models import Usuario, UsuarioEmpresa

from . import padron
from .models import PadronRuc, VersionPadronRuc
from .padron import (
    CANDADO_IMPORTACION, ErrorImportacion, detectar_formato, estado_padron, importar_padron, interpretar_fila,
    limpiar_versiones_retiradas, versiones_retiradas_con_filas,
)
from .providers import ProveedorPadronReducido, obtener_proveedor
from .schemas import PadronNoCargado, RucNoEncontrado
from .service import clave_cache, consultar_ruc


def ruc(base10):
    return base10 + str(digito_verificador_ruc(base10))


# Encabezado REAL del padrón oficial (verificado en el ZIP "Actualizado al 31/10/2026", cp1252).
CABECERA = ('RUC|NOMBRE O RAZÓN SOCIAL|ESTADO DEL CONTRIBUYENTE|CONDICIÓN DE DOMICILIO|UBIGEO|TIPO DE VÍA|'
            'NOMBRE DE VÍA|CÓDIGO DE ZONA|TIPO DE ZONA|NÚMERO|INTERIOR|LOTE|DEPARTAMENTO|MANZANA|KILÓMETRO|')
SIN_DIR = ['-'] * 10
R_EMPRESA, R_PERSONA, R_BAJA, R_OTRO = ruc('2061000001'), ruc('1045000002'), ruc('2061000003'), ruc('2061000004')


def fila(numero, nombre, estado='ACTIVO', condicion='HABIDO', ubigeo='-', direccion=SIN_DIR, sep='|'):
    return sep.join([numero, nombre, estado, condicion, ubigeo, *direccion]) + sep


FILAS_BASE = [
    fila(R_EMPRESA, 'COMERCIAL ÑANDÚ FICTICIA S.A.C.', ubigeo='150122',
         direccion=['AV.', 'JOSE LARCO', 'URB.', 'MIRAFLORES', '1232', '-', '-', '501', '-', '-']),
    fila(R_PERSONA, 'PEREZ FICTICIO JUAN'),
    fila(R_BAJA, 'EMPRESA FICTICIA EN BAJA S.R.L.', estado='BAJA DE OFICIO', condicion='NO HALLADO', ubigeo='040101',
         direccion=['CAL.', 'LOS ALAMOS', '-', '-', '-', '-', '7', '-', 'B', '-']),
]


class ZipTemporal:
    """Crea ZIPs temporales con el formato oficial y limpia la caché."""

    def setUp(self):
        cache.clear()
        self.dir = tempfile.mkdtemp(prefix='padron17d_')
        self.addCleanup(shutil.rmtree, self.dir, True)

    def zip(self, filas=None, *, nombre='padron_reducido_ruc.zip', interno='padron_reducido_ruc.txt', cabecera=CABECERA,
            encoding='cp1252', extra=None, fecha=(2026, 10, 31, 2, 31, 32), eol='\n'):
        ruta = os.path.join(self.dir, nombre)
        contenido = eol.join([cabecera, *(FILAS_BASE if filas is None else filas)]) + eol
        with zipfile.ZipFile(ruta, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo(interno, date_time=fecha), contenido.encode(encoding), zipfile.ZIP_DEFLATED)
            for n, datos in (extra or {}).items():
                z.writestr(n, datos)
        return ruta

    def importar(self, ruta=None, **kw):
        return importar_padron(ruta or self.zip(), **kw)


class ConZip(ZipTemporal, TestCase):
    """Base con transacción por prueba."""


# =============================================================================================
class ModeloYMigracionTests(ConZip):
    # 1: modelo
    def test_modelo(self):
        v = VersionPadronRuc.objects.create(fuente='x', archivo='a.zip', archivo_interno='a.txt', sha256='0' * 64)
        p = PadronRuc.objects.create(version=v, ruc=R_EMPRESA, razon_social='X FICTICIA')
        self.assertEqual((v.estado, p.ubigeo, p.domicilio_fiscal), ('CARGANDO', None, None))
        self.assertIn(R_EMPRESA, str(p))
        self.assertEqual((PadronRuc._meta.db_table, VersionPadronRuc._meta.db_table), ('padron_ruc', 'padron_ruc_version'))

    # 2: migración aplicada y tablas creadas
    def test_migracion(self):
        self.assertTrue(MigrationRecorder.Migration.objects.filter(app='consulta_ruc', name='0001_initial').exists())
        tablas = connection.introspection.table_names()
        self.assertIn('padron_ruc', tablas)
        self.assertIn('padron_ruc_version', tablas)

    # 3: RUC único por versión, con un solo índice (el de la restricción), sin índices redundantes
    def test_unique_e_indice(self):
        with connection.cursor() as cur:
            restricciones = connection.introspection.get_constraints(cur, 'padron_ruc')
        unicas = {n: c for n, c in restricciones.items() if c['unique'] and not c['primary_key']}
        self.assertEqual([c['columns'] for c in unicas.values()], [['version_id', 'ruc']])
        indices_ruc = [n for n, c in restricciones.items() if c['index'] and 'ruc' in c['columns'] and not c['unique']]
        self.assertEqual(indices_ruc, [])  # unique ya crea el índice: no hay otro sobre ruc
        v1 = VersionPadronRuc.objects.create(fuente='x', archivo='a', archivo_interno='a', sha256='1')
        v2 = VersionPadronRuc.objects.create(fuente='x', archivo='b', archivo_interno='b', sha256='2')
        PadronRuc.objects.create(version=v1, ruc=R_EMPRESA, razon_social='A')
        PadronRuc.objects.create(version=v2, ruc=R_EMPRESA, razon_social='A')  # mismo RUC en otra versión: OK
        with self.assertRaises(IntegrityError), transaction.atomic():
            PadronRuc.objects.create(version=v1, ruc=R_EMPRESA, razon_social='B')
        # Una sola versión ACTIVA a la vez.
        VersionPadronRuc.objects.filter(pk=v1.pk).update(estado='ACTIVA')
        with self.assertRaises(IntegrityError), transaction.atomic():
            VersionPadronRuc.objects.filter(pk=v2.pk).update(estado='ACTIVA')


# =============================================================================================
class ZipTests(ConZip):
    # 4: ZIP válido
    def test_zip_valido(self):
        version, r = self.importar()
        self.assertEqual(version.estado, 'ACTIVA')
        self.assertEqual((r.leidos, r.validos, r.omitidos, r.duplicados), (3, 3, 0, 0))
        self.assertEqual(PadronRuc.objects.filter(version=version).count(), 3)

    # 5: ZIP corrupto (truncado y con datos dañados a mitad de lectura)
    def test_zip_corrupto(self):
        ruta = self.zip()
        truncado = os.path.join(self.dir, 'truncado.zip')
        with open(ruta, 'rb') as f, open(truncado, 'wb') as g:
            g.write(f.read()[:60])
        with self.assertRaisesRegex(ErrorImportacion, 'ZIP'):
            importar_padron(truncado)
        # Datos comprimidos alterados: falla al leer (CRC/deflate) y la versión queda FALLIDA, vacía.
        grande = self.zip([fila(ruc(f'20{i:08d}'), f'EMPRESA FICTICIA {i}') for i in range(1, 3000)], nombre='g.zip')
        datos = bytearray(open(grande, 'rb').read())
        for i in range(400, 900):
            datos[i] ^= 0x5A
        dañado = os.path.join(self.dir, 'dañado.zip')
        open(dañado, 'wb').write(bytes(datos))
        with self.assertRaises(ErrorImportacion):
            importar_padron(dañado)
        self.assertFalse(VersionPadronRuc.objects.filter(estado='ACTIVA').exists())
        self.assertEqual(PadronRuc.objects.count(), 0)

    # 6: no es ZIP / no existe
    def test_no_zip(self):
        txt = os.path.join(self.dir, 'padron.zip')
        open(txt, 'w', encoding='cp1252').write(CABECERA + '\n')
        with self.assertRaisesRegex(ErrorImportacion, 'no es un ZIP'):
            importar_padron(txt)
        with self.assertRaisesRegex(ErrorImportacion, 'no existe'):
            importar_padron(os.path.join(self.dir, 'inexistente.zip'))
        self.assertEqual(VersionPadronRuc.objects.count(), 0)

    # 7: ZIP Slip / rutas peligrosas (aunque nunca se extrae nada a disco)
    def test_zip_slip(self):
        for interno in ('../../evil.txt', '/etc/padron.txt', 'C:/padron.txt', 'dir\\..\\padron.txt'):
            with self.subTest(interno=interno):
                ruta = self.zip(interno=interno, nombre='slip.zip')
                with self.assertRaisesRegex(ErrorImportacion, 'ZIP Slip'):
                    importar_padron(ruta)
        ruta = self.zip(extra={'../fuera.txt': 'x'}, nombre='slip2.zip')
        with self.assertRaisesRegex(ErrorImportacion, 'ZIP Slip'):
            importar_padron(ruta)
        self.assertEqual(PadronRuc.objects.count(), 0)

    # 8: contenido interno inesperado
    def test_archivo_interno_inesperado(self):
        for extra, interno in (({'leeme.exe': 'MZ'}, 'padron_reducido_ruc.txt'), ({'otro.txt': 'x'}, 'padron_reducido_ruc.txt'),
                               ({}, 'padron.exe')):
            with self.subTest(extra=extra, interno=interno):
                with self.assertRaisesRegex(ErrorImportacion, 'Contenido inesperado'):
                    importar_padron(self.zip(extra=extra, interno=interno, nombre='inesperado.zip'))
        # No se asume el nombre interno: cualquier único .txt con el encabezado correcto sirve.
        version, _ = importar_padron(self.zip(interno='otro_nombre.TXT', nombre='renombrado.zip'))
        self.assertEqual(version.archivo_interno, 'otro_nombre.TXT')

    def test_zip_bomb(self):
        with override_settings(PADRON_RUC_MAX_BYTES=100):
            with self.assertRaisesRegex(ErrorImportacion, 'tamaño'):
                importar_padron(self.zip())
        ruta = self.zip([fila(R_EMPRESA, 'A' * 250)] + [fila(R_PERSONA, 'B')] * 2000, nombre='ratio.zip')
        with override_settings(PADRON_RUC_MAX_RATIO=3):
            with self.assertRaisesRegex(ErrorImportacion, 'compresión'):
                importar_padron(ruta)


# =============================================================================================
class FormatoYFilasTests(ConZip):
    # 9: encoding (Windows-1252 real, ISO-8859-1 compatible y UTF-8)
    def test_encoding(self):
        f = detectar_formato(CABECERA.encode('cp1252'))
        self.assertEqual((f.codificacion, f.separador), ('cp1252', '|'))
        self.assertEqual(detectar_formato(CABECERA.encode('utf-8')).codificacion, 'utf-8')
        self.assertEqual(detectar_formato(('\ufeff' + CABECERA).encode('utf-8')).codificacion, 'utf-8')
        # Caracteres propios de cp1252 que trae el padrón real (’ – Š) y bytes indefinidos (0x81).
        _, d = interpretar_fila(fila(R_OTRO, 'D’LIMA – ŠOLCOVÁ FICTICIA').encode('cp1252'), f)
        self.assertEqual(d['razon_social'], 'D’LIMA – ŠOLCOVÁ FICTICIA')
        estado, d = interpretar_fila(fila(R_OTRO, 'X').encode('cp1252').replace(b'|X|', b'|X\x81Y|'), f)
        self.assertEqual((estado, d['razon_social']), ('ok', 'X\ufffdY'))
        for enc in ('cp1252', 'latin-1', 'utf-8'):
            with self.subTest(enc=enc):
                cache.clear()
                PadronRuc.objects.all().delete()
                VersionPadronRuc.objects.all().delete()
                version, _ = importar_padron(self.zip(encoding=enc, nombre=f'{enc}.zip'))
                self.assertEqual(version.codificacion, 'cp1252' if enc == 'latin-1' else enc)
                self.assertEqual(PadronRuc.objects.get(ruc=R_EMPRESA).razon_social, 'COMERCIAL ÑANDÚ FICTICIA S.A.C.')

    # 10: separador detectado desde el encabezado; encabezado ajeno se rechaza
    def test_separador(self):
        filas = [fila(R_EMPRESA, 'EMPRESA FICTICIA PUNTO Y COMA', sep=';')]
        version, r = importar_padron(self.zip(filas, cabecera=CABECERA.replace('|', ';'), nombre='pyc.zip'))
        self.assertEqual((version.separador, r.validos), (';', 1))
        with self.assertRaisesRegex(ErrorImportacion, 'Encabezado inesperado'):
            importar_padron(self.zip(cabecera='CODIGO|DESCRIPCION|', nombre='otro.zip'))
        # Columnas en otro orden: se ubican por nombre, no por posición.
        cab = 'NOMBRE O RAZÓN SOCIAL|RUC|UBIGEO|ESTADO DEL CONTRIBUYENTE|CONDICIÓN DE DOMICILIO|'
        f = detectar_formato(cab.encode('cp1252'))
        estado, datos = interpretar_fila(f'EMPRESA FICTICIA ORDEN|{R_OTRO}|150101|ACTIVO|HABIDO|'.encode('cp1252'), f)
        self.assertEqual((estado, datos['ruc'], datos['razon_social'], datos['ubigeo']),
                         ('ok', R_OTRO, 'EMPRESA FICTICIA ORDEN', '150101'))

    # 11: fila válida y armado del domicilio (la columna DEPARTAMENTO es el dpto. del domicilio)
    def test_fila_valida(self):
        f = detectar_formato(CABECERA.encode('cp1252'))
        estado, d = interpretar_fila(FILAS_BASE[0].encode('latin-1'), f)
        self.assertEqual(estado, 'ok')
        self.assertEqual(d, {'ruc': R_EMPRESA, 'razon_social': 'COMERCIAL ÑANDÚ FICTICIA S.A.C.', 'estado': 'ACTIVO',
                             'condicion': 'HABIDO', 'ubigeo': '150122',
                             'domicilio_fiscal': 'AV. JOSE LARCO NRO. 1232 DPTO. 501 URB. MIRAFLORES'})
        _, d = interpretar_fila(FILAS_BASE[2].encode('latin-1'), f)
        self.assertEqual(d['domicilio_fiscal'], 'CAL. LOS ALAMOS MZA. B LOTE. 7')
        _, d = interpretar_fila(FILAS_BASE[1].encode('latin-1'), f)
        self.assertEqual((d['ubigeo'], d['domicilio_fiscal']), (None, None))  # '-' no se convierte en dato
        _, d = interpretar_fila(fila(R_OTRO, 'X FICTICIA', ubigeo='999999').encode('latin-1'), f)
        self.assertIsNone(d['ubigeo'])  # ubigeo con formato inválido no se guarda
        # Formas reales: '----' = sin tipo, zona con tipo y nombre, manzana/lote sin número.
        _, d = interpretar_fila(fila(R_OTRO, 'ASOCIACION FICTICIA', ubigeo='070106',
                                     direccion=['AV.', 'VENUS', 'A.H.', 'HIJOS DE GRAU', '-', '-', '12', '-', 'B', '-']).encode(), f)
        self.assertEqual(d['domicilio_fiscal'], 'AV. VENUS MZA. B LOTE. 12 A.H. HIJOS DE GRAU')
        _, d = interpretar_fila(fila(R_OTRO, 'X', direccion=['----', 'PROL. SAN MARTIN', '----', '-', '41', '-', '-', '-', '-', '-']).encode(), f)
        self.assertEqual(d['domicilio_fiscal'], 'PROL. SAN MARTIN NRO. 41')
        # '|' escapado como '\|' dentro de un valor (5 filas del padrón real).
        estado, d = interpretar_fila(f'{R_OTRO}|EBEN EZER \\| FICTICIA S.A.C.|ACTIVO|HABIDO|-|-|-|-|-|-|-|-|-|-|-|'.encode(), f)
        self.assertEqual((estado, d['razon_social']), ('ok', 'EBEN EZER | FICTICIA S.A.C.'))

    # 12: fila incompleta / 13: RUC inválido
    def test_fila_incompleta_y_ruc_invalido(self):
        malo_dv = R_EMPRESA[:10] + str((int(R_EMPRESA[10]) + 1) % 10)
        filas = [*FILAS_BASE, f'{R_OTRO}|INCOMPLETA FICTICIA|ACTIVO|', fila(R_OTRO, '-'), fila(malo_dv, 'DV MALO'),
                 fila('2061ABC0001', 'LETRAS'), fila('123', 'CORTO'), '']
        version, r = importar_padron(self.zip(filas))
        self.assertEqual((r.leidos, r.validos, r.incompletas, r.ruc_invalidos, r.omitidos), (8, 3, 2, 3, 5))
        self.assertEqual(version.registros_omitidos, 5)
        self.assertFalse(PadronRuc.objects.filter(ruc__in=[R_OTRO, malo_dv]).exists())

    # 14: duplicados (se conserva la primera aparición)
    def test_duplicados(self):
        version, r = importar_padron(self.zip([*FILAS_BASE, fila(R_EMPRESA, 'REPETIDA FICTICIA'), fila(R_PERSONA, 'OTRA')]))
        self.assertEqual((r.validos, r.duplicados), (3, 2))
        self.assertEqual(version.registros_duplicados, 2)
        self.assertEqual(PadronRuc.objects.get(ruc=R_EMPRESA).razon_social, 'COMERCIAL ÑANDÚ FICTICIA S.A.C.')

    # 15: importación por lotes (memoria acotada) y duplicados entre lotes distintos
    def test_lotes(self):
        filas = [fila(ruc(f'20{i:08d}'), f'EMPRESA FICTICIA {i}') for i in range(1, 251)] + [fila(ruc('2000000001'), 'DUP')]
        llamadas = []
        original = padron._cargar_lote

        def espia(version_id, lote):
            llamadas.append(len(lote))
            return original(version_id, lote)

        with mock.patch.object(padron, '_cargar_lote', side_effect=espia):
            _, r = importar_padron(self.zip(filas), lote=100)
        self.assertEqual(llamadas, [100, 100, 51])
        self.assertEqual((r.validos, r.duplicados), (250, 1))

    # 16: metadatos de la importación
    def test_metadatos(self):
        ruta = self.zip()
        version, r = importar_padron(ruta)
        self.assertEqual(version.fuente, padron.FUENTE_OFICIAL)
        self.assertEqual((version.archivo, version.archivo_interno), ('padron_reducido_ruc.zip', 'padron_reducido_ruc.txt'))
        self.assertEqual(version.sha256, padron.sha256_archivo(ruta))
        self.assertEqual(timezone.localtime(version.fecha_padron, padron.ZONA_SUNAT).isoformat(),
                         '2026-10-31T02:31:32-05:00')  # fecha/hora del TXT dentro del ZIP (hora de Perú)
        self.assertEqual((version.registros_leidos, version.registros_validos), (3, 3))
        self.assertIsNotNone(version.activada_en)
        self.assertTrue(version.completa)
        e = estado_padron()
        self.assertEqual((e['disponible'], e['registros'], e['fecha_padron'], e['version']), (True, 3, '2026-10-31', version.pk))
        # Otra fecha de publicación → otra fecha de versión (no es una constante).
        v2, _ = importar_padron(self.zip(fecha=(2026, 11, 7, 3, 0, 0), nombre='nov.zip'))
        self.assertEqual(estado_padron()['fecha_padron'], '2026-11-07')
        self.assertNotEqual(v2.pk, version.pk)


# =============================================================================================
class VersionadoTests(ConZip):
    # 17: activar una versión nueva retira la anterior (y libera sus filas)
    def test_activacion_nueva_version(self):
        v1, _ = self.importar()
        v2, _ = importar_padron(self.zip([fila(R_EMPRESA, 'NOMBRE NUEVO FICTICIO'), *FILAS_BASE[1:]], nombre='v2.zip'))
        v1.refresh_from_db()
        self.assertEqual((v1.estado, v2.estado), ('RETIRADA', 'ACTIVA'))
        # La retirada conserva sus filas (consultas en curso); las nuevas leen la activa.
        self.assertEqual(PadronRuc.objects.filter(version=v1).count(), 3)
        self.assertEqual(ProveedorPadronReducido().consultar(R_EMPRESA, timeout=1)['razon_social'], 'NOMBRE NUEVO FICTICIO')
        self.assertEqual(limpiar_versiones_retiradas(retencion_minutos=0), [v1.pk])
        self.assertEqual(PadronRuc.objects.filter(version=v1).count(), 0)
        v3, _ = importar_padron(self.zip(nombre='v3.zip'))
        self.assertEqual(PadronRuc.objects.filter(version=v2).count(), 3)  # recién retirada: se conserva
        self.assertEqual(VersionPadronRuc.objects.filter(estado='ACTIVA').get().pk, v3.pk)

    # 18: un fallo NO elimina la versión activa
    def test_fallo_no_elimina_activa(self):
        v1, _ = self.importar()
        casos = {
            'encabezado': self.zip(cabecera='X|Y|', nombre='malo.zip'),
            'sin_validos': self.zip([fila('123', 'X')], nombre='vacio.zip'),
            'caida_sospechosa': self.zip([FILAS_BASE[0]], nombre='truncado.zip'),
        }
        for caso, ruta in casos.items():
            with self.subTest(caso=caso), self.assertRaises(ErrorImportacion):
                importar_padron(ruta)
        # Error a mitad de la carga (p. ej. disco lleno en el 2.º lote): se descartan sus filas.
        original, n = padron._cargar_lote, {'i': 0}

        def falla(version_id, lote):
            n['i'] += 1
            if n['i'] == 2:
                raise OSError('disco lleno (simulado)')
            return original(version_id, lote)

        filas = [fila(ruc(f'20{i:08d}'), f'EMPRESA FICTICIA {i}') for i in range(1, 400)]
        with mock.patch.object(padron, '_cargar_lote', side_effect=falla):
            with self.assertRaisesRegex(ErrorImportacion, 'padrón activo no cambió'):
                importar_padron(self.zip(filas, nombre='disco.zip'), lote=100)
        v1.refresh_from_db()
        self.assertEqual(v1.estado, 'ACTIVA')
        self.assertEqual(PadronRuc.objects.filter(version=v1).count(), 3)
        self.assertEqual(PadronRuc.objects.exclude(version=v1).count(), 0)
        fallidas = VersionPadronRuc.objects.filter(estado='FALLIDA')
        self.assertEqual(fallidas.count(), 3)  # el encabezado malo falla antes de crear versión
        self.assertTrue(all(v.error and v.finalizado_en for v in fallidas))
        self.assertEqual(consultar_ruc(R_EMPRESA, proveedor=ProveedorPadronReducido())['datos']['ruc'], R_EMPRESA)
        # Con --permitir-reduccion la caída se acepta.
        v_chica, _ = importar_padron(casos['caida_sospechosa'], proporcion_minima=0)
        self.assertEqual(v_chica.estado, 'ACTIVA')

    def test_importacion_interrumpida_se_limpia(self):
        v1, _ = self.importar()
        colgada = VersionPadronRuc.objects.create(fuente='x', archivo='a', archivo_interno='a', sha256='z')
        PadronRuc.objects.create(version=colgada, ruc=R_OTRO, razon_social='PARCIAL')
        v2, _ = importar_padron(self.zip(nombre='v2.zip'))
        colgada.refresh_from_db()
        self.assertEqual((colgada.estado, PadronRuc.objects.filter(version=colgada).count()), ('FALLIDA', 0))
        self.assertEqual(v2.estado, 'ACTIVA')


# =============================================================================================
class ProveedorPadronTests(ConZip):
    # 19: encuentra / 22: mapeo / 23: oficial
    def test_encuentra_mapeo_y_oficial(self):
        self.importar()
        r = consultar_ruc(R_EMPRESA, proveedor=ProveedorPadronReducido())
        self.assertEqual(r['datos'], {
            'ruc': R_EMPRESA, 'razon_social': 'COMERCIAL ÑANDÚ FICTICIA S.A.C.', 'nombre_comercial': None,
            'direccion': 'AV. JOSE LARCO NRO. 1232 DPTO. 501 URB. MIRAFLORES', 'ubigeo': '150122',
            'departamento': None, 'provincia': None, 'distrito': None, 'estado': 'ACTIVO', 'condicion': 'HABIDO'})
        self.assertEqual((r['oficial'], r['fuente'], r['proveedor'], r['actualizado_al']),
                         (True, 'Padrón Reducido SUNAT', 'padron_reducido', '2026-10-31'))
        self.assertEqual(r['advertencias'], [])
        baja = consultar_ruc(R_BAJA, proveedor=ProveedorPadronReducido())
        self.assertEqual((baja['datos']['estado'], baja['datos']['condicion']), ('BAJA DE OFICIO', 'NO HALLADO'))
        self.assertEqual(len(baja['advertencias']), 2)  # se advierte, no se bloquea

    # 20: no encuentra (con padrón cargado)
    def test_no_encuentra(self):
        self.importar()
        with self.assertRaises(RucNoEncontrado) as ctx:
            consultar_ruc(R_OTRO, proveedor=ProveedorPadronReducido())
        self.assertEqual((ctx.exception.codigo, ctx.exception.proveedor), ('RUC_NO_ENCONTRADO', 'padron_reducido'))

    # 21: padrón no cargado ≠ RUC no encontrado
    def test_padron_no_cargado(self):
        with self.assertRaises(PadronNoCargado) as ctx:
            consultar_ruc(R_EMPRESA, proveedor=ProveedorPadronReducido())
        self.assertEqual((ctx.exception.codigo, ctx.exception.http_status), ('PADRON_RUC_NO_CARGADO', 503))
        self.assertIn('todavía no ha sido importado', ctx.exception.mensaje)
        # Solo versiones fallidas/retiradas: sigue sin padrón cargado.
        VersionPadronRuc.objects.create(fuente='x', archivo='a', archivo_interno='a', sha256='z', estado='FALLIDA')
        with self.assertRaises(PadronNoCargado):
            consultar_ruc(R_EMPRESA, proveedor=ProveedorPadronReducido())
        # El RUC inválido se rechaza antes (sin tocar el padrón).
        with self.assertRaisesRegex(Exception, 'RUC'):
            consultar_ruc('123', proveedor=ProveedorPadronReducido())

    def test_configuracion(self):
        with override_settings(CONSULTA_RUC_PROVEEDOR='padron_reducido', DEBUG=False, EJECUTANDO_TESTS=False):
            self.assertIsInstance(obtener_proveedor(), ProveedorPadronReducido)  # oficial: válido en producción
        with override_settings(CONSULTA_RUC_PROVEEDOR=' PADRON_REDUCIDO '):
            self.assertIsInstance(obtener_proveedor(), ProveedorPadronReducido)

    # 24: la clave de caché incluye la versión: un padrón nuevo no devuelve el dato viejo
    def test_cache_por_version(self):
        v1, _ = self.importar()
        p = ProveedorPadronReducido
        primera = consultar_ruc(R_EMPRESA, proveedor=p())
        self.assertTrue(consultar_ruc(R_EMPRESA, proveedor=p())['desde_cache'])
        self.assertEqual(clave_cache(R_EMPRESA, 'padron_reducido', f'v{v1.pk}'),
                         f'consulta_ruc:v2:padron_reducido:v{v1.pk}:{R_EMPRESA}')
        v2, _ = importar_padron(self.zip([fila(R_EMPRESA, 'RAZON ACTUALIZADA FICTICIA'), *FILAS_BASE[1:]], nombre='v2.zip'))
        nueva = consultar_ruc(R_EMPRESA, proveedor=p())
        self.assertEqual((primera['datos']['razon_social'], nueva['datos']['razon_social'], nueva['desde_cache']),
                         ('COMERCIAL ÑANDÚ FICTICIA S.A.C.', 'RAZON ACTUALIZADA FICTICIA', False))
        self.assertEqual(nueva['version_datos'], f'v{v2.pk}')


# =============================================================================================
@override_settings(CONSULTA_RUC_PROVEEDOR='padron_reducido', CONSULTA_RUC_THROTTLE_RATE='1000/min')
class EndpointPadronTests(ConZip):
    def setUp(self):
        super().setUp()
        pen = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(ruc=ruc('2010010017'), razon_social='EMPRESA 17D', moneda_base_codigo=pen)
        self.admin = Usuario.objects.create(username='admin17d', email='a17d@test.pe', password_hash='x')
        self.lector = Usuario.objects.create(username='lector17d', email='l17d@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=self.admin, empresa=self.empresa, rol='ADMIN')
        UsuarioEmpresa.objects.create(usuario=self.lector, empresa=self.empresa, rol='USUARIO')
        self.client = APIClient()
        self.h = {'HTTP_X_EMPRESA_ID': str(self.empresa.id)}

    def get(self, numero):
        return self.client.get(reverse('consulta-ruc', args=[numero]), **self.h)

    def estado(self):
        return self.client.get(reverse('consulta-ruc-estado'), **self.h)

    # 25: el endpoint existente responde con el padrón (mismo contrato)
    def test_endpoint(self):
        self.client.force_authenticate(user=self.admin)
        r = self.get(R_EMPRESA)
        self.assertEqual((r.status_code, r.data['codigo'] if r.status_code != 200 else None), (503, 'PADRON_RUC_NO_CARGADO'))
        self.assertEqual(set(r.data), {'codigo', 'mensaje'})
        self.importar()
        r = self.get(R_EMPRESA)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['datos']['razon_social'], r.data['oficial'], r.data['fuente']),
                         ('COMERCIAL ÑANDÚ FICTICIA S.A.C.', True, 'Padrón Reducido SUNAT'))
        self.assertEqual((self.get(R_OTRO).status_code, self.get(R_OTRO).data['codigo']), (404, 'RUC_NO_ENCONTRADO'))
        self.assertEqual(self.get('20610000000').data['codigo'], 'RUC_INVALIDO')

    # 26: permisos sin cambios (ADMIN de la empresa activa), también para el estado administrativo
    def test_permisos(self):
        self.importar()
        self.assertEqual((self.get(R_EMPRESA).status_code, self.estado().status_code), (401, 401))
        self.client.force_authenticate(user=self.lector)
        self.assertEqual((self.get(R_EMPRESA).status_code, self.estado().status_code), (403, 403))
        self.client.force_authenticate(user=self.admin)
        self.assertEqual((self.get(R_EMPRESA).status_code, self.estado().status_code), (200, 200))
        otra = self.client.get(reverse('consulta-ruc-estado'), HTTP_X_EMPRESA_ID='999999')
        self.assertEqual(otra.status_code, 403)

    # 27: auditoría con proveedor, versión y caché; nunca la respuesta completa
    def test_auditoria(self):
        self.client.force_authenticate(user=self.admin)
        self.get(R_EMPRESA)                 # padrón no cargado
        v, _ = self.importar()
        self.get(R_EMPRESA)
        self.get(R_EMPRESA)                 # caché
        self.get(R_OTRO)                    # no encontrado
        valores = [a.valor_nuevo for a in Auditoria.objects.filter(accion='CONSULTA_RUC').order_by('id')]
        self.assertEqual([(x['resultado'], x['proveedor'], x['version_datos'], x['desde_cache']) for x in valores], [
            ('PADRON_RUC_NO_CARGADO', 'padron_reducido', None, None),
            ('EXITO', 'padron_reducido', f'v{v.pk}', False),
            ('EXITO', 'padron_reducido', f'v{v.pk}', True),
            ('RUC_NO_ENCONTRADO', 'padron_reducido', None, None),
        ])
        texto = str(valores)
        for prohibido in ('ÑANDÚ', 'LARCO', 'razon_social', 'direccion'):
            self.assertNotIn(prohibido, texto)

    # 28: estado administrativo (solo metadatos)
    def test_estado_administrativo(self):
        self.client.force_authenticate(user=self.admin)
        r = self.estado()
        self.assertEqual(r.data, {'proveedor': 'padron_reducido', 'configurado': True, 'oficial': True,
                                  'fuente': 'Padrón Reducido SUNAT', 'disponible': False, 'registros': 0, 'version': None,
                                  'fecha_padron': None, 'fecha_importacion': None})
        v, _ = self.importar()
        r = self.estado()
        self.assertEqual((r.data['disponible'], r.data['registros'], r.data['version'], r.data['fecha_padron']),
                         (True, 3, v.pk, '2026-10-31'))
        self.assertTrue(r.data['fecha_importacion'])
        self.assertNotIn(R_EMPRESA, r.content.decode())  # nunca filas
        with override_settings(CONSULTA_RUC_PROVEEDOR=''):
            r = self.estado()
            self.assertEqual((r.data['proveedor'], r.data['configurado'], r.data['disponible']), (None, False, False))
        with override_settings(CONSULTA_RUC_PROVEEDOR='mock'):
            r = self.estado()
            self.assertEqual((r.data['proveedor'], r.data['oficial'], r.data['fuente']),
                             ('MOCK_DESARROLLO', False, 'Datos de prueba (no oficiales)'))


# =============================================================================================
class ComandosTests(ConZip):
    def test_importar_y_estado(self):
        salida = io.StringIO()
        call_command('estado_padron_ruc', stdout=salida)
        self.assertIn('Disponible: No', salida.getvalue())
        salida = io.StringIO()
        call_command('importar_padron_ruc', self.zip([*FILAS_BASE, fila('123', 'X')]), stdout=salida)
        texto = salida.getvalue()
        for esperado in ('Registros leídos: 4', 'Registros válidos: 3', 'Registros omitidos: 1', 'Duplicados: 0',
                         'Tiempo:', 'Versión: v', 'cp1252', "'|'"):
            self.assertIn(esperado, texto)
        self.assertNotIn('ÑANDÚ', texto)  # no imprime filas
        salida = io.StringIO()
        call_command('estado_padron_ruc', stdout=salida)
        self.assertIn('Disponible: Sí', salida.getvalue())
        self.assertIn('Registros: 3', salida.getvalue())
        with self.assertRaisesRegex(CommandError, 'no cambió'):
            call_command('importar_padron_ruc', os.path.join(self.dir, 'no_existe.zip'), stdout=io.StringIO())


# =============================================================================================
# Auditoría 17D, BAJO-1: una consulta que ya tomó la versión A no se queda sin datos al activar B.
class RetencionVersionRetiradaTests(ConZip):
    def test_carrera_consulta_en_curso_con_version_retirada(self):
        a, _ = self.importar()                                    # 1. A activa con el RUC
        en_curso = ProveedorPadronReducido()
        self.assertEqual(en_curso.version_datos(), f'v{a.pk}')    # 2. la consulta fija A
        b, _ = importar_padron(self.zip([fila(R_EMPRESA, 'RAZON EN B FICTICIA'), *FILAS_BASE[1:]], nombre='b.zip'))  # 3.
        # 4. la consulta iniciada con A termina con su dato (no RUC_NO_ENCONTRADO)
        r = consultar_ruc(R_EMPRESA, proveedor=en_curso, usar_cache=False)
        self.assertEqual((r['datos']['razon_social'], r['version_datos']), ('COMERCIAL ÑANDÚ FICTICIA S.A.C.', f'v{a.pk}'))
        # 5. las consultas nuevas usan B
        r = consultar_ruc(R_EMPRESA, proveedor=ProveedorPadronReducido(), usar_cache=False)
        self.assertEqual((r['datos']['razon_social'], r['version_datos']), ('RAZON EN B FICTICIA', f'v{b.pk}'))
        # 6. limpieza controlada: dentro del plazo no se borra; pasado el plazo sí, solo A
        self.assertEqual(limpiar_versiones_retiradas(), [])
        self.assertEqual([v.pk for v in versiones_retiradas_con_filas()], [a.pk])
        self.assertEqual(limpiar_versiones_retiradas(ahora=timezone.now() + timedelta(minutes=11)), [a.pk])
        a.refresh_from_db()
        self.assertEqual((a.estado, a.registros_validos), ('RETIRADA', 3))   # metadatos conservados
        self.assertEqual(PadronRuc.objects.filter(version=a).count(), 0)
        self.assertEqual(PadronRuc.objects.filter(version=b).count(), 3)      # la activa nunca se toca
        self.assertEqual(limpiar_versiones_retiradas(retencion_minutos=0), [])  # idempotente

    def test_la_importacion_limpia_retiradas_viejas_y_conserva_la_reciente(self):
        v1, _ = self.importar()
        v2, _ = importar_padron(self.zip(nombre='v2.zip'))
        VersionPadronRuc.objects.filter(pk=v2.pk).update(activada_en=timezone.now() - timedelta(hours=2))  # v1 retirada hace 2 h
        v3, _ = importar_padron(self.zip(nombre='v3.zip'))
        self.assertEqual(PadronRuc.objects.filter(version=v1).count(), 0)   # vieja: se limpió al empezar
        self.assertEqual(PadronRuc.objects.filter(version=v2).count(), 3)   # recién retirada: se conserva
        self.assertEqual(PadronRuc.objects.filter(version=v3).count(), 3)
        # Sin limpieza (opción --sin-limpieza) no se borra nada.
        VersionPadronRuc.objects.filter(pk=v3.pk).update(activada_en=timezone.now() - timedelta(hours=2))
        importar_padron(self.zip(nombre='v4.zip'), limpiar_retiradas=False)
        self.assertEqual(PadronRuc.objects.filter(version=v2).count(), 3)

    def test_comando_limpiar_padrones_ruc(self):
        v1, _ = self.importar()
        importar_padron(self.zip(nombre='v2.zip'))
        salida = io.StringIO()
        call_command('limpiar_padrones_ruc', stdout=salida)
        self.assertIn(f'Se conservan (dentro del plazo de retención): v{v1.pk}', salida.getvalue())
        salida = io.StringIO()
        call_command('estado_padron_ruc', stdout=salida)
        self.assertIn(f'Versiones retiradas aún con filas (se limpian con limpiar_padrones_ruc): v{v1.pk}', salida.getvalue())
        salida = io.StringIO()
        call_command('limpiar_padrones_ruc', '--retencion-minutos', '0', stdout=salida)
        self.assertIn(f'Filas borradas de las versiones retiradas: v{v1.pk}.', salida.getvalue())
        self.assertEqual(PadronRuc.objects.filter(version=v1).count(), 0)

    # Auditoría final 17D, MEDIO: --retencion-minutos solo acepta enteros >= 0.
    def test_comando_limpiar_rechaza_retencion_negativa(self):
        v1, _ = self.importar()
        v2, _ = importar_padron(self.zip(nombre='v2.zip'))
        # v1 es elegible incluso con la retención por defecto: un -1 no debe ni tocarla ni nada más.
        VersionPadronRuc.objects.filter(pk=v2.pk).update(activada_en=timezone.now() - timedelta(hours=2))
        antes = list(VersionPadronRuc.objects.order_by('id').values_list('id', 'estado', 'registros_validos', 'activada_en'))
        filas_antes = PadronRuc.objects.count()
        for valor in ('-1', '-60', 'abc', '1.5'):
            with self.subTest(valor=valor):
                with self.assertRaisesRegex(CommandError, 'entero mayor o igual a 0'):
                    call_command('limpiar_padrones_ruc', '--retencion-minutos', valor, stdout=io.StringIO())
        with self.assertRaisesRegex(CommandError, 'entero mayor o igual a 0'):
            call_command('limpiar_padrones_ruc', '--retencion-minutos=-1', stdout=io.StringIO())
        self.assertEqual(PadronRuc.objects.count(), filas_antes)
        self.assertEqual(PadronRuc.objects.filter(version=v1).count(), 3)
        self.assertEqual(list(VersionPadronRuc.objects.order_by('id').values_list('id', 'estado', 'registros_validos', 'activada_en')), antes)
        self.assertEqual(VersionPadronRuc.objects.get(estado='ACTIVA').pk, v2.pk)
        # La función tampoco corrige negativos en silencio.
        with self.assertRaises(ValueError):
            limpiar_versiones_retiradas(retencion_minutos=-1)
        self.assertEqual(PadronRuc.objects.filter(version=v1).count(), 3)
        # 0 sigue permitido (limpieza manual explícita) y solo borra la retirada.
        salida = io.StringIO()
        call_command('limpiar_padrones_ruc', '--retencion-minutos', '0', stdout=salida)
        self.assertIn(f'Filas borradas de las versiones retiradas: v{v1.pk}.', salida.getvalue())
        self.assertEqual((PadronRuc.objects.filter(version=v1).count(), PadronRuc.objects.filter(version=v2).count()), (0, 3))

    # Auditoría final 17D, BAJO: el argumento real --sin-limpieza del comando de importación.
    def test_comando_importar_sin_limpieza(self):
        v1, _ = self.importar()
        v2, _ = importar_padron(self.zip(nombre='v2.zip'))
        # 1. v1 retirada hace 2 h: elegible para la limpieza que hace la importación al empezar.
        VersionPadronRuc.objects.filter(pk=v2.pk).update(activada_en=timezone.now() - timedelta(hours=2))
        self.assertEqual([v.pk for v in versiones_retiradas_con_filas()], [v1.pk])
        # 2-3. comando real con --sin-limpieza
        salida = io.StringIO()
        with mock.patch.object(padron, 'limpiar_versiones_retiradas', wraps=padron.limpiar_versiones_retiradas) as limpieza:
            call_command('importar_padron_ruc', self.zip(nombre='v3.zip'), '--sin-limpieza', stdout=salida)
        self.assertIn('Padrón importado y activado.', salida.getvalue())
        # 4. la nueva queda activa
        v3 = VersionPadronRuc.objects.get(estado='ACTIVA')
        self.assertNotIn(v3.pk, (v1.pk, v2.pk))
        self.assertEqual(PadronRuc.objects.filter(version=v3).count(), 3)
        # 5-6. la retirada elegible conserva sus filas: no se ejecutó la limpieza
        limpieza.assert_not_called()
        self.assertEqual(PadronRuc.objects.filter(version=v1).count(), 3)
        self.assertEqual(PadronRuc.objects.filter(version=v2).count(), 3)
        self.assertEqual([v.pk for v in versiones_retiradas_con_filas()], [v1.pk, v2.pk])
        # Contraste: sin la opción, la misma situación SÍ limpia la retirada vieja al empezar.
        VersionPadronRuc.objects.filter(pk=v3.pk).update(activada_en=timezone.now() - timedelta(hours=1))
        call_command('importar_padron_ruc', self.zip(nombre='v4.zip'), stdout=io.StringIO())
        self.assertEqual((PadronRuc.objects.filter(version=v1).count(), PadronRuc.objects.filter(version=v2).count()), (0, 0))


# =============================================================================================
# Auditoría 17D, MEDIO-1: el candado es de PostgreSQL y se prueba con conexiones REALES distintas.
def en_otra_conexion(funcion, *args, **kwargs):
    """
    Ejecuta `funcion` en otro hilo. Django abre una conexión PROPIA por hilo a la MISMA base de
    pruebas (misma configuración, sin hosts ni claves escritos aquí). Devuelve (resultado, error, pid).
    """
    salida = {}

    def correr():
        try:
            with connection.cursor() as cur:
                cur.execute('SELECT pg_backend_pid(), current_database()')
                salida['pid'], salida['base'] = cur.fetchone()
            salida['resultado'] = funcion(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — se devuelve para afirmarlo en la prueba
            salida['error'] = exc
        finally:
            connections.close_all()  # cierra la conexión de ESTE hilo

    hilo = threading.Thread(target=correr)
    hilo.start()
    hilo.join(timeout=120)
    assert not hilo.is_alive(), 'el hilo de la conexión B no terminó'
    return salida.get('resultado'), salida.get('error'), salida.get('pid'), salida.get('base')


def candados_asesores():
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND database = "
                    '(SELECT oid FROM pg_database WHERE datname = current_database())')
        return cur.fetchone()[0]


class CandadoPostgresTests(ZipTemporal, TransactionTestCase):
    """
    Conexión A = la del hilo de la prueba; conexión B = la de otro hilo. Son sesiones distintas de
    PostgreSQL (pg_backend_pid distinto) sobre la base de pruebas que crea Django.
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(self._soltar_candado_a)

    def _soltar_candado_a(self):
        with connection.cursor() as cur:
            cur.execute('SELECT pg_advisory_unlock_all()')

    def _pid_a(self):
        with connection.cursor() as cur:
            cur.execute('SELECT pg_backend_pid(), current_database()')
            return cur.fetchone()

    def test_dos_conexiones_no_importan_a_la_vez(self):
        activa, _ = self.importar()
        pid_a, base_a = self._pid_a()
        self.assertTrue(base_a.startswith('test_'))  # nunca la base real
        # 1. A toma el candado de importación
        with connection.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', [CANDADO_IMPORTACION])
            self.assertTrue(cur.fetchone()[0])
        # 2-3. B intenta importar y recibe el error del contrato
        _, error, pid_b, base_b = en_otra_conexion(importar_padron, self.zip(nombre='b.zip'))
        self.assertNotEqual(pid_a, pid_b)          # conexiones independientes de verdad
        self.assertEqual(base_a, base_b)           # misma base de pruebas
        self.assertIsInstance(error, ErrorImportacion)
        self.assertIn('Ya hay otra importación del padrón en curso', str(error))
        # 4. la versión activa no cambió y B no dejó versiones a medias
        self.assertEqual(VersionPadronRuc.objects.get(estado='ACTIVA').pk, activa.pk)
        self.assertEqual(VersionPadronRuc.objects.count(), 1)
        # 5-6. A libera; ahora B importa sin problema
        with connection.cursor() as cur:
            cur.execute('SELECT pg_advisory_unlock(%s)', [CANDADO_IMPORTACION])
            self.assertTrue(cur.fetchone()[0])
        resultado, error, pid_b2, _ = en_otra_conexion(importar_padron, self.zip(nombre='b2.zip'))
        self.assertIsNone(error)
        self.assertNotEqual(pid_a, pid_b2)
        self.assertEqual(VersionPadronRuc.objects.get(estado='ACTIVA').pk, resultado[0].pk)
        # Tras el éxito B soltó el candado: A puede tomarlo de nuevo.
        with connection.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s)', [CANDADO_IMPORTACION])
            self.assertTrue(cur.fetchone()[0])
            cur.execute('SELECT pg_advisory_unlock(%s)', [CANDADO_IMPORTACION])
        # 8. no quedan candados persistentes
        self.assertEqual(candados_asesores(), 0)

    def test_importacion_real_en_curso_bloquea_a_la_otra(self):
        """A está REALMENTE importando (pausada a mitad de la carga) mientras B intenta importar."""
        activa, _ = self.importar()
        cargando, seguir = threading.Event(), threading.Event()

        def pausar(_resumen):
            cargando.set()
            seguir.wait(timeout=60)

        filas = [fila(ruc(f'20{i:08d}'), f'EMPRESA FICTICIA {i}') for i in range(1, 300)]
        hilo_a_salida = {}

        def importar_en_a():
            try:
                hilo_a_salida['r'] = importar_padron(self.zip(filas, nombre='a.zip'), lote=100, progreso=pausar)
            except Exception as exc:  # noqa: BLE001
                hilo_a_salida['e'] = exc
            finally:
                connections.close_all()

        hilo_a = threading.Thread(target=importar_en_a)
        hilo_a.start()
        try:
            self.assertTrue(cargando.wait(timeout=60))   # A tiene el candado y está cargando
            _, error, _, _ = en_otra_conexion(importar_padron, self.zip(nombre='b.zip'))
            self.assertIsInstance(error, ErrorImportacion)
            self.assertIn('Ya hay otra importación', str(error))
            self.assertEqual(VersionPadronRuc.objects.get(estado='ACTIVA').pk, activa.pk)  # aún la anterior
        finally:
            seguir.set()
            hilo_a.join(timeout=120)
        self.assertNotIn('e', hilo_a_salida)
        self.assertEqual(VersionPadronRuc.objects.get(estado='ACTIVA').pk, hilo_a_salida['r'][0].pk)
        self.assertEqual(candados_asesores(), 0)

    def test_el_candado_se_libera_si_la_importacion_falla(self):
        pid_a, _ = self._pid_a()
        # 7. B toma el candado y falla DESPUÉS de tenerlo (encabezado inválido / sin registros válidos)
        for ruta in (self.zip(cabecera='X|Y|', nombre='malo.zip'), self.zip([fila('123', 'X')], nombre='vacio.zip')):
            _, error, pid_b, _ = en_otra_conexion(importar_padron, ruta)
            self.assertNotEqual(pid_a, pid_b)
            self.assertIsInstance(error, ErrorImportacion)
            with connection.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(%s)', [CANDADO_IMPORTACION])
                self.assertTrue(cur.fetchone()[0])   # B lo liberó aunque falló
                cur.execute('SELECT pg_advisory_unlock(%s)', [CANDADO_IMPORTACION])
        self.assertFalse(VersionPadronRuc.objects.filter(estado='ACTIVA').exists())
        self.assertEqual(candados_asesores(), 0)
