"""
Bloque 4 — Formato 13.1 por establecimiento en períodos abiertos: el saldo final era
cantidad × CPP por establecimiento y la suma no coincidía con el saldo real de la
empresa. Ahora se reparte el saldo real con la misma regla que el cierre (diferencia de
redondeo al establecimiento principal), sin crear ni perder importes.
"""
from decimal import Decimal

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.empresas.models import CierrePeriodoDetalle, Establecimiento
from apps.empresas.services import cerrar_periodo
from apps.inventario.models import Almacen
from apps.reportes.formato131_service import generar_formato_131
from apps.reportes.services import consultar_kardex_valorizado

D = Decimal


class MicrodiferenciasEstablecimientoTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.estab_2 = Establecimiento.objects.create(empresa=self.empresa, codigo_sunat='0001', nombre='SUCURSAL')
        self.almacen_b = Almacen.objects.create(empresa=self.empresa, establecimiento=self.estab_2,
                                                codigo='ALMB', nombre='SUCURSAL')
        # CPP con decimales: 1 × 1.00 (principal) + 2 × 0.50 (sucursal) → 2.00 / 3 u. = 0.666667
        self.compra_confirmada('1', '1', fecha='2026-01-08')
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '2', '0.5', almacen=self.almacen_b.id)],
                                  fecha='2026-01-09')

    def reportes(self):
        data = generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)
        return {r['cabecera']['establecimiento']['id']: r for r in data['reportes']}

    def valor_empresa(self):
        return consultar_kardex_valorizado(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                           periodo_id=self.enero.id)['resumen']['saldo_final_valor']

    def test_dos_establecimientos_suman_el_saldo_real_en_periodo_abierto(self):
        reportes = self.reportes()
        principal, sucursal = reportes[self.establecimiento.id], reportes[self.estab_2.id]
        self.assertEqual(self.valor_empresa(), D('2.00000000'))
        self.assertEqual(D(principal['saldo_final']['costo_total']) + D(sucursal['saldo_final']['costo_total']),
                         D('2.00000000'))  # antes 0.666667 + 1.333334 = 2.000001
        # El redondeo va al principal y se informa como ajuste, no como error contable.
        self.assertEqual(principal['saldo_final']['costo_total'], '0.66666600')
        self.assertEqual(principal['microdiferencia_cierre'], '-0.00000100')
        self.assertEqual(principal['fuente_saldo_final'], 'CALCULADO')
        self.assertEqual(sucursal['saldo_final']['costo_total'], '1.33333400')
        self.assertEqual(sucursal['microdiferencia_cierre'], '0.00000000')
        # Mismo CPP en ambos: no se inventan costos por almacén.
        self.assertEqual(principal['saldo_final']['costo_unitario'], sucursal['saldo_final']['costo_unitario'])

    def test_periodo_cerrado_concilia_con_el_cierre(self):
        abierto = {e: r['saldo_final'] for e, r in self.reportes().items()}
        cierre, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.enero.id, usuario=self.usuario)
        reportes = self.reportes()
        total = D('0')
        for estab_id, reporte in reportes.items():
            detalle = CierrePeriodoDetalle.objects.get(cierre_periodo=cierre, producto=self.producto,
                                                       establecimiento_id=estab_id)
            self.assertEqual(D(reporte['saldo_final']['costo_total']), detalle.saldo_valor_pen)
            self.assertEqual(reporte['fuente_saldo_final'], 'CIERRE')
            self.assertEqual(reporte['saldo_final'], abierto[estab_id])  # abierto y cerrado coinciden
            total += detalle.saldo_valor_pen
        self.assertEqual(total, self.valor_empresa())

    def test_saldo_inicial_del_periodo_siguiente_tambien_suma_el_saldo_real(self):
        from datetime import date
        from apps.empresas.models import Periodo
        febrero = Periodo.objects.create(empresa=self.empresa, anio=2026, mes=2, orden=202602,
                                         fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 2, 28), estado='ABIERTO')
        data = generar_formato_131(empresa_id=self.empresa.id, periodo_id=febrero.id)
        iniciales = [D(r['saldo_inicial_valorizado']['costo_total']) for r in data['reportes']]
        self.assertEqual(sum(iniciales), D('2.00000000'))
