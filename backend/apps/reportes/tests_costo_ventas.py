"""
Costo de venta: Saldo inicial + Compras − Saldo final = Costo de venta.

- El ejemplo del dueño (3 u. × S/ 10 + 100 u. × S/ 10 − 50 u. × S/ 10 = 53 u. / S/ 530).
- Promedio del período (un solo P.U.): 100 × 20 + 100 × 22.50 → P.U. 21.25 → C. venta 1 062.50,
  con la diferencia frente al Kardex (promedio móvil) informada.
- Escenario integral (devolución, transferencia, nota de crédito de compra, anulación, merma):
  la fórmula cuadra al centavo y el desglose suma exactamente el costo de venta.
- Rango de meses: un solo promedio para todo el rango.
- Validaciones multiempresa, endpoint y la 5ta hoja del Excel del Kardex Valorizado.
"""
import io
from datetime import date
from decimal import Decimal

import openpyxl
from django.test import TestCase
from django.urls import reverse

from apps.catalogos.models import TipoOperacion
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import Establecimiento, Periodo
from apps.inventario.models import (
    Almacen, NotaInterna, NotaInternaDetalle, SaldoInicial, Transferencia, TransferenciaDetalle,
)
from apps.inventario.services import confirmar_nota_interna, confirmar_saldo_inicial, confirmar_transferencia
from apps.reportes.costo_ventas import generar_costo_ventas
from apps.reportes.services import consultar_kardex_valorizado

D = Decimal


def dec(valor):
    return D(valor) if valor is not None else None


class CostoVentasBase(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.febrero = Periodo.objects.create(
            empresa=self.empresa, anio=2026, mes=2, orden=202602,
            fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 2, 28), estado='ABIERTO',
        )

    def saldo_inicial(self, cantidad, valor, producto=None):
        producto = producto or self.producto
        saldo = SaldoInicial.objects.create(
            empresa=self.empresa, periodo=self.enero, almacen=self.almacen, producto=producto,
            cantidad=D(cantidad), valor_pen=D(valor), cpp_inicial=(D(valor) / D(cantidad)).quantize(D('0.000001')),
            creado_por=self.usuario,
        )
        confirmar_saldo_inicial(saldo_id=saldo.id, empresa_id=self.empresa.id, usuario=self.usuario)

    def merma(self, cantidad, fecha, periodo=None):
        nota = NotaInterna.objects.create(
            empresa=self.empresa, almacen=self.almacen, periodo=periodo or self.enero,
            tipo_operacion=TipoOperacion.objects.get(codigo_interno='MERMA'),
            fecha=fecha, motivo='Merma de prueba', creado_por=self.usuario,
        )
        NotaInternaDetalle.objects.create(nota_interna=nota, producto=self.producto, cantidad_base=D(cantidad))
        confirmar_nota_interna(nota_id=nota.id, empresa_id=self.empresa.id, usuario=self.usuario)

    def crear_tipo_merma(self):
        TipoOperacion.objects.get_or_create(
            codigo_interno='MERMA',
            defaults=dict(codigo_sunat='13', descripcion='MERMA', naturaleza='SALIDA',
                          origen_requerido='NOTA_INTERNA', es_interna=True),
        )

    def reporte(self, periodo=None, hasta=None, **kwargs):
        return generar_costo_ventas(
            empresa_id=self.empresa.id, periodo_id=(periodo or self.enero).id,
            periodo_hasta_id=hasta.id if hasta else None, **kwargs,
        )

    def fila(self, reporte, producto=None):
        producto = producto or self.producto
        return next(f for f in reporte['productos'] if f['producto']['id'] == producto.id)


class EjemploDelDuenoTests(CostoVentasBase):
    def test_ejemplo_del_dueno(self):
        # S.I. 3 u. × 10 = 30; + Compras 100 u. × 10 = 1 000; − S. final 50 u. × 10 = 500 → C. ventas 530.
        self.saldo_inicial('3', '30')
        self.compra_confirmada('100', '10', fecha='2026-01-05')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '53', '15')], fecha='2026-01-20')

        fila = self.fila(self.reporte())
        esperado = {
            'saldo_inicial': ('3', '10', '30'),
            'compras': ('100', '10', '1000'),
            'saldo_final': ('50', '10', '500'),
            'costo_venta': ('53', '10', '530'),
        }
        for clave, (cantidad, unitario, valor) in esperado.items():
            with self.subTest(clave=clave):
                self.assertEqual(dec(fila[clave]['cantidad']), D(cantidad))
                self.assertEqual(dec(fila[clave]['costo_unitario']), D(unitario))
                self.assertEqual(dec(fila[clave]['valor']), D(valor))
        self.assertEqual(dec(fila['desglose']['ventas']['valor']), D('530'))
        self.assertEqual(dec(fila['diferencia']), D('0'))

    def test_promedio_del_periodo_un_solo_pu(self):
        # S.I. 100 u. × 20 = 2 000; se venden 50 u.; luego compra 100 u. × 22.50 = 2 250.
        # Disponible 200 u. / 4 250 → P.U. 21.25 → S. final 150 × 21.25 = 3 187.50 → C. venta 1 062.50.
        self.saldo_inicial('100', '2000')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '50', '30')], fecha='2026-01-10')
        self.compra_confirmada('100', '22.50', fecha='2026-01-20')

        fila = self.fila(self.reporte())
        esperado = {
            'saldo_inicial': ('100', '20', '2000'),
            'compras': ('100', '22.50', '2250'),
            'disponible': ('200', '21.25', '4250'),
            'saldo_final': ('150', '21.25', '3187.50'),
            'costo_venta': ('50', '21.25', '1062.50'),
        }
        for clave, (cantidad, unitario, valor) in esperado.items():
            with self.subTest(clave=clave):
                self.assertEqual(dec(fila[clave]['cantidad']), D(cantidad))
                self.assertEqual(dec(fila[clave]['costo_unitario']), D(unitario))
                self.assertEqual(dec(fila[clave]['valor']), D(valor))
        self.assertEqual(dec(fila['costo_promedio']), D('21.25'))
        self.assertEqual(dec(fila['desglose']['ventas']['valor']), D('1062.50'))
        self.assertEqual(dec(fila['diferencia']), D('0'))
        self.assertEqual(dec(fila['mermas']['valor']), D('0'))
        # El Kardex (promedio móvil) vendió a 20.00: se informa la diferencia por método.
        self.assertEqual(dec(fila['kardex']['costo_venta']['valor']), D('1000'))
        self.assertEqual(dec(fila['kardex']['saldo_final']['valor']), D('3250'))
        self.assertEqual(dec(fila['diferencia_metodo']), D('62.50'))

    def test_mermas_van_aparte_y_no_son_costo_de_venta(self):
        # Mismo ejemplo con 2 u. de merma: disponible 200 u. × 21.25; S. final 148 u.;
        # mermas 2 × 21.25 = 42.50; costo de venta solo lo vendido: 50 × 21.25 = 1 062.50.
        self.crear_tipo_merma()
        self.saldo_inicial('100', '2000')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '50', '30')], fecha='2026-01-10')
        self.compra_confirmada('100', '22.50', fecha='2026-01-20')
        self.merma('2', date(2026, 1, 25))

        reporte = self.reporte()
        fila = self.fila(reporte)
        self.assertEqual(dec(fila['saldo_final']['cantidad']), D('148'))
        self.assertEqual(dec(fila['saldo_final']['valor']), D('3145'))
        self.assertEqual(dec(fila['mermas']['cantidad']), D('2'))
        self.assertEqual(dec(fila['mermas']['costo_unitario']), D('21.25'))
        self.assertEqual(dec(fila['mermas']['valor']), D('42.50'))
        self.assertEqual(dec(fila['costo_venta']['cantidad']), D('50'))
        self.assertEqual(dec(fila['costo_venta']['valor']), D('1062.50'))
        self.assertEqual(dec(fila['diferencia']), D('0'))
        self.assertNotIn('mermas_desmedros', fila['desglose'])
        totales = reporte['totales']
        self.assertEqual(dec(totales['mermas']['valor']), D('42.50'))
        self.assertEqual(dec(totales['costo_venta']['valor']), D('1062.50'))
        self.assertIn('Mermas', reporte['formula'])

    def test_bonificacion_entra_a_costo_cero_y_baja_el_pu(self):
        # + 10 u. de bonificación (costo 0): disponible 210 u. / 4 250 → P.U. 20.238095…
        # S. final 160 u. → 3 238.10; costo de venta 4 250 − 3 238.10 = 1 011.90 (antes 1 062.50).
        self.saldo_inicial('100', '2000')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '50', '30')], fecha='2026-01-10')
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '100', '22.50'),
                                             self.linea('COMPRA', '10', '22.50', es_bonificacion=True)],
                                  fecha='2026-01-20')
        fila = self.fila(self.reporte())
        self.assertEqual(dec(fila['disponible']['cantidad']), D('210'))
        self.assertEqual(dec(fila['disponible']['valor']), D('4250'))
        self.assertEqual(dec(fila['saldo_final']['valor']), D('3238.10'))
        self.assertEqual(dec(fila['costo_venta']['cantidad']), D('50'))
        self.assertEqual(dec(fila['costo_venta']['valor']), D('1011.90'))

    def test_totales_de_la_empresa_suman_los_productos(self):
        self.saldo_inicial('3', '30')
        self.saldo_inicial('10', '50', producto=self.producto_2)
        self.compra_confirmada('100', '10', fecha='2026-01-05')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '53', '15'),
                                            self.linea('VENTA', '4', '9', producto=self.producto_2)],
                                  fecha='2026-01-20')
        reporte = self.reporte()
        totales = reporte['totales']
        self.assertEqual(dec(totales['saldo_inicial']['valor']), D('80'))
        self.assertEqual(dec(totales['compras']['valor']), D('1000'))
        self.assertEqual(dec(totales['saldo_final']['valor']), D('530'))
        self.assertEqual(dec(totales['costo_venta']['valor']), D('550'))
        self.assertIsNone(totales['costo_venta']['cantidad'])  # unidades distintas no se suman
        self.assertEqual(dec(totales['diferencia']), D('0'))
        self.assertEqual(sum(dec(f['costo_venta']['valor']) for f in reporte['productos']), D('550'))


class EscenarioIntegralTests(CostoVentasBase):
    def setUp(self):
        super().setUp()
        for codigo, sunat, naturaleza, origen in (
            ('TRANSFERENCIA_SALIDA', '11', 'SALIDA', 'TRANSFERENCIA'),
            ('TRANSFERENCIA_ENTRADA', '21', 'ENTRADA', 'TRANSFERENCIA'),
        ):
            TipoOperacion.objects.create(codigo_interno=codigo, codigo_sunat=sunat, descripcion=codigo,
                                         naturaleza=naturaleza, origen_requerido=origen, es_interna=True)
        self.crear_tipo_merma()
        sucursal = Establecimiento.objects.create(empresa=self.empresa, codigo_sunat='0001', nombre='SUCURSAL')
        self.almacen_b = Almacen.objects.create(empresa=self.empresa, establecimiento=sucursal,
                                                codigo='ALMB', nombre='SUCURSAL')

    def escenario_enero(self):
        self.saldo_inicial('3', '2.00')                                       # CPP con decimales
        compra = self.compra_confirmada('5', '1.10', fecha='2026-01-05')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '2', '30')], fecha='2026-01-10')
        self.documento_confirmado(                                            # devolución de venta
            'VENTA', [self.linea('DEVOLUCION_VENTA', '1', '30',
                                 detalle_origen=DocumentoDetalle.objects.get(documento_id=venta).id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=venta), fecha='2026-01-12',
        )
        transferencia = Transferencia.objects.create(empresa=self.empresa, almacen_origen=self.almacen,
                                                     almacen_destino=self.almacen_b, fecha=date(2026, 1, 14),
                                                     creado_por=self.usuario)
        TransferenciaDetalle.objects.create(transferencia=transferencia, producto=self.producto, cantidad_base=D('2'))
        confirmar_transferencia(transferencia_id=transferencia.id, empresa_id=self.empresa.id, usuario=self.usuario)
        self.documento_confirmado(                                            # descuento en compra
            'COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '0.37',
                                  detalle_origen=DocumentoDetalle.objects.get(documento_id=compra).id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=compra), fecha='2026-01-15',
        )
        self.anular(self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30')], fecha='2026-01-16'))
        self.merma('1', date(2026, 1, 18))
        self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30')], fecha='2026-01-20')

    def test_formula_promedio_del_periodo_y_desglose(self):
        self.escenario_enero()
        fila = self.fila(self.reporte())
        si, compras = dec(fila['saldo_inicial']['valor']), dec(fila['compras']['valor'])
        sf, cv = dec(fila['saldo_final']['valor']), dec(fila['costo_venta']['valor'])

        self.assertEqual(si, D('2.00'))
        mermas = dec(fila['mermas']['valor'])
        self.assertEqual(cv, si + compras - sf - mermas)
        # 3 + 5 − 2 + 1 − 1 (merma) − 1 (venta) = 5 u.; la anulación y la transferencia no cambian el saldo.
        self.assertEqual(dec(fila['disponible']['cantidad']), D('8'))
        self.assertEqual(dec(fila['saldo_final']['cantidad']), D('5'))
        self.assertEqual(dec(fila['mermas']['cantidad']), D('1'))
        self.assertEqual(dec(fila['costo_venta']['cantidad']), D('2'))   # 2 − 1 devolución + 1 venta (sin merma)
        promedio = (si + compras) / D('8')
        self.assertEqual(sf, (D('5') * promedio).quantize(D('0.01')))
        self.assertEqual(mermas, (D('1') * promedio).quantize(D('0.01')))

        kardex = consultar_kardex_valorizado(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                             periodo_id=self.enero.id)['resumen']
        self.assertEqual(dec(fila['saldo_final']['cantidad']), D(str(kardex['saldo_final_cantidad'])))

        compras_detalle = fila['compras_detalle']
        self.assertEqual(dec(compras_detalle['compras']['valor']), D('5.50'))
        self.assertLess(dec(compras_detalle['notas_credito_debito']['valor']), D('0'))
        self.assertEqual(compras, sum(dec(v['valor']) for v in compras_detalle.values()))

        desglose = fila['desglose']
        self.assertEqual(dec(desglose['transferencias']['valor']), D('0'))
        self.assertEqual(dec(desglose['transferencias']['cantidad']), D('0'))
        self.assertNotIn('mermas_desmedros', desglose)
        self.assertLess(dec(desglose['devoluciones_venta']['valor']), D('0'))
        self.assertEqual(dec(desglose['ventas']['cantidad']), D('3'))     # 2 + 1 anulada (−1) + 1
        self.assertEqual(sum(dec(v['valor']) for v in desglose.values()), cv)
        self.assertEqual(dec(fila['diferencia']), D('0'))

    def test_rango_de_meses_usa_un_solo_promedio(self):
        self.escenario_enero()
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '7', '13')], fecha='2026-02-03', periodo=self.febrero)
        self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-02-10', periodo=self.febrero)

        enero, febrero = self.fila(self.reporte()), self.fila(self.reporte(self.febrero))
        rango = self.reporte(self.enero, hasta=self.febrero)
        total = self.fila(rango)
        # El saldo inicial de cada mes es el valor del Kardex al cierre del mes anterior.
        kardex_enero = consultar_kardex_valorizado(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                                   periodo_id=self.enero.id)['resumen']
        self.assertEqual(dec(febrero['saldo_inicial']['valor']), D(str(kardex_enero['saldo_final_valor'])))
        self.assertEqual(dec(total['saldo_inicial']['valor']), dec(enero['saldo_inicial']['valor']))
        self.assertEqual(dec(total['compras']['valor']), dec(enero['compras']['valor']) + dec(febrero['compras']['valor']))
        self.assertEqual(dec(total['saldo_final']['cantidad']), dec(febrero['saldo_final']['cantidad']))
        # Un solo P.U. para todo el rango.
        disp_valor = dec(total['saldo_inicial']['valor']) + dec(total['compras']['valor'])
        self.assertEqual(dec(total['disponible']['valor']), disp_valor)
        self.assertEqual(dec(total['disponible']['cantidad']), D('15'))   # 3 + 5 + 7
        self.assertEqual(dec(total['saldo_final']['valor']),
                         (dec(total['saldo_final']['cantidad']) * disp_valor / D('15')).quantize(D('0.01')))
        self.assertEqual(dec(total['costo_venta']['valor']),
                         disp_valor - dec(total['saldo_final']['valor']) - dec(total['mermas']['valor']))
        self.assertEqual(rango['periodo_desde']['etiqueta'], '2026-01')
        self.assertEqual(rango['periodo_hasta']['etiqueta'], '2026-02')
        self.assertEqual(dec(rango['totales']['diferencia']), D('0'))


class CostoVentasApiTests(CostoVentasBase):
    def setUp(self):
        super().setUp()
        self.saldo_inicial('3', '30')
        self.compra_confirmada('100', '10', fecha='2026-01-05')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '53', '15')], fecha='2026-01-20')

    def test_endpoint_json(self):
        resp = self.client.get(reverse('costo-ventas'), {'periodo_id': self.enero.id}, **self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(dec(resp.data['totales']['costo_venta']['valor']), D('530'))
        self.assertEqual(resp.data['empresa']['ruc'], self.empresa.ruc)

    def test_filtro_por_producto(self):
        self.saldo_inicial('10', '50', producto=self.producto_2)
        reporte = self.reporte(producto_id=self.producto.id)
        self.assertEqual([f['producto']['id'] for f in reporte['productos']], [self.producto.id])

    def test_validaciones(self):
        url = reverse('costo-ventas')
        otro = Periodo.objects.create(empresa=self.otra_empresa, anio=2026, mes=1, orden=202601,
                                      fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 31))
        casos = [
            ({}, 'periodo_id'),
            ({'periodo_id': otro.id}, 'periodo_id'),
            ({'periodo_id': self.febrero.id, 'periodo_hasta_id': self.enero.id}, 'periodo_hasta_id'),
            ({'periodo_id': self.enero.id, 'periodo_hasta_id': otro.id}, 'periodo_hasta_id'),
            ({'periodo_id': self.enero.id, 'producto_id': 999999}, 'producto_id'),
            ({'periodo_id': 'abc'}, 'periodo_id'),
        ]
        for params, campo in casos:
            with self.subTest(params=params):
                resp = self.client.get(url, params, **self.headers)
                self.assertEqual(resp.status_code, 400)
                self.assertIn(campo, resp.data)

    def test_no_mezcla_empresas(self):
        resp = self.client.get(reverse('costo-ventas'), {'periodo_id': self.enero.id},
                               HTTP_X_EMPRESA_ID=str(self.otra_empresa.id))
        self.assertEqual(resp.status_code, 403)

    def _hoja_kardex(self, **params):
        resp = self.client.get(reverse('kardex-excel-export'), params, **self.headers)
        self.assertEqual(resp.status_code, 200)
        libro = openpyxl.load_workbook(io.BytesIO(resp.content))
        self.assertEqual(libro.sheetnames[-1], 'Costo de Venta')
        self.assertEqual(len(libro.sheetnames), 5)
        return libro['Costo de Venta']

    def test_excel_kardex_trae_hoja_costo_venta(self):
        hoja = self._hoja_kardex(periodo_id=self.enero.id)
        filas = list(hoja.iter_rows(values_only=True))
        resumen = {f[0]: f[1] for f in filas if f[0]}
        self.assertEqual(D(str(resumen['Saldo inicial'])), D('30'))
        self.assertEqual(D(str(resumen['+ Compras netas'])), D('1000'))
        self.assertEqual(D(str(resumen['= COSTO DE VENTA'])), D('530'))
        self.assertEqual(D(str(resumen['Diferencia (debe ser 0)'])), D('0'))
        self.assertEqual(D(str(resumen['Diferencia por método'])), D('0'))
        self.assertNotIn('− Mermas (al P.U. promedio)', resumen)      # sin mermas no aparece la línea
        producto = [f for f in filas if f[0] == self.producto.codigo_interno][0]
        self.assertEqual(D(str(producto[10])), D('10'))      # P.U. promedio del período
        self.assertEqual(D(str(producto[15])), D('53'))      # unidades vendidas
        self.assertEqual(D(str(producto[17])), D('530'))     # costo de venta
        total = [f for f in filas if f[0] == 'TOTAL EMPRESA'][0]
        self.assertEqual(D(str(total[17])), D('530'))
        self.assertFalse(any('no aplica' in str(f[0]) for f in filas if f[0]))

    def test_excel_con_mermas_muestra_la_linea_aparte(self):
        self.crear_tipo_merma()
        self.merma('3', date(2026, 1, 25))
        hoja = self._hoja_kardex(periodo_id=self.enero.id)
        filas = list(hoja.iter_rows(values_only=True))
        resumen = {f[0]: f[1] for f in filas if f[0]}
        self.assertEqual(D(str(resumen['− Mermas (al P.U. promedio)'])), D('30'))     # 3 u. × 10
        self.assertEqual(D(str(resumen['= COSTO DE VENTA'])), D('530'))               # solo lo vendido
        producto = [f for f in filas if f[0] == self.producto.codigo_interno][0]
        self.assertEqual(D(str(producto[17])), D('30'))      # mermas
        self.assertEqual(D(str(producto[20])), D('530'))     # costo de venta

    def test_excel_kardex_filtro_almacen_avisa_que_es_por_empresa(self):
        hoja = self._hoja_kardex(periodo_id=self.enero.id, almacen_id=self.almacen.id)
        textos = [str(f[0]) for f in hoja.iter_rows(values_only=True) if f[0]]
        self.assertTrue(any('no aplica el filtro de almacén' in t for t in textos))

    def test_excel_kardex_sin_periodo_pide_elegirlo(self):
        hoja = self._hoja_kardex()
        textos = [str(f[0]) for f in hoja.iter_rows(values_only=True) if f[0]]
        self.assertTrue(any('Seleccione un período' in t for t in textos))
        self.assertNotIn('= COSTO DE VENTA', textos)

    def test_ya_no_hay_excel_separado(self):
        resp = self.client.get('/api/reportes/costo-ventas/excel/', {'periodo_id': self.enero.id}, **self.headers)
        self.assertEqual(resp.status_code, 404)
