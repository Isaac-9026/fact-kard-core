from django.db import IntegrityError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario, UsuarioEmpresa
from apps.usuarios.authentication import generar_token
from apps.auditoria.models import Auditoria


class UsuariosModelTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20100070970',
            razon_social='EMPRESA MODELO S.A.C.',
            moneda_base_codigo=self.moneda
        )
        self.usuario = Usuario.objects.create(
            username='admin_test',
            email='admin@factkard.pe',
            password_hash='pbkdf2_sha256$test_hash'
        )

    def test_crear_usuario_y_asignacion(self):
        ue = UsuarioEmpresa.objects.create(
            usuario=self.usuario,
            empresa=self.empresa,
            rol='ADMIN'
        )
        self.assertEqual(ue.rol, 'ADMIN')
        self.assertTrue(ue.activo)

    def test_rol_invalido_check_constraint(self):
        with self.assertRaises(IntegrityError):
            UsuarioEmpresa.objects.create(
                usuario=self.usuario,
                empresa=self.empresa,
                rol='SUPER_INV'
            )

    def test_usuario_empresa_unique_constraint(self):
        UsuarioEmpresa.objects.create(
            usuario=self.usuario,
            empresa=self.empresa,
            rol='ADMIN'
        )
        with self.assertRaises(IntegrityError):
            UsuarioEmpresa.objects.create(
                usuario=self.usuario,
                empresa=self.empresa,
                rol='USUARIO'
            )


class UsuariosAuthAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')

        self.empresa_a = Empresa.objects.create(
            ruc='20100070970',
            razon_social='EMPRESA A S.A.C.',
            moneda_base_codigo=self.moneda,
            estado='ACTIVA'
        )
        self.empresa_b = Empresa.objects.create(
            ruc='20601234567',
            razon_social='EMPRESA B S.A.C.',
            moneda_base_codigo=self.moneda,
            estado='ACTIVA'
        )

        # Usuario Normal (rol USUARIO en Empresa A)
        self.user_a = Usuario.objects.create(
            username='operador_a',
            email='operador@empresa-a.pe',
            activo=True
        )
        self.user_a.set_password('password123')
        self.user_a.save()

        self.asig_user_a = UsuarioEmpresa.objects.create(
            usuario=self.user_a,
            empresa=self.empresa_a,
            rol='USUARIO',
            activo=True
        )

        # Usuario Admin en Empresa A
        self.admin_a = Usuario.objects.create(
            username='admin_a',
            email='admin@empresa-a.pe',
            activo=True
        )
        self.admin_a.set_password('adminpass123')
        self.admin_a.save()

        self.asig_admin_a = UsuarioEmpresa.objects.create(
            usuario=self.admin_a,
            empresa=self.empresa_a,
            rol='ADMIN',
            activo=True
        )

        # Superadministrador Global
        self.superadmin = Usuario.objects.create(
            username='super_root',
            email='root@factkard.pe',
            es_admin_global=True,
            activo=True
        )
        self.superadmin.set_password('supersecret')
        self.superadmin.save()

    def test_login_exitoso_y_obtencion_token_y_empresas(self):
        res = self.client.post('/api/usuarios/login/', {
            'username': 'operador_a',
            'password': 'password123',
        }, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('token', res.data)
        self.assertIn('usuario', res.data)
        self.assertEqual(res.data['usuario']['username'], 'operador_a')
        self.assertIn('empresas', res.data)
        self.assertEqual(len(res.data['empresas']), 1)
        self.assertEqual(res.data['empresas'][0]['id'], self.empresa_a.id)
        self.assertEqual(res.data['empresas'][0]['rol'], 'USUARIO')

    def test_login_credenciales_invalidas(self):
        res = self.client.post('/api/usuarios/login/', {
            'username': 'operador_a',
            'password': 'password_incorrecto',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_usuario_inactivo(self):
        self.user_a.activo = False
        self.user_a.save()

        res = self.client.post('/api/usuarios/login/', {
            'username': 'operador_a',
            'password': 'password123',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_me_autenticado(self):
        token = generar_token(self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        res = self.client.get('/api/usuarios/me/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['usuario']['username'], 'operador_a')
        self.assertEqual(len(res.data['empresas']), 1)

    def test_usuario_empresa_a_recibe_403_al_enviar_header_empresa_b(self):
        """
        Demuestra la Regla Multiempresa Estricta:
        Un usuario asignado a Empresa A recibe 403 Forbidden al enviar X-Empresa-Id de Empresa B.
        """
        token = generar_token(self.user_a)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {token}',
            HTTP_X_EMPRESA_ID=str(self.empresa_b.id)
        )

        res = self.client.get('/api/usuarios/asignaciones/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('asignación activa', str(res.data))

    def test_usuario_rol_usuario_recibe_403_al_intentar_accion_admin(self):
        """
        Demuestra la Regla de Permisos por Rol:
        Un usuario con rol USUARIO recibe 403 Forbidden al intentar realizar una acción de ADMIN.
        """
        token = generar_token(self.user_a)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {token}',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id)
        )

        res = self.client.get('/api/usuarios/asignaciones/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Administrador', str(res.data))

    def test_admin_empresa_a_puede_listar_y_asignar_usuarios(self):
        token = generar_token(self.admin_a)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {token}',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id)
        )

        # 1. Listar asignaciones de Empresa A
        res_list = self.client.get('/api/usuarios/asignaciones/')
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_list.data), 2)  # user_a y admin_a

        # 2. Crear nuevo usuario para asignarle rol
        nuevo_user = Usuario.objects.create(
            username='contador_nuevo',
            email='contador@empresa-a.pe',
            activo=True
        )
        nuevo_user.set_password('cnt123')
        nuevo_user.save()

        res_post = self.client.post('/api/usuarios/asignaciones/', {
            'usuario_id': nuevo_user.id,
            'rol': 'USUARIO',
            'activo': True,
        }, format='json')

        self.assertEqual(res_post.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_post.data['username'], 'contador_nuevo')
        self.assertEqual(res_post.data['rol'], 'USUARIO')

        # 3. Comprobar que se registró en auditoría
        aud = Auditoria.objects.filter(
            empresa_id=self.empresa_a.id,
            entidad='USUARIO_EMPRESA',
            accion='ASIGNAR_USUARIO'
        ).first()
        self.assertIsNotNone(aud)
        self.assertEqual(aud.usuario_id, self.admin_a.id)
