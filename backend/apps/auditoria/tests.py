from django.db import connection, ProgrammingError, InternalError
from django.test import TransactionTestCase, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario, UsuarioEmpresa
from apps.usuarios.authentication import generar_token
from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar_auditoria


class AuditoriaModelTest(TransactionTestCase):
    def test_auditoria_inmutabilidad_trigger(self):
        # 1. Crear registro (INSERT permitido)
        aud = Auditoria.objects.create(
            accion='CREAR',
            entidad='EMPRESA',
            registro_id=1,
            valor_nuevo={'ruc': '20100070970'},
            motivo='Registro inicial de auditoría'
        )
        self.assertIsNotNone(aud.id)

        # 2. Intentar UPDATE directo en base de datos (debe fallar por trigger)
        with self.assertRaises((ProgrammingError, InternalError)) as cm:
            with connection.cursor() as cur:
                cur.execute(f"UPDATE auditoria SET accion = 'MODIFICAR' WHERE id = {aud.id};")
        self.assertIn('AUDITORIA es de solo insercion', str(cm.exception))

        # 3. Intentar DELETE directo en base de datos (debe fallar por trigger)
        with self.assertRaises((ProgrammingError, InternalError)) as cm:
            with connection.cursor() as cur:
                cur.execute(f"DELETE FROM auditoria WHERE id = {aud.id};")
        self.assertIn('AUDITORIA es de solo insercion', str(cm.exception))


class AuditoriaAPITest(TestCase):
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

        self.admin_a = Usuario.objects.create(
            username='admin_a',
            email='admin@empresa-a.pe',
            activo=True
        )
        self.admin_a.set_password('adminpass123')
        self.admin_a.save()

        UsuarioEmpresa.objects.create(
            usuario=self.admin_a,
            empresa=self.empresa_a,
            rol='ADMIN',
            activo=True
        )

        self.user_a = Usuario.objects.create(
            username='operador_a',
            email='operador@empresa-a.pe',
            activo=True
        )
        self.user_a.set_password('userpass123')
        self.user_a.save()

        UsuarioEmpresa.objects.create(
            usuario=self.user_a,
            empresa=self.empresa_a,
            rol='USUARIO',
            activo=True
        )

        # Registros de auditoría en Empresa A
        self.aud_a1 = registrar_auditoria(
            empresa_id=self.empresa_a.id,
            usuario_id=self.admin_a.id,
            accion='CREAR',
            entidad='DOCUMENTO',
            registro_id=101,
            valor_nuevo={'serie': 'F001', 'numero': 1},
            motivo='Emisión de factura F001-1'
        )
        self.aud_a2 = registrar_auditoria(
            empresa_id=self.empresa_a.id,
            usuario_id=self.admin_a.id,
            accion='MODIFICAR',
            entidad='CLIENTE',
            registro_id=202,
            valor_anterior={'direccion': 'Calle Antigua 123'},
            valor_nuevo={'direccion': 'Av. Principal 456'},
            motivo='Actualización de domicilio fiscal'
        )

        # Registro de auditoría en Empresa B
        self.aud_b1 = registrar_auditoria(
            empresa_id=self.empresa_b.id,
            usuario_id=self.admin_a.id,
            accion='CREAR',
            entidad='DOCUMENTO',
            registro_id=303,
            valor_nuevo={'serie': 'B001', 'numero': 1},
            motivo='Emisión en Empresa B'
        )

    def test_registrar_auditoria_service(self):
        aud = registrar_auditoria(
            empresa_id=self.empresa_a.id,
            usuario_id=self.admin_a.id,
            accion='TEST_ACCION',
            entidad='TEST_ENTIDAD',
            registro_id=999,
            valor_anterior={'foo': 'bar'},
            valor_nuevo={'foo': 'baz'},
            motivo='Prueba de servicio'
        )
        self.assertIsNotNone(aud.id)
        self.assertEqual(aud.accion, 'TEST_ACCION')
        self.assertEqual(aud.entidad, 'TEST_ENTIDAD')
        self.assertEqual(aud.valor_nuevo, {'foo': 'baz'})

    def test_auditoria_solo_devuelve_registros_empresa_activa(self):
        """
        Demuestra la Regla Multiempresa en Auditoría:
        El endpoint de auditoría solo devuelve registros de la empresa activa (empresa_a),
        nunca registros de empresa_b.
        """
        token = generar_token(self.admin_a)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {token}',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id)
        )

        res = self.client.get('/api/auditoria/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)

        # Verificar que todos los registros pertenezcan a empresa_a
        for item in res.data:
            self.assertEqual(item['empresa_id'], self.empresa_a.id)
            self.assertNotEqual(item['registro_id'], 303)  # El de empresa_b

    def test_auditoria_filtros_entidad_y_accion(self):
        token = generar_token(self.admin_a)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {token}',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id)
        )

        # Filtro por entidad
        res_entidad = self.client.get('/api/auditoria/', {'entidad': 'DOCUMENTO'})
        self.assertEqual(res_entidad.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_entidad.data), 1)
        self.assertEqual(res_entidad.data[0]['entidad'], 'DOCUMENTO')

        # Filtro por acción
        res_accion = self.client.get('/api/auditoria/', {'accion': 'MODIFICAR'})
        self.assertEqual(res_accion.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_accion.data), 1)
        self.assertEqual(res_accion.data[0]['accion'], 'MODIFICAR')
        self.assertEqual(res_accion.data[0]['entidad'], 'CLIENTE')

    def test_usuario_rol_usuario_recibe_403_en_auditoria(self):
        """
        Un usuario con rol USUARIO no puede ver auditoría (requiere ADMIN).
        """
        token = generar_token(self.user_a)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {token}',
            HTTP_X_EMPRESA_ID=str(self.empresa_a.id)
        )

        res = self.client.get('/api/auditoria/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_empresa_a_recibe_403_al_consultar_empresa_b(self):
        """
        Admin A no tiene asignación en Empresa B -> 403 Forbidden.
        """
        token = generar_token(self.admin_a)
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {token}',
            HTTP_X_EMPRESA_ID=str(self.empresa_b.id)
        )

        res = self.client.get('/api/auditoria/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
