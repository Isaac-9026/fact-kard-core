from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario, UsuarioEmpresa
from apps.usuarios.authentication import generar_token


class GestionUsuariosAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')

        self.empresa_1 = Empresa.objects.create(
            ruc='20100070970',
            razon_social='EMPRESA UNO S.A.C.',
            moneda_base_codigo=self.moneda,
            estado='ACTIVA'
        )
        self.empresa_2 = Empresa.objects.create(
            ruc='20601234567',
            razon_social='EMPRESA DOS S.A.C.',
            moneda_base_codigo=self.moneda,
            estado='ACTIVA'
        )

        # 1. Administrador Global del Estudio (es_admin_global=True)
        self.admin = Usuario.objects.create(
            username='admin_global',
            email='admin@estudio.pe',
            es_admin_global=True,
            activo=True
        )
        self.admin.set_password('AdminClave123')
        self.admin.save()
        UsuarioEmpresa.objects.create(
            usuario=self.admin,
            empresa=self.empresa_1,
            rol='ADMIN',
            activo=True
        )

        # 2. Administrador Local de Empresa Cliente (ADMIN en Empresa 1, pero NO es admin global)
        self.admin_local = Usuario.objects.create(
            username='admin_cliente_local',
            email='admin_local@cliente.pe',
            es_admin_global=False,
            activo=True
        )
        self.admin_local.set_password('LocalAdmin123')
        self.admin_local.save()
        UsuarioEmpresa.objects.create(
            usuario=self.admin_local,
            empresa=self.empresa_1,
            rol='ADMIN',
            activo=True
        )

        # 3. Usuario Operador Asistente (rol USUARIO en Empresa 1, NO es admin global)
        self.operador = Usuario.objects.create(
            username='operador_asistente',
            email='operador@estudio.pe',
            es_admin_global=False,
            activo=True
        )
        self.operador.set_password('OperadorClave123')
        self.operador.save()
        UsuarioEmpresa.objects.create(
            usuario=self.operador,
            empresa=self.empresa_1,
            rol='USUARIO',
            activo=True
        )

    def test_admin_global_estudio_listar_usuarios(self):
        token = generar_token(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        res = self.client.get('/api/usuarios/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res.data, list)
        self.assertGreaterEqual(len(res.data), 3)
        admin_data = next((u for u in res.data if u['username'] == 'admin_global'), None)
        self.assertIsNotNone(admin_data)
        self.assertIn('asignaciones', admin_data)
        self.assertEqual(len(admin_data['asignaciones']), 1)
        self.assertEqual(admin_data['asignaciones'][0]['empresa_ruc'], '20100070970')

    def test_admin_local_empresa_recibe_403_al_intentar_acceso_global(self):
        """
        Micro-ajuste multi-tenant: Un administrador local de empresa cliente (rol='ADMIN')
        NO tiene privilegios globales y recibe 403 Forbidden al intentar listar usuarios del estudio,
        evitando escalación de privilegios entre empresas de la cartera.
        """
        token = generar_token(self.admin_local)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        res = self.client.get('/api/usuarios/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Administrador Global del Estudio', str(res.data))

    def test_usuario_operador_recibe_403_al_listar_usuarios(self):
        token = generar_token(self.operador)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        res = self.client.get('/api/usuarios/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_crear_usuario_con_asignaciones_multiempresa(self):
        token = generar_token(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        payload = {
            'username': 'nuevo_contador',
            'email': 'contador@estudio.pe',
            'password_inicial': 'Contador2026!',
            'asignaciones': [
                {'empresa_id': self.empresa_1.id, 'rol': 'ADMIN', 'activo': True},
                {'empresa_id': self.empresa_2.id, 'rol': 'USUARIO', 'activo': True},
            ]
        }
        res = self.client.post('/api/usuarios/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['username'], 'nuevo_contador')
        self.assertEqual(len(res.data['asignaciones']), 2)

        # Verificar en base de datos
        nuevo = Usuario.objects.get(username='nuevo_contador')
        self.assertTrue(nuevo.check_password('Contador2026!'))
        self.assertTrue(nuevo.activo)
        self.assertEqual(UsuarioEmpresa.objects.filter(usuario=nuevo).count(), 2)

    def test_crear_usuario_duplicado_rechazado(self):
        token = generar_token(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        payload = {
            'username': 'admin_global',
            'email': 'otro_email@estudio.pe',
            'password_inicial': 'Password123',
        }
        res = self.client.post('/api/usuarios/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('username', res.data)

    def test_crear_usuario_password_menor_a_8_caracteres_rechazado(self):
        token = generar_token(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        payload = {
            'username': 'usuario_clave_corta',
            'email': 'corta@estudio.pe',
            'password_inicial': '12345',
        }
        res = self.client.post('/api/usuarios/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_actualizar_usuario_y_asignaciones(self):
        token = generar_token(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        payload = {
            'email': 'operador_modificado@estudio.pe',
            'asignaciones': [
                {'empresa_id': self.empresa_1.id, 'rol': 'ADMIN', 'activo': True},
                {'empresa_id': self.empresa_2.id, 'rol': 'USUARIO', 'activo': True},
            ]
        }
        res = self.client.patch(f'/api/usuarios/{self.operador.id}/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.operador.refresh_from_db()
        self.assertEqual(self.operador.email, 'operador_modificado@estudio.pe')
        self.assertEqual(UsuarioEmpresa.objects.filter(usuario=self.operador).count(), 2)
        ue1 = UsuarioEmpresa.objects.get(usuario=self.operador, empresa=self.empresa_1)
        self.assertEqual(ue1.rol, 'ADMIN')

    def test_usuario_no_puede_desactivar_su_propia_cuenta(self):
        token = generar_token(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        payload = {'activo': False}
        res = self.client.patch(f'/api/usuarios/{self.admin.id}/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('No puedes desactivar tu propia cuenta en sesión', res.data['detail'])

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.activo)

    def test_admin_puede_desactivar_otro_usuario(self):
        token = generar_token(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        payload = {'activo': False}
        res = self.client.patch(f'/api/usuarios/{self.operador.id}/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.operador.refresh_from_db()
        self.assertFalse(self.operador.activo)

    def test_resetear_password_admin(self):
        token = generar_token(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        res = self.client.post(f'/api/usuarios/{self.operador.id}/reset-password/', {
            'password_nuevo': 'NuevaClaveTemporal2026!'
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.operador.refresh_from_db()
        self.assertTrue(self.operador.check_password('NuevaClaveTemporal2026!'))

    def test_operador_recibe_403_al_resetear_password_de_otro(self):
        token = generar_token(self.operador)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        res = self.client.post(f'/api/usuarios/{self.admin.id}/reset-password/', {
            'password_nuevo': 'IntentoHack2026!'
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cambiar_password_propio_exitoso(self):
        token = generar_token(self.operador)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        res = self.client.post('/api/auth/cambiar-password/', {
            'password_actual': 'OperadorClave123',
            'password_nuevo': 'MiNuevaClaveSegura2026!'
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.operador.refresh_from_db()
        self.assertFalse(self.operador.check_password('OperadorClave123'))
        self.assertTrue(self.operador.check_password('MiNuevaClaveSegura2026!'))

    def test_cambiar_password_propio_password_actual_incorrecto(self):
        token = generar_token(self.operador)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        res = self.client.post('/api/auth/cambiar-password/', {
            'password_actual': 'ClaveTotalmenteErronea',
            'password_nuevo': 'MiNuevaClaveSegura2026!'
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('La contraseña actual es incorrecta', res.data['detail'])

    def test_cambiar_password_propio_mismo_password_rechazado(self):
        token = generar_token(self.operador)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        res = self.client.post('/api/auth/cambiar-password/', {
            'password_actual': 'OperadorClave123',
            'password_nuevo': 'OperadorClave123'
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
