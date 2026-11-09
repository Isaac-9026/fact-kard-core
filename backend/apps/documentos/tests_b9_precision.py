"""
Bloque 9 — precisión: lo que guarda la API para cada caso de oro es exactamente lo que el
frontend calcula y muestra antes de guardar.

Casos: qa/precision/casos_documentos.json (Decimal + ROUND_HALF_UP, generados por
qa/precision/generar_casos.py). El frontend verifica los mismos casos en
frontend/src/utils/precisionDocumentos.test.ts.
"""
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from apps.catalogos.models import UnidadMedida
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import TasaIgvVigencia
from apps.inventario.models import ProductoUnidad

CASOS = json.loads((Path(settings.BASE_DIR).parent / 'qa' / 'precision' / 'casos_documentos.json').read_text('utf-8'))
Q8 = Decimal('0.00000001')


def texto(valor):
    return f'{Decimal(valor).quantize(Q8, rounding=ROUND_HALF_UP):f}'


class PrecisionDocumentosTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.unidades = {'1': self.pu}

    def unidad_con_factor(self, factor):
        if factor not in self.unidades:
            codigo = f'U{len(self.unidades)}'
            und = UnidadMedida.objects.create(codigo=codigo, descripcion=f'UNIDAD {factor}')
            self.unidades[factor] = ProductoUnidad.objects.create(
                producto=self.producto, unidad_codigo=und, factor_a_base=Decimal(factor), es_base=False,
            )
        return self.unidades[factor]

    def preparar(self, caso):
        if caso.get('tasa_historica'):
            t = caso['tasa_historica']
            TasaIgvVigencia.objects.create(empresa=self.empresa, vigente_desde=date.fromisoformat(t['vigente_desde']),
                                           tasa_pct=Decimal(t['tasa_pct']))
        if caso['moneda'] == 'USD':
            self.crear_tc(date.fromisoformat(caso['fecha']), caso['tc_venta'])
        if caso.get('requiere_stock'):
            self.compra_confirmada('500', '10', fecha='2026-01-05')
        origen = None
        if caso.get('origen') == 'COMPRA':
            origen = self.compra_confirmada('10', '10', fecha='2026-01-11')
        elif caso.get('origen') == 'VENTA':
            origen = self.documento_confirmado('VENTA', [self.linea('VENTA', '5', '30')], fecha='2026-01-11')
        return Documento.objects.get(pk=origen) if origen else None

    def lineas_api(self, caso, origen):
        lineas = []
        for i, l in enumerate(caso['lineas']):
            unidad = self.unidad_con_factor(l.get('factor', '1'))
            linea = self.linea(l['operacion'], l['cantidad'], l['precio'],
                               producto_unidad=unidad.id,
                               # El IGV que envía el frontend: el sugerido (= esperado del caso de oro).
                               igv=caso['esperado']['lineas'][i]['igv'],
                               afectacion_igv=l['afectacion'],
                               es_bonificacion=bool(l.get('bonificacion')))
            if origen is not None:
                linea['detalle_origen'] = DocumentoDetalle.objects.filter(documento=origen).first().id
            lineas.append(linea)
        return lineas

    def verificar_caso(self, caso):
        tipos = {'FACTURA': self.factura, 'NC': self.nota_credito, 'ND': self.nota_debito}
        origen = self.preparar(caso)
        datos = self.payload(caso['clase'], self.lineas_api(caso, origen), tipo=tipos[caso['tipo']],
                             fecha=caso['fecha'], moneda=caso['moneda'], origen=origen)
        doc = Documento.objects.get(pk=self.crear(datos).data['id'])
        esperado = caso['esperado']
        self.assertEqual((texto(doc.subtotal), texto(doc.igv), texto(doc.total)),
                         (esperado['subtotal'], esperado['igv'], esperado['total']))
        detalles = list(doc.detalles.order_by('linea'))
        self.assertEqual(len(detalles), len(esperado['lineas']))
        for det, esp in zip(detalles, esperado['lineas']):
            self.assertEqual(texto(det.igv), esp['igv'])
            self.assertEqual(texto(det.cantidad_base), esp['cantidad_base'])
            self.assertEqual(texto(det.precio_unitario * det.cantidad_original), texto(esp['importe']))
        # Se puede revisar y confirmar (impacta Kardex) sin errores de validación.
        self.revisar(doc.id)
        self.confirmar(doc.id)

    def test_usd_costo_en_pen_lo_calcula_solo_el_backend(self):
        caso = next(c for c in CASOS if c['id'] == 'compra_usd_tc')
        self.preparar(caso)
        doc_id = self.crear(self.payload('COMPRA', self.lineas_api(caso, None), fecha=caso['fecha'],
                                         moneda='USD')).data['id']
        doc = Documento.objects.get(pk=doc_id)
        self.assertEqual(doc.monto_tc, Decimal(caso['tc_venta']))
        for det, l in zip(doc.detalles.order_by('linea'), caso['lineas']):
            valor_pen = Decimal(l['precio']) * Decimal(l['cantidad']) * Decimal(caso['tc_venta'])
            esperado = (valor_pen / det.cantidad_base).quantize(Q8, rounding=ROUND_HALF_UP)
            self.assertEqual(det.costo_unitario_pen, esperado)  # IGV 100 % recuperable: no entra al costo

    def test_valor_anterior_del_frontend_quedaba_guardado_con_0_00004875_de_mas(self):
        """Documenta la causa raíz: el backend acepta el IGV del frontend (±0.01) y lo guarda tal cual."""
        caso = next(c for c in CASOS if c['id'] == 'auditoria_0_00004875')
        lineas = self.lineas_api(caso, None)
        lineas[0]['igv'] = caso['antes']['igv_lineas'][0]  # 0.03004875 (float, sin redondear a céntimos)
        doc = Documento.objects.get(pk=self.crear(self.payload('COMPRA', lineas)).data['id'])
        self.assertEqual(texto(doc.total), caso['antes']['total'])
        self.assertEqual(texto(doc.total - Decimal(caso['esperado']['total'])), '0.00004875')

    def test_total_se_redondea_half_up_no_half_even(self):
        caso = next(c for c in CASOS if c['id'] == 'redondeo_mitad_hacia_arriba')
        doc = Documento.objects.get(pk=self.crear(self.payload('COMPRA', self.lineas_api(caso, None))).data['id'])
        self.assertEqual(texto(doc.subtotal), '1.26734567')  # HALF_EVEN daría 1.26734566


# Un test por caso de oro (cada uno en su propia transacción: la tasa histórica o el TC de
# un caso no afectan a los demás).
def _crear_test(caso):
    def test(self):
        self.verificar_caso(caso)
    test.__doc__ = caso['descripcion']
    return test


for _caso in CASOS:
    setattr(PrecisionDocumentosTests, f"test_caso_{_caso['id']}", _crear_test(_caso))
