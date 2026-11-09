"""
Regresión BE-001: POST /api/catalogos/tipos-cambio/ devolvía HTTP 500 después de
guardar el registro (registrar_auditoria recibía 'tabla' en lugar de 'entidad').
El alta del TipoCambio y su auditoría deben ser atómicas.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.auditoria.models import Auditoria
from apps.catalogos.models import Moneda, TipoCambio
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario, UsuarioEmpresa

URL = '/api/catalogos/tipos-cambio/'


class TipoCambioAltaAtomicaTests(TestCase):
    def setUp(self):
        self.pen = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.usd = Moneda.objects.create(codigo='USD', nombre='Dólares')
        self.empresa = Empresa.objects.create(
            ruc='20111111111', razon_social='EMPRESA TC S.A.C.', moneda_base_codigo=self.pen,
        )
        self.admin = Usuario.objects.create(
            username='admin_empresa_tc', email='admin_tc_be001@test.pe', password_hash='x',
        )
        UsuarioEmpresa.objects.create(usuario=self.admin, empresa=self.empresa, rol='ADMIN')
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_EMPRESA_ID=str(self.empresa.id))
        self.payload = {
            'moneda_codigo': 'USD',
            'fecha_publicacion': '2026-10-01',
            'compra': '3.70000000',
            'venta': '3.71000000',
            'fuente': 'SBS',
        }

    def test_alta_valida_responde_201_persiste_y_audita(self):
        respuesta = self.client.post(URL, self.payload, format='json')

        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.data['fecha_publicacion'], '2026-10-01')

        tc = TipoCambio.objects.get(pk=respuesta.data['id'])
        self.assertEqual(str(tc.fecha_publicacion), '2026-10-01')
        self.assertEqual(tc.compra, Decimal('3.70000000'))
        self.assertEqual(tc.venta, Decimal('3.71000000'))

        auditoria = Auditoria.objects.get(entidad='TIPO_CAMBIO', registro_id=tc.id)
        self.assertEqual(auditoria.accion, 'CREAR')
        self.assertEqual(auditoria.usuario_id, self.admin.id)
        self.assertEqual(auditoria.empresa_id, self.empresa.id)
        self.assertEqual(auditoria.valor_nuevo['fecha_publicacion'], '2026-10-01')
        self.assertEqual(auditoria.valor_nuevo['venta'], '3.71000000')

    def test_fechas_calendario_se_conservan_literalmente(self):
        for fecha in ('2026-10-01', '2026-10-22', '2026-10-31'):
            with self.subTest(fecha=fecha):
                respuesta = self.client.post(
                    URL, {**self.payload, 'fecha_publicacion': fecha}, format='json',
                )
                self.assertEqual(respuesta.status_code, 201, respuesta.data)
                self.assertEqual(respuesta.data['fecha_publicacion'], fecha)
                self.assertEqual(
                    str(TipoCambio.objects.get(pk=respuesta.data['id']).fecha_publicacion), fecha,
                )

    def test_duplicado_responde_400_y_no_crea_segundo_registro(self):
        primera = self.client.post(URL, self.payload, format='json')
        self.assertEqual(primera.status_code, 201)

        segunda = self.client.post(URL, self.payload, format='json')

        self.assertEqual(segunda.status_code, 400)
        self.assertEqual(
            TipoCambio.objects.filter(moneda_codigo='USD', fecha_publicacion='2026-10-01').count(), 1,
        )
        self.assertEqual(Auditoria.objects.filter(entidad='TIPO_CAMBIO').count(), 1)

    def test_fallo_de_auditoria_revierte_el_tipo_de_cambio(self):
        tc_antes = TipoCambio.objects.count()
        auditoria_antes = Auditoria.objects.count()

        with mock.patch(
            'apps.catalogos.views.registrar_auditoria',
            side_effect=RuntimeError('fallo provocado de auditoría'),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(URL, self.payload, format='json')

        self.assertEqual(TipoCambio.objects.count(), tc_antes)
        self.assertFalse(
            TipoCambio.objects.filter(moneda_codigo='USD', fecha_publicacion='2026-10-01').exists()
        )
        self.assertEqual(Auditoria.objects.count(), auditoria_antes)

    def test_sin_header_empresa_tambien_audita_sin_empresa(self):
        self.client.credentials()
        respuesta = self.client.post(URL, self.payload, format='json')

        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        auditoria = Auditoria.objects.get(entidad='TIPO_CAMBIO', registro_id=respuesta.data['id'])
        self.assertIsNone(auditoria.empresa_id)

    def test_header_de_empresa_ajena_no_se_usa_en_la_auditoria(self):
        otra = Empresa.objects.create(
            ruc='20222222222', razon_social='OTRA S.A.C.', moneda_base_codigo=self.pen,
        )
        self.client.credentials(HTTP_X_EMPRESA_ID=str(otra.id))
        respuesta = self.client.post(URL, self.payload, format='json')

        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        auditoria = Auditoria.objects.get(entidad='TIPO_CAMBIO', registro_id=respuesta.data['id'])
        self.assertIsNone(auditoria.empresa_id)
