from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda, TipoExistencia
from apps.empresas.models import CierrePeriodo, CierrePeriodoDetalle, Empresa, Establecimiento, Periodo
from apps.inventario.models import Producto
from apps.usuarios.models import Usuario, UsuarioEmpresa


class PilotoComparadorTest(TestCase):
    def setUp(self):
        moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(ruc='20333333333', razon_social='PILOTO', moneda_base_codigo=moneda)
        self.otra = Empresa.objects.create(ruc='20444444444', razon_social='OTRA', moneda_base_codigo=moneda)
        self.est = Establecimiento.objects.create(empresa=self.empresa, codigo_sunat='0000', nombre='PRINCIPAL')
        tipo = TipoExistencia.objects.create(codigo='01', descripcion='MERCADERÍA')
        self.producto = Producto.objects.create(empresa=self.empresa, codigo_interno='P1', descripcion='UNO', tipo_existencia_codigo=tipo)
        self.ajeno = Producto.objects.create(empresa=self.otra, codigo_interno='PX', descripcion='AJENO', tipo_existencia_codigo=tipo)
        self.periodo = Periodo.objects.create(empresa=self.empresa, anio=2026, mes=10, orden=202610, fecha_inicio='2026-10-01', fecha_fin='2026-10-31', estado='CERRADO')
        self.periodo_ajeno = Periodo.objects.create(empresa=self.otra, anio=2026, mes=10, orden=202610, fecha_inicio='2026-10-01', fecha_fin='2026-10-31')
        self.user = Usuario.objects.create(username='piloto', email='p@test.local', activo=True)
        UsuarioEmpresa.objects.create(usuario=self.user, empresa=self.empresa, rol='USUARIO', activo=True)
        cierre = CierrePeriodo.objects.create(periodo=self.periodo, version_calculo=1, cerrado_por=self.user, vigente=True)
        CierrePeriodoDetalle.objects.create(cierre_periodo=cierre, producto=self.producto, establecimiento=self.est, saldo_cantidad=Decimal('125'), cpp_pen=Decimal('10.6875'), saldo_valor_pen=Decimal('1335.9375'))
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def payload(self, **cambios):
        data = {'periodo_id': self.periodo.id, 'producto_id': self.producto.id, 'cantidad_esperada': '125', 'cpp_esperado': '10.6875', 'valor_esperado': '1335.9375', 'tiempo_manual_segundos': '100', 'tiempo_factkard_segundos': '20'}
        data.update(cambios); return data

    def post(self, **cambios): return self.client.post(reverse('piloto-comparador'), self.payload(**cambios), format='json', HTTP_X_EMPRESA_ID=str(self.empresa.id))
    def test_01_comparacion_sin_diferencias(self): self.assertEqual(self.post().status_code, 200)
    def test_02_cuadra_100(self): self.assertTrue(self.post().data['cuadra_100'])
    def test_03_diferencia_cantidad_cero(self): self.assertEqual(self.post().data['diferencias']['cantidad'], '0.00000000')
    def test_04_diferencia_cpp_cero(self): self.assertEqual(self.post().data['diferencias']['cpp'], '0.00000000')
    def test_05_diferencia_valor_cero(self): self.assertEqual(self.post().data['diferencias']['valor'], '0.00000000')
    def test_06_reduccion_correcta(self): self.assertEqual(self.post().data['reduccion_porcentaje'], '80.000000')
    def test_07_salida_decimal_normalizada(self): self.assertRegex(self.post().data['cantidad_factkard'], r'^\d+\.\d{8}$')
    def test_08_tiempo_manual_cero(self): self.assertEqual(self.post(tiempo_manual_segundos='0').status_code, 400)
    def test_09_tiempo_factkard_negativo(self): self.assertEqual(self.post(tiempo_factkard_segundos='-1').status_code, 400)
    def test_10_producto_ajeno(self): self.assertEqual(self.post(producto_id=self.ajeno.id).status_code, 400)
    def test_11_periodo_ajeno(self): self.assertEqual(self.post(periodo_id=self.periodo_ajeno.id).status_code, 400)
    def test_12_fuente_no_manipulable(self):
        data = self.payload(); data.update({'cantidad_factkard': '999', 'cpp_factkard': '999', 'valor_factkard': '999'})
        response = self.client.post(reverse('piloto-comparador'), data, format='json', HTTP_X_EMPRESA_ID=str(self.empresa.id))
        self.assertEqual(response.data['cantidad_factkard'], '125.00000000')
