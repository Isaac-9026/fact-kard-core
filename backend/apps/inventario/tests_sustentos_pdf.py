import hashlib
import os
import shutil
import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda, TipoExistencia, TipoOperacion, UnidadMedida
from apps.empresas.models import CierrePeriodo, ConfigEmpresa, Empresa, Establecimiento, Periodo
from apps.empresas.services import cerrar_periodo
from apps.inventario.models import Almacen, NotaInterna, NotaInternaDetalle, Producto, ProductoUnidad
from apps.usuarios.models import Usuario, UsuarioEmpresa


class SustentosPdfTestCase(TestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_dir)
        self.override.enable()

        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.tipo_existencia = TipoExistencia.objects.create(codigo='01', descripcion='MERCADERÍA')
        self.unidad = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDAD')

        self.empresa_a = Empresa.objects.create(
            ruc='20610000001', razon_social='EMPRESA A', moneda_base_codigo=self.moneda
        )
        self.empresa_b = Empresa.objects.create(
            ruc='20610000002', razon_social='EMPRESA B', moneda_base_codigo=self.moneda
        )

        self.est_a = Establecimiento.objects.create(
            empresa=self.empresa_a, codigo_sunat='0001', nombre='SEDE A'
        )
        self.est_b = Establecimiento.objects.create(
            empresa=self.empresa_b, codigo_sunat='0001', nombre='SEDE B'
        )
        ConfigEmpresa.objects.create(
            empresa=self.empresa_a, establecimiento_principal=self.est_a
        )

        self.almacen_a = Almacen.objects.create(
            empresa=self.empresa_a, establecimiento=self.est_a, codigo='A01', nombre='ALMACÉN A'
        )
        self.almacen_b = Almacen.objects.create(
            empresa=self.empresa_b, establecimiento=self.est_b, codigo='B01', nombre='ALMACÉN B'
        )

        self.producto_a = Producto.objects.create(
            empresa=self.empresa_a, codigo_interno='PROD_A', descripcion='PRODUCTO A',
            tipo_existencia_codigo=self.tipo_existencia
        )
        ProductoUnidad.objects.create(
            producto=self.producto_a, unidad_codigo=self.unidad,
            factor_a_base=Decimal('1.00000000'), es_base=True
        )

        self.periodo_a = Periodo.objects.create(
            empresa=self.empresa_a, anio=2026, mes=1, orden=202601,
            fecha_inicio='2026-01-01', fecha_fin='2026-01-31', estado='ABIERTO'
        )

        self.tipo_op_merma = TipoOperacion.objects.create(
            codigo_interno='MERMA', descripcion='MERMA', naturaleza='SALIDA',
            es_interna=True, origen_requerido='NOTA_INTERNA', activo=True
        )

        self.admin_a = Usuario.objects.create(
            username='admin_sustento_a', email='admin_a@test.pe', password_hash='hash'
        )
        UsuarioEmpresa.objects.create(
            usuario=self.admin_a, empresa=self.empresa_a, rol='ADMIN'
        )

        self.admin_b = Usuario.objects.create(
            username='admin_sustento_b', email='admin_b@test.pe', password_hash='hash'
        )
        UsuarioEmpresa.objects.create(
            usuario=self.admin_b, empresa=self.empresa_b, rol='ADMIN'
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_a)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _headers(self, empresa_id=None):
        emp_id = empresa_id or self.empresa_a.id
        return {'HTTP_X_EMPRESA_ID': str(emp_id)}

    def test_adjuntar_descargar_y_preservar_pdf_en_nota_interna(self):
        # 1. Crear nota interna en BORRADOR
        nota = NotaInterna.objects.create(
            empresa=self.empresa_a,
            almacen=self.almacen_a,
            periodo=self.periodo_a,
            tipo_operacion=self.tipo_op_merma,
            fecha='2026-01-10',
            motivo='Merma inicial de prueba',
            archivo_sustento='Acta Notarial N° 100',
            estado='BORRADOR',
            creado_por=self.admin_a,
        )
        NotaInternaDetalle.objects.create(
            nota_interna=nota,
            producto=self.producto_a,
            cantidad_base=Decimal('5.00000000'),
        )

        pdf_bytes = b'%PDF-1.4 prueba de informe tecnico de destruccion de desmedros'
        pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
        archivo_subido = SimpleUploadedFile(
            'informe_tecnico.pdf', pdf_bytes, content_type='application/pdf'
        )

        url_sustento = f'/api/inventario/notas-internas/{nota.id}/sustento-pdf/'

        # 2. Subir PDF a la nota
        resp_subir = self.client.post(
            url_sustento,
            {'archivo': archivo_subido, 'referencia_legal': 'Acta Notarial N° 100-2026'},
            format='multipart',
            **self._headers(),
        )
        self.assertEqual(resp_subir.status_code, 200)
        data = resp_subir.json()
        self.assertEqual(data['archivo_sustento'], 'Acta Notarial N° 100-2026')
        self.assertIsNotNone(data.get('sustento_pdf'))
        self.assertTrue(data['sustento_pdf']['tiene_pdf'])
        self.assertEqual(data['sustento_pdf']['sha256'], pdf_sha)
        self.assertEqual(data['sustento_pdf']['nombre_archivo'], 'informe_tecnico.pdf')

        # 3. PATCH de la nota actualizando motivo y archivo_sustento textual: debe preservar el PDF vinculado
        url_detalle = f'/api/inventario/notas-internas/{nota.id}/'
        resp_patch = self.client.patch(
            url_detalle,
            {
                'motivo': 'Merma actualizada con justificacion',
                'archivo_sustento': 'Acta Notarial N° 100-2026 Ampliada',
            },
            format='json',
            **self._headers(),
        )
        self.assertEqual(resp_patch.status_code, 200)
        data_patch = resp_patch.json()
        self.assertEqual(data_patch['motivo'], 'Merma actualizada con justificacion')
        self.assertEqual(data_patch['archivo_sustento'], 'Acta Notarial N° 100-2026 Ampliada')
        self.assertIsNotNone(data_patch.get('sustento_pdf'))
        self.assertTrue(data_patch['sustento_pdf']['tiene_pdf'])
        self.assertEqual(data_patch['sustento_pdf']['sha256'], pdf_sha)

        # 4. Confirmar nota interna
        nota.estado = 'CONFIRMADO'
        nota.save(update_fields=['estado'])

        # 5. Intentar sobrescribir el PDF en estado CONFIRMADO debe rechazar con 400 Bad Request
        otro_pdf = SimpleUploadedFile(
            'otro.pdf', b'%PDF-1.4 otro contenido', content_type='application/pdf'
        )
        resp_sobrescribir = self.client.post(
            url_sustento,
            {'archivo': otro_pdf},
            format='multipart',
            **self._headers(),
        )
        self.assertEqual(resp_sobrescribir.status_code, 400)
        self.assertIn('No se puede reemplazar', resp_sobrescribir.json()['detail'])

        # 6. Descargar el archivo PDF
        resp_descarga = self.client.get(url_sustento, **self._headers())
        self.assertEqual(resp_descarga.status_code, 200)
        self.assertEqual(resp_descarga['Content-Type'], 'application/pdf')
        self.assertIn('attachment', resp_descarga['Content-Disposition'])
        self.assertEqual(b''.join(resp_descarga.streaming_content), pdf_bytes)

    def test_rechaza_archivo_no_pdf_y_aislamiento_multitenant(self):
        nota = NotaInterna.objects.create(
            empresa=self.empresa_a,
            almacen=self.almacen_a,
            periodo=self.periodo_a,
            tipo_operacion=self.tipo_op_merma,
            fecha='2026-01-10',
            motivo='Merma test rechazo',
            estado='BORRADOR',
            creado_por=self.admin_a,
        )
        NotaInternaDetalle.objects.create(
            nota_interna=nota, producto=self.producto_a, cantidad_base=Decimal('1')
        )
        url_sustento = f'/api/inventario/notas-internas/{nota.id}/sustento-pdf/'

        # Rechazo por extensión no .pdf
        archivo_txt = SimpleUploadedFile('documento.txt', b'contenido texto', content_type='text/plain')
        resp_txt = self.client.post(url_sustento, {'archivo': archivo_txt}, format='multipart', **self._headers())
        self.assertEqual(resp_txt.status_code, 400)

        # Rechazo por contenido que no inicia con %PDF-
        archivo_falso_pdf = SimpleUploadedFile('falso.pdf', b'NO_ES_PDF_REAL', content_type='application/pdf')
        resp_falso = self.client.post(url_sustento, {'archivo': archivo_falso_pdf}, format='multipart', **self._headers())
        self.assertEqual(resp_falso.status_code, 400)

        # Adjuntar PDF válido
        pdf_bytes = b'%PDF-1.4 contenido valido'
        archivo_valido = SimpleUploadedFile('valido.pdf', pdf_bytes, content_type='application/pdf')
        resp_valido = self.client.post(url_sustento, {'archivo': archivo_valido}, format='multipart', **self._headers())
        self.assertEqual(resp_valido.status_code, 200)

        # Aislamiento multitenant: empresa B no puede consultar ni descargar el PDF de la empresa A
        self.client.force_authenticate(user=self.admin_b)
        resp_otra_empresa = self.client.get(url_sustento, **self._headers(self.empresa_b.id))
        self.assertEqual(resp_otra_empresa.status_code, 404)

    def test_adjuntar_y_descargar_sustento_pdf_en_cierre_periodo(self):
        cierre, _ = cerrar_periodo(
            empresa_id=self.empresa_a.id,
            periodo_id=self.periodo_a.id,
            usuario=self.admin_a,
        )
        self.assertTrue(cierre.vigente)

        url_cierre_pdf = f'/api/empresas/cierres/{cierre.id}/sustento-pdf/'
        pdf_bytes = b'%PDF-1.4 acta notarial de cierre de inventario anual'
        pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
        archivo_cierre = SimpleUploadedFile(
            'acta_cierre_2026.pdf', pdf_bytes, content_type='application/pdf'
        )

        # 1. Adjuntar sustento al cierre
        resp_subir = self.client.post(
            url_cierre_pdf,
            {'archivo': archivo_cierre, 'referencia': 'Acta Notarial N° 12 de Cierre'},
            format='multipart',
            **self._headers(),
        )
        self.assertEqual(resp_subir.status_code, 200)
        data = resp_subir.json()
        self.assertIsNotNone(data.get('sustento_pdf'))
        self.assertTrue(data['sustento_pdf']['tiene_pdf'])
        self.assertEqual(data['sustento_pdf']['sha256'], pdf_sha)
        self.assertEqual(data['sustento_pdf']['nombre_archivo'], 'acta_cierre_2026.pdf')
        self.assertEqual(data['sustento_pdf']['referencia'], 'Acta Notarial N° 12 de Cierre')

        # 2. Segundo intento debe ser rechazado por inmutabilidad
        otro_archivo = SimpleUploadedFile(
            'otro_cierre.pdf', b'%PDF-1.4 otro', content_type='application/pdf'
        )
        resp_segundo = self.client.post(
            url_cierre_pdf, {'archivo': otro_archivo}, format='multipart', **self._headers()
        )
        self.assertEqual(resp_segundo.status_code, 400)

        # 3. Descarga del PDF
        resp_descarga = self.client.get(url_cierre_pdf, **self._headers())
        self.assertEqual(resp_descarga.status_code, 200)
        self.assertEqual(resp_descarga['Content-Type'], 'application/pdf')
        self.assertEqual(b''.join(resp_descarga.streaming_content), pdf_bytes)

        # 4. Multitenant isolation
        self.client.force_authenticate(user=self.admin_b)
        resp_otra_empresa = self.client.get(url_cierre_pdf, **self._headers(self.empresa_b.id))
        self.assertEqual(resp_otra_empresa.status_code, 404)
