"""
Pruebas unitarias del Paso 2: modelo `ImportacionTrabajo` y servicio de staging `importacion_staging`.
"""
import hashlib
import tempfile
from pathlib import Path

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.importacion_kardex_confirmar import confirmar_importacion_kardex
from apps.documentos.importacion_staging import (
    guardar_archivos_staging,
    leer_archivos_staging,
    limpiar_staging,
    sanitizar_nombre_archivo,
)
from apps.documentos.models import ImportacionLote, ImportacionTrabajo
from apps.documentos.tests_importacion_kardex import OPC, compra, excel


class ImportacionTrabajoModelTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.crear_producto('011004')
        res = confirmar_importacion_kardex(
            empresa_id=self.empresa.id,
            usuario=self.usuario,
            archivos=[('inicial.xlsx', excel([compra('011004', 2, 'F001', 1, 10, 12)], OPC))],
            almacen_id=self.almacen.id,
        )
        self.lote = ImportacionLote.objects.get(pk=res['lote'])

    def test_creacion_y_transiciones_de_estado(self):
        trabajo = ImportacionTrabajo.objects.create(
            empresa=self.empresa,
            usuario=self.usuario,
            tipo='CONFIRMAR',
            almacen=self.almacen,
            parametros_json={'proveedores': {'clave': '20555000111'}},
        )
        self.assertEqual(trabajo.estado, 'EN_COLA')
        self.assertEqual(trabajo.intentos, 0)
        self.assertEqual(trabajo.archivos_meta_json, [])
        self.assertEqual(trabajo.resumen_json, {})

        for nuevo_estado in ('PROCESANDO', 'COMPLETADO'):
            trabajo.estado = nuevo_estado
            trabajo.save(update_fields=['estado'])
            trabajo.refresh_from_db()
            self.assertEqual(trabajo.estado, nuevo_estado)

    def test_constraints_tipo_y_estado(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ImportacionTrabajo.objects.create(
                    empresa=self.empresa, usuario=self.usuario, tipo='OTRO',
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ImportacionTrabajo.objects.create(
                    empresa=self.empresa, usuario=self.usuario, tipo='CONFIRMAR', estado='INVALIDO',
                )

    def test_impide_dos_trabajos_anular_activos_sobre_mismo_lote(self):
        primero = ImportacionTrabajo.objects.create(
            empresa=self.empresa,
            usuario=self.usuario,
            tipo='ANULAR',
            estado='EN_COLA',
            lote=self.lote,
            parametros_json={'motivo': 'Prueba anulación'},
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ImportacionTrabajo.objects.create(
                    empresa=self.empresa,
                    usuario=self.usuario,
                    tipo='ANULAR',
                    estado='EN_COLA',
                    lote=self.lote,
                    parametros_json={'motivo': 'Duplicado'},
                )

        primero.estado = 'PROCESANDO'
        primero.save(update_fields=['estado'])
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ImportacionTrabajo.objects.create(
                    empresa=self.empresa,
                    usuario=self.usuario,
                    tipo='ANULAR',
                    estado='PROCESANDO',
                    lote=self.lote,
                )

        # Cuando finaliza en ERROR o COMPLETADO, sí se puede volver a encolar otro ANULAR
        primero.estado = 'ERROR'
        primero.save(update_fields=['estado'])
        segundo = ImportacionTrabajo.objects.create(
            empresa=self.empresa,
            usuario=self.usuario,
            tipo='ANULAR',
            estado='EN_COLA',
            lote=self.lote,
        )
        self.assertEqual(segundo.lote_id, self.lote.id)


class ImportacionStagingTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def test_sanitizar_nombre_elimina_path_traversal(self):
        self.assertEqual(sanitizar_nombre_archivo('../../etc/passwd.xlsx'), 'passwd.xlsx')
        self.assertEqual(sanitizar_nombre_archivo(r'C:\fakepath\..archivo malo (1).xlsx'), 'archivo_malo_1_.xlsx')
        self.assertEqual(sanitizar_nombre_archivo('...'), 'archivo.xlsx')

    def test_guardar_leer_integridad_y_limpieza_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'staging'
            with override_settings(IMPORTACION_STAGING_DIR=root):
                trabajo = ImportacionTrabajo.objects.create(
                    empresa=self.empresa, usuario=self.usuario, tipo='CONFIRMAR', almacen=self.almacen,
                )
                buf1 = excel([compra('011004', 2, 'F001', 10, 5, 12)], OPC)
                bytes1 = buf1.getvalue()
                bytes2 = b'contenido-excel-2'

                rel_dir, meta = guardar_archivos_staging(
                    trabajo.id,
                    [('../../malicioso.xlsx', bytes1), ('malicioso.xlsx', bytes2)],
                )
                trabajo.staging_dir = rel_dir
                trabajo.archivos_meta_json = meta
                trabajo.save(update_fields=['staging_dir', 'archivos_meta_json'])

                self.assertEqual(rel_dir, f'trabajo_{trabajo.id}')
                self.assertEqual(len(meta), 2)
                self.assertEqual(meta[0]['tamano'], len(bytes1))
                self.assertEqual(meta[0]['sha256'], hashlib.sha256(bytes1).hexdigest())
                self.assertNotEqual(meta[0]['ruta_relativa'], meta[1]['ruta_relativa'])
                self.assertTrue((root / meta[0]['ruta_relativa']).is_file())

                leidos = leer_archivos_staging(trabajo)
                self.assertEqual(len(leidos), 2)
                self.assertEqual(leidos[0][0], '../../malicioso.xlsx')
                self.assertEqual(leidos[0][1].read(), bytes1)
                self.assertEqual(leidos[1][1].read(), bytes2)

                self.assertTrue(limpiar_staging(trabajo))
                self.assertFalse((root / rel_dir).exists())
                self.assertTrue(root.exists())

    def test_detecta_corrupcion_y_manipulacion_en_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'staging'
            with override_settings(IMPORTACION_STAGING_DIR=root):
                trabajo = ImportacionTrabajo.objects.create(
                    empresa=self.empresa, usuario=self.usuario, tipo='CONFIRMAR', almacen=self.almacen,
                )
                datos = b'excel-integro-123'
                rel_dir, meta = guardar_archivos_staging(trabajo.id, [('datos.xlsx', datos)])
                trabajo.staging_dir = rel_dir
                trabajo.archivos_meta_json = meta
                trabajo.save(update_fields=['staging_dir', 'archivos_meta_json'])

                # 1. Manipulación con mismo tamaño (hash distinto)
                archivo_disco = root / meta[0]['ruta_relativa']
                archivo_disco.write_bytes(b'excel-integro-999')
                with self.assertRaisesMessage(ValidationError, 'SHA-256'):
                    leer_archivos_staging(trabajo)

                # 2. Tamaño alterado
                archivo_disco.write_bytes(b'corto')
                with self.assertRaisesMessage(ValidationError, 'Tamaño alterado'):
                    leer_archivos_staging(trabajo)

                # 3. Archivo borrado
                archivo_disco.unlink()
                with self.assertRaisesMessage(ValidationError, 'No se encontró el archivo'):
                    leer_archivos_staging(trabajo)

                # 4. Path traversal en metadata o staging_dir no permitido en lectura/limpieza
                exterior = Path(tmp) / 'fuera'
                exterior.mkdir()
                (exterior / 'secreto.xlsx').write_bytes(datos)
                trabajo.archivos_meta_json = [{
                    'nombre': 'secreto.xlsx',
                    'ruta_relativa': '../../fuera/secreto.xlsx',
                    'tamano': len(datos),
                    'sha256': hashlib.sha256(datos).hexdigest(),
                }]
                with self.assertRaisesMessage(ValidationError, 'fuera de rango'):
                    leer_archivos_staging(trabajo)

                trabajo.staging_dir = '../fuera'
                self.assertFalse(limpiar_staging(trabajo))
                self.assertTrue(exterior.exists())
