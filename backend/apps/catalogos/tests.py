from datetime import date
from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.catalogos.models import (
    Moneda,
    TipoCambio,
    TipoComprobante,
    TipoOperacion,
    TipoExistencia,
    UnidadMedida,
)


class CatalogosModelTest(TestCase):
    def setUp(self):
        self.moneda_usd = Moneda.objects.create(codigo='USD', nombre='Dólares Americanos')

    def test_crear_moneda(self):
        moneda = Moneda.objects.create(codigo='EUR', nombre='Euros')
        self.assertEqual(moneda.codigo, 'EUR')
        self.assertEqual(str(moneda), 'EUR - Euros')

    def test_tipo_cambio_unique_constraint(self):
        fecha = date(2026, 10, 19)
        tc = TipoCambio.objects.create(
            moneda_codigo=self.moneda_usd,
            fecha_publicacion=fecha,
            venta=Decimal('3.75000000'),
            compra=Decimal('3.74000000'),
            fuente='SUNAT'
        )
        self.assertEqual(tc.venta, Decimal('3.75000000'))

        # Duplicado en la misma moneda, fecha y fuente debe fallar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                TipoCambio.objects.create(
                    moneda_codigo=self.moneda_usd,
                    fecha_publicacion=fecha,
                    venta=Decimal('3.80000000'),
                    compra=Decimal('3.79000000'),
                    fuente='SUNAT'
                )

    def test_tipo_comprobante_check_constraint(self):
        tc = TipoComprobante.objects.create(
            codigo_sunat='01',
            descripcion='FACTURA',
            es_nota=False,
            efecto_nota='NINGUNO'
        )
        self.assertEqual(tc.codigo_sunat, '01')

        # Efecto de nota inválido debe fallar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                TipoComprobante.objects.create(
                    codigo_sunat='07',
                    descripcion='NOTA DE CREDITO',
                    es_nota=True,
                    efecto_nota='INVALIDO'
                )

    def test_tipo_operacion_check_constraint(self):
        top = TipoOperacion.objects.create(
            codigo_interno='COMPRA_LOCAL',
            codigo_sunat='02',
            descripcion='COMPRA NACIONAL',
            naturaleza='ENTRADA',
            origen_requerido='DOCUMENTO'
        )
        self.assertEqual(top.naturaleza, 'ENTRADA')

        # Naturaleza inválida debe fallar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                TipoOperacion.objects.create(
                    codigo_interno='OPERACION_INVALIDA',
                    descripcion='INVALIDA',
                    naturaleza='OTRA',
                    origen_requerido='DOCUMENTO'
                )

        # Origen requerido inválido debe fallar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                TipoOperacion.objects.create(
                    codigo_interno='OPERACION_INVALIDA_2',
                    descripcion='INVALIDA 2',
                    naturaleza='SALIDA',
                    origen_requerido='ORIGEN_NO_EXISTENTE'
                )

    def test_tipo_existencia_y_unidad_medida(self):
        te = TipoExistencia.objects.create(codigo='01', descripcion='MERCADERIAS')
        self.assertEqual(str(te), '01 - MERCADERIAS')

        um = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDADES')
        self.assertEqual(str(um), 'NIU - UNIDADES')


class TipoCambioResolverApiTest(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        from apps.usuarios.models import Usuario
        self.client = APIClient()
        self.admin_user = Usuario.objects.create(
            username='admin_tc',
            email='admin_tc@factkard.pe',
            password_hash='hash',
            es_admin_global=True,
            activo=True,
        )
        self.normal_user = Usuario.objects.create(
            username='operador_tc',
            email='operador_tc@factkard.pe',
            password_hash='hash',
            es_admin_global=False,
            activo=True,
        )
        self.client.force_authenticate(user=self.admin_user)

        self.moneda_usd = Moneda.objects.create(codigo='USD', nombre='Dólares Americanos')
        self.moneda_pen = Moneda.objects.create(codigo='PEN', nombre='Soles')

        # Publicación del viernes 16 de Octubre
        self.tc_viernes = TipoCambio.objects.create(
            moneda_codigo=self.moneda_usd,
            fecha_publicacion=date(2026, 10, 16),
            compra=Decimal('3.74200000'),
            venta=Decimal('3.75100000'),
            fuente='SBS'
        )

    def test_c01_acceso_anonimo_retorna_401(self):
        anon_client = APIClient()
        resp_get = anon_client.get('/api/catalogos/tipos-cambio/')
        self.assertEqual(resp_get.status_code, 401)
        resp_resolver = anon_client.get('/api/catalogos/tipo-cambio/resolver/', {'moneda': 'USD', 'fecha': '2026-10-16'})
        self.assertEqual(resp_resolver.status_code, 401)
        resp_post = anon_client.post('/api/catalogos/tipos-cambio/', {}, format='json')
        self.assertEqual(resp_post.status_code, 401)

    def test_c01_usuario_sin_rol_admin_no_puede_crear_tipo_cambio(self):
        self.client.force_authenticate(user=self.normal_user)
        payload = {
            'moneda_codigo': 'USD',
            'fecha_publicacion': '2026-10-20',
            'compra': '3.75000000',
            'venta': '3.76000000',
            'fuente': 'SBS',
        }
        resp = self.client.post('/api/catalogos/tipos-cambio/', payload, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_resolucion_fecha_exacta(self):
        response = self.client.get(
            '/api/catalogos/tipo-cambio/resolver/',
            {'moneda': 'USD', 'fecha': '2026-10-16'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['moneda_codigo'], 'USD')
        self.assertEqual(response.data['fecha_publicacion'], '2026-10-16')
        self.assertEqual(response.data['fecha_consultada'], '2026-10-16')
        self.assertTrue(response.data['es_fecha_exacta'])
        self.assertEqual(Decimal(response.data['compra']), Decimal('3.74200000'))
        self.assertEqual(Decimal(response.data['venta']), Decimal('3.75100000'))

    def test_resolucion_fin_de_semana_o_feriado_toma_ultimo_tc_anterior(self):
        # Sábado 17 de Octubre (no hay publicación oficial, toma el del viernes 16)
        response_sabado = self.client.get(
            '/api/catalogos/tipo-cambio/resolver/',
            {'moneda': 'USD', 'fecha': '2026-10-17'}
        )
        self.assertEqual(response_sabado.status_code, 200)
        self.assertEqual(response_sabado.data['fecha_publicacion'], '2026-10-16')
        self.assertEqual(response_sabado.data['fecha_consultada'], '2026-10-17')
        self.assertFalse(response_sabado.data['es_fecha_exacta'])
        self.assertEqual(Decimal(response_sabado.data['compra']), Decimal('3.74200000'))
        self.assertEqual(Decimal(response_sabado.data['venta']), Decimal('3.75100000'))

        # Domingo 18 de Octubre (sigue tomando el del viernes 16)
        response_domingo = self.client.get(
            '/api/catalogos/tipo-cambio/resolver/',
            {'moneda': 'USD', 'fecha': '2026-10-18'}
        )
        self.assertEqual(response_domingo.status_code, 200)
        self.assertEqual(response_domingo.data['fecha_publicacion'], '2026-10-16')
        self.assertEqual(response_domingo.data['fecha_consultada'], '2026-10-18')
        self.assertFalse(response_domingo.data['es_fecha_exacta'])

    def test_resolucion_fecha_anterior_a_todo_registro_retorna_404(self):
        response = self.client.get(
            '/api/catalogos/tipo-cambio/resolver/',
            {'moneda': 'USD', 'fecha': '2026-10-15'}
        )
        self.assertEqual(response.status_code, 404)

    def test_resolucion_parametros_invalidos(self):
        # Falta fecha
        res_no_fecha = self.client.get('/api/catalogos/tipo-cambio/resolver/', {'moneda': 'USD'})
        self.assertEqual(res_no_fecha.status_code, 400)

        # Formato de fecha inválido
        res_bad_fecha = self.client.get('/api/catalogos/tipo-cambio/resolver/', {'moneda': 'USD', 'fecha': '17-10-2026'})
        self.assertEqual(res_bad_fecha.status_code, 400)

    def test_post_tipo_cambio_crea_con_decimal(self):
        payload = {
            'moneda_codigo': 'USD',
            'fecha_publicacion': '2026-10-19',
            'compra': '3.74800000',
            'venta': '3.75600000',
            'fuente': 'SBS',
        }
        response = self.client.post('/api/catalogos/tipos-cambio/', payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decimal(response.data['compra']), Decimal('3.74800000'))
        self.assertEqual(Decimal(response.data['venta']), Decimal('3.75600000'))
