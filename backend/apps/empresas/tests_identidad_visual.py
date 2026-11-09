import io
import shutil
import tempfile
from PIL import Image

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda
from apps.empresas.models import ConfigEmpresa, Empresa
from apps.usuarios.models import Usuario, UsuarioEmpresa


def _crear_imagen_bytes(formato='PNG', size=(64, 64), color=(79, 70, 229)):
    buf = io.BytesIO()
    img = Image.new('RGB', size, color=color)
    img.save(buf, format=formato)
    buf.seek(0)
    return buf.getvalue()


class IdentidadVisualEmpresaTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.temp_media = tempfile.mkdtemp()
        self.override_media = override_settings(MEDIA_ROOT=self.temp_media)
        self.override_media.enable()

        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20600000001',
            razon_social='EMPRESA IDENTIDAD TEST S.A.C.',
            moneda_base_codigo=self.moneda,
        )
        ConfigEmpresa.objects.create(
            empresa=self.empresa,
            tolerancia_residuo_pen='0.05000000',
            decimales_calculo=6,
            regla_redondeo='ROUND_HALF_UP',
            metodo_valuacion='CPP',
        )
        self.admin = Usuario.objects.create(
            username='admin_identidad',
            email='admin@identidad.pe',
            password_hash='hash',
        )
        UsuarioEmpresa.objects.create(
            usuario=self.admin,
            empresa=self.empresa,
            rol='ADMIN',
        )
        self.operador = Usuario.objects.create(
            username='operador_identidad',
            email='operador@identidad.pe',
            password_hash='hash',
        )
        UsuarioEmpresa.objects.create(
            usuario=self.operador,
            empresa=self.empresa,
            rol='USUARIO',
        )

    def tearDown(self):
        self.override_media.disable()
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def _headers(self, usuario):
        from apps.usuarios.authentication import generar_token
        token = generar_token(usuario)
        return {
            'HTTP_AUTHORIZATION': f'Bearer {token}',
            'HTTP_X_EMPRESA_ID': str(self.empresa.id),
        }

    def test_subida_valida_logo_y_color_tema(self):
        img_bytes = _crear_imagen_bytes('PNG', (128, 128))
        archivo = SimpleUploadedFile('logo.png', img_bytes, content_type='image/png')

        url = reverse('empresa-detail', args=[self.empresa.id])
        resp = self.client.patch(
            url,
            {'logo': archivo, 'color_tema': '#4f46e5'},
            format='multipart',
            **self._headers(self.admin),
        )
        self.assertEqual(resp.status_code, 200)
        self.empresa.refresh_from_db()
        self.assertTrue(bool(self.empresa.logo))
        self.assertEqual(self.empresa.color_tema, '#4F46E5')
        self.assertIn('/media/empresas/', resp.data['logo'])

    def test_rechazo_archivo_falso_corrupto(self):
        falso_png = SimpleUploadedFile('malicioso.png', b'MZ\x90\x00 ejecutable disfrazado', content_type='image/png')
        url = reverse('empresa-detail', args=[self.empresa.id])
        resp = self.client.patch(
            url,
            {'logo': falso_png},
            format='multipart',
            **self._headers(self.admin),
        )
        self.assertEqual(resp.status_code, 400)
        self.empresa.refresh_from_db()
        self.assertFalse(bool(self.empresa.logo))

    def test_rechazo_color_tema_invalido(self):
        url = reverse('empresa-detail', args=[self.empresa.id])
        for color_invalido in ['#ZZZZZZ', 'blue', '#12345', '123456', '#1234567']:
            resp = self.client.patch(
                url,
                {'color_tema': color_invalido},
                format='json',
                **self._headers(self.admin),
            )
            self.assertEqual(resp.status_code, 400, f'Color {color_invalido} debió ser rechazado')

    def test_rechazo_formato_no_permitido_gif(self):
        gif_bytes = _crear_imagen_bytes('GIF', (32, 32))
        archivo = SimpleUploadedFile('animacion.gif', gif_bytes, content_type='image/gif')
        url = reverse('empresa-detail', args=[self.empresa.id])
        resp = self.client.patch(
            url,
            {'logo': archivo},
            format='multipart',
            **self._headers(self.admin),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Solo se admiten WEBP, PNG y JPEG', str(resp.data))

    def test_reemplazo_logo_elimina_anterior_tras_commit(self):
        from django.core.files.storage import default_storage

        # 1. Subir primer logo
        img1 = SimpleUploadedFile('logo1.png', _crear_imagen_bytes('PNG'), content_type='image/png')
        url = reverse('empresa-detail', args=[self.empresa.id])
        resp1 = self.client.patch(url, {'logo': img1}, format='multipart', **self._headers(self.admin))
        self.assertEqual(resp1.status_code, 200)
        self.empresa.refresh_from_db()
        ruta1 = self.empresa.logo.name
        self.assertTrue(default_storage.exists(ruta1))

        # 2. Subir segundo logo (reemplazo)
        img2 = SimpleUploadedFile('logo2.webp', _crear_imagen_bytes('WEBP'), content_type='image/webp')
        with self.captureOnCommitCallbacks(execute=True):
            resp2 = self.client.patch(url, {'logo': img2}, format='multipart', **self._headers(self.admin))
        self.assertEqual(resp2.status_code, 200)
        self.empresa.refresh_from_db()
        ruta2 = self.empresa.logo.name
        self.assertNotEqual(ruta1, ruta2)
        # El archivo 1 debe haberse eliminado y el 2 debe existir
        self.assertFalse(default_storage.exists(ruta1))
        self.assertTrue(default_storage.exists(ruta2))

    def test_quitar_logo_elimina_archivo_tras_commit(self):
        from django.core.files.storage import default_storage

        img = SimpleUploadedFile('logo.png', _crear_imagen_bytes('PNG'), content_type='image/png')
        url = reverse('empresa-detail', args=[self.empresa.id])
        resp = self.client.patch(url, {'logo': img}, format='multipart', **self._headers(self.admin))
        self.assertEqual(resp.status_code, 200)
        self.empresa.refresh_from_db()
        ruta = self.empresa.logo.name
        self.assertTrue(default_storage.exists(ruta))

        # Quitar logo con quitar_logo=True
        with self.captureOnCommitCallbacks(execute=True):
            resp_del = self.client.patch(url, {'quitar_logo': True}, format='json', **self._headers(self.admin))
        self.assertEqual(resp_del.status_code, 200)
        self.empresa.refresh_from_db()
        self.assertFalse(bool(self.empresa.logo))
        self.assertFalse(default_storage.exists(ruta))

    def test_empresa_sin_logo_ni_color_tema_funciona_limpia(self):
        url = reverse('empresa-detail', args=[self.empresa.id])
        resp = self.client.get(url, **self._headers(self.admin))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data.get('logo'))
        self.assertIsNone(resp.data.get('color_tema'))

    def test_usuario_operador_no_puede_modificar_identidad(self):
        url = reverse('empresa-detail', args=[self.empresa.id])
        resp = self.client.patch(
            url,
            {'color_tema': '#10B981'},
            format='json',
            **self._headers(self.operador),
        )
        self.assertEqual(resp.status_code, 403)
