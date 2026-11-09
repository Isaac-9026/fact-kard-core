"""
Bloque 5 — Formato 13.1: el saldo valorizado de CADA fila por establecimiento es su parte
del saldo real de la empresa en ese instante (cantidad × CPP global, redondeo al
establecimiento principal). En todo momento: suma de establecimientos = empresa.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import Establecimiento
from apps.inventario.models import Almacen
from apps.reportes.formato131_service import generar_formato_131
from apps.reportes.saldos_corte import q8

D = Decimal


class Formato131FilasEstablecimientoTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.sucursal = Establecimiento.objects.create(empresa=self.empresa, codigo_sunat='0001', nombre='SUCURSAL')
        self.almacen_b = Almacen.objects.create(empresa=self.empresa, establecimiento=self.sucursal, codigo='ALMB', nombre='B')

    def escenario(self):
        compra = self.compra_confirmada('1', '1', fecha='2026-01-05')                       # principal
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '2', '0.5', almacen=self.almacen_b.id)],
                                  fecha='2026-01-06')                                         # sucursal
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30', almacen=self.almacen_b.id)],
                                          fecha='2026-01-08')
        self.documento_confirmado(                                                            # devolución
            'VENTA', [self.linea('DEVOLUCION_VENTA', '1', '30', almacen=self.almacen_b.id,
                                 detalle_origen=DocumentoDetalle.objects.get(documento_id=venta).id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=venta), fecha='2026-01-09',
        )
        self.documento_confirmado(                                                            # ajuste de valor
            'COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '0.13',
                                  detalle_origen=DocumentoDetalle.objects.get(documento_id=compra).id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=compra), fecha='2026-01-10',
        )
        self.anular(self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30')], fecha='2026-01-11'))  # extorno

    def test_cada_fila_es_la_parte_del_saldo_real_y_suman_la_empresa(self):
        self.escenario()
        reportes = {r['cabecera']['establecimiento']['id']: r
                    for r in generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)['reportes']}
        kardex = {f['id']: f for f in self.client.get(reverse('kardex-report'), {'producto_id': self.producto.id},
                                                       **self.headers).data['movimientos']}
        filas = sorted(
            ((estab, f) for estab, r in reportes.items() for f in r['movimientos']),
            key=lambda x: (x[1]['fecha_emision'], x[1]['orden']['prioridad_dia'], x[1]['orden']['secuencia'],
                           x[1]['movimiento_id']),
        )
        cantidades = {e: D(r['saldo_inicial_valorizado']['cantidad']) for e, r in reportes.items()}
        principal = self.establecimiento.id
        self.assertGreaterEqual(len(filas), 7)
        for estab, fila in filas:
            cantidades[estab] = D(fila['saldo_final']['cantidad'])
            cpp = D(fila['saldo_final']['costo_unitario'])
            k = kardex[fila['movimiento_id']]
            esperado = {e: q8(c * cpp) for e, c in cantidades.items()}
            esperado[principal] = q8(esperado[principal] + D(k['saldo_valor']) - sum(esperado.values()))
            with self.subTest(movimiento=fila['movimiento_id']):
                self.assertEqual(D(fila['saldo_final']['costo_total']), esperado[estab])
                self.assertEqual(sum(esperado.values()), D(k['saldo_valor']))  # establecimientos = empresa
                self.assertEqual(sum(cantidades.values()), D(k['saldo_cantidad']))
                if estab != principal:  # no se inventan costos: cantidad × CPP global
                    self.assertEqual(D(fila['saldo_final']['costo_total']), q8(cantidades[estab] * cpp))
        total = sum(D(r['saldo_final']['costo_total']) for r in reportes.values())
        self.assertEqual(total, D(kardex[filas[-1][1]['movimiento_id']]['saldo_valor']))
