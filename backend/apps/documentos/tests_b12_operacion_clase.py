"""
Bloque 12 — el backend es la autoridad sobre la operación de cada línea de un comprobante.

Antes solo se validaba la naturaleza: COMPRA + AJUSTE_INGRESO, VENTA + AJUSTE_SALIDA o
COMPRA + SALDO_INICIAL se aceptaban (201). Ahora además debe ser una operación comercial del
flujo de ese comprobante (apps.documentos.reglas._validar_contexto_comercial, derivada de
es_interna y origen_requerido del catálogo). Las notas internas, transferencias y saldos
iniciales siguen funcionando por su propio módulo.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.catalogos.models import TipoOperacion
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento
from apps.inventario.models import Almacen

# Atributos de seed_catalogos_sunat (código SUNAT, naturaleza, es_interna, afecta_kardex, origen).
SEED_FALTANTES = {
    'BONIFICACION': ('99', 'ENTRADA', False, True, 'DOCUMENTO'),
    'AJUSTE_INGRESO': ('99', 'ENTRADA', True, True, 'NOTA_INTERNA'),
    'AJUSTE_SALIDA': ('99', 'SALIDA', True, True, 'NOTA_INTERNA'),
    'AJUSTE_VALOR_MANUAL': ('99', 'AJUSTE_VALOR', True, True, 'NOTA_INTERNA'),
    'MERMA': ('13', 'SALIDA', True, True, 'NOTA_INTERNA'),
    'TRANSFERENCIA_ENTRADA': ('21', 'ENTRADA', True, True, 'TRANSFERENCIA'),
    'TRANSFERENCIA_SALIDA': ('11', 'SALIDA', True, True, 'TRANSFERENCIA'),
}


class OperacionComercialBase(Bloque2Fixture):
    def setUp(self):
        self.crear_base()
        for codigo, (sunat, naturaleza, interna, afecta, origen) in SEED_FALTANTES.items():
            self.op[codigo] = TipoOperacion.objects.create(
                codigo_interno=codigo, descripcion=codigo, codigo_sunat=sunat, naturaleza=naturaleza,
                es_interna=interna, afecta_kardex=afecta, origen_requerido=origen,
            )
        # En la seed real SALDO_INICIAL NO está marcada como interna: se rechaza por su origen.
        TipoOperacion.objects.filter(codigo_interno='SALDO_INICIAL').update(es_interna=False)

    def assert_rechazado(self, data, *textos):
        antes = Documento.objects.filter(empresa=self.empresa).count()
        resp = self.crear(data, esperado=400)
        for texto in textos:
            self.assertIn(texto, str(resp.data))
        self.assertEqual(Documento.objects.filter(empresa=self.empresa).count(), antes)
        return resp


class OperacionIncompatibleConLaClaseTests(OperacionComercialBase, TestCase):
    """Naturaleza incorrecta: se mantiene el rechazo y el mensaje de siempre."""

    def test_compra_con_operacion_venta(self):
        self.assert_rechazado(self.payload('COMPRA', [self.linea('VENTA', '2', '10')]),
                              "la operación 'VENTA' (naturaleza SALIDA) no es válida para un comprobante de compra")
        self.assertFalse(self.movimientos().exists())

    def test_venta_con_operacion_compra(self):
        self.assert_rechazado(self.payload('VENTA', [self.linea('COMPRA', '2', '10')]),
                              "la operación 'COMPRA' (naturaleza ENTRADA) no es válida para un comprobante de venta")

    def test_compra_con_ajuste_de_valor(self):
        self.assert_rechazado(self.payload('COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '2', '10')]),
                              "(naturaleza AJUSTE_VALOR) no es válida para un comprobante de compra")


class OperacionInternaEnComprobanteTests(OperacionComercialBase, TestCase):
    """Naturaleza correcta pero operación interna: antes 201, ahora 400."""

    CASOS = (
        ('COMPRA', 'AJUSTE_INGRESO', 'NOTA_INTERNA'),
        ('VENTA', 'AJUSTE_SALIDA', 'NOTA_INTERNA'),
        ('COMPRA', 'SALDO_INICIAL', 'SALDO_INICIAL'),
        ('COMPRA', 'TRANSFERENCIA_ENTRADA', 'TRANSFERENCIA'),
        ('VENTA', 'TRANSFERENCIA_SALIDA', 'TRANSFERENCIA'),
        ('VENTA', 'MERMA', 'NOTA_INTERNA'),
    )

    def test_operaciones_internas_rechazadas_en_compra_y_venta(self):
        self.compra_confirmada('20', '10')  # stock para que nada dependa de él
        for clase, operacion, origen in self.CASOS:
            with self.subTest(clase=clase, operacion=operacion):
                self.assert_rechazado(
                    self.payload(clase, [self.linea(operacion, '1', '10')]),
                    f"la operación '{operacion}' es de uso interno (origen {origen})",
                )

    def test_residuo_automatico_rechazado_en_nota(self):
        # RESIDUO_AUTOMATICO es AJUSTE_VALOR (origen MOTOR): en una compra normal ya fallaba por
        # naturaleza; en una NC de compra, donde AJUSTE_VALOR sí se admite, ahora falla por origen.
        compra = self.compra_confirmada('10', '10')
        self.assert_rechazado(self.payload('COMPRA', [self.linea('RESIDUO_AUTOMATICO', '1', '5')], tipo=self.nota_credito,
                                           origen=Documento.objects.get(pk=compra), fecha='2026-01-15'),
                              "la operación 'RESIDUO_AUTOMATICO' es de uso interno (origen MOTOR)")
        self.assert_rechazado(self.payload('COMPRA', [self.linea('RESIDUO_AUTOMATICO', '1', '5')]), 'no es válida para un comprobante de compra')

    def test_ajuste_valor_manual_rechazado_en_nota(self):
        compra = self.compra_confirmada('10', '10')
        self.assert_rechazado(self.payload('COMPRA', [self.linea('AJUSTE_VALOR_MANUAL', '1', '5')], tipo=self.nota_debito,
                                           origen=Documento.objects.get(pk=compra), fecha='2026-01-15'),
                              "'AJUSTE_VALOR_MANUAL' es de uso interno (origen NOTA_INTERNA)")

    def test_operacion_interna_creada_antes_no_se_puede_confirmar(self):
        # Un borrador guardado antes del cambio se vuelve a validar al confirmar (motor Kardex).
        doc = self.crear(self.payload('COMPRA', [self.linea('COMPRA', '1', '10')])).data['id']
        Documento.objects.get(pk=doc).detalles.update(tipo_operacion=self.op['AJUSTE_INGRESO'])
        self.revisar(doc)
        resp = self.confirmar(doc, esperado=400)
        self.assertIn("'AJUSTE_INGRESO' es de uso interno", str(resp.data))
        self.assertFalse(self.movimientos().exists())


class DevolucionSoloEnNotaTests(OperacionComercialBase, TestCase):
    def test_factura_con_devolucion_rechazada(self):
        self.assert_rechazado(self.payload('VENTA', [self.linea('DEVOLUCION_COMPRA', '1', '10')]),
                              "'DEVOLUCION_COMPRA' no es válida para un comprobante de venta",
                              'una devolución solo se registra con una Nota de Crédito')

    def test_nota_de_credito_con_operacion_de_factura_rechazada(self):
        compra = self.compra_confirmada('10', '10')
        detalle = Documento.objects.get(pk=compra).detalles.get(linea=1)
        self.assert_rechazado(self.payload('COMPRA', [self.linea('VENTA', '1', '10', detalle_origen=detalle.id)], tipo=self.nota_credito,
                                           origen=Documento.objects.get(pk=compra), fecha='2026-01-15'),
                              "'VENTA' no es válida para una Nota de Crédito de compra",
                              'en una nota el movimiento físico es una devolución')


class FlujosValidosSiguenTests(OperacionComercialBase, TestCase):
    def test_compra_venta_y_bonificacion(self):
        self.compra_confirmada('10', '10')
        bonif = self.documento_confirmado('COMPRA', [
            self.linea('COMPRA', '5', '10'),
            self.linea('BONIFICACION', '2', '0', igv='0.00', afectacion_igv='GRATUITO', es_bonificacion=True),
        ], fecha='2026-01-11')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '20')], fecha='2026-01-12')
        self.assertEqual(Documento.objects.get(pk=bonif).estado, 'CONFIRMADO')
        self.assertEqual(Documento.objects.get(pk=venta).estado, 'CONFIRMADO')
        self.assertEqual(self.stock(), Decimal('13'))  # 10 + 5 + 2 bonificadas − 4

    def test_notas_de_credito_y_debito(self):
        compra = self.compra_confirmada('10', '10')
        origen_c = Documento.objects.get(pk=compra)
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '20')], fecha='2026-01-12')
        origen_v = Documento.objects.get(pk=venta)
        casos = [
            ('COMPRA', self.nota_credito, origen_c, [self.linea('DEVOLUCION_COMPRA', '1', '10', detalle_origen=origen_c.detalles.get(linea=1).id)]),
            ('COMPRA', self.nota_credito, origen_c, [self.linea('NC_DESCUENTO_COMPRA', '1', '5')]),
            ('COMPRA', self.nota_debito, origen_c, [self.linea('ND_CARGO_COMPRA', '1', '5')]),
            ('VENTA', self.nota_credito, origen_v, [self.linea('DEVOLUCION_VENTA', '1', '20', detalle_origen=origen_v.detalles.get(linea=1).id)]),
            ('VENTA', self.nota_credito, origen_v, [self.linea('NC_VENTA_SIN_DEVOLUCION', '1', '5')]),
            ('VENTA', self.nota_debito, origen_v, [self.linea('ND_CARGO_VENTA', '1', '5')]),
        ]
        for i, (clase, tipo, origen, lineas) in enumerate(casos):
            with self.subTest(clase=clase, operacion=lineas[0]['tipo_operacion']):
                doc = self.documento_confirmado(clase, lineas, tipo=tipo, origen=origen, fecha=f'2026-01-{15 + i}')
                self.assertEqual(Documento.objects.get(pk=doc).estado, 'CONFIRMADO')

    def test_saldo_inicial_y_transferencia_por_su_modulo(self):
        si = self.client.post(reverse('saldo-inicial-list-create'), {
            'periodo': self.enero.id, 'almacen': self.almacen.id, 'producto': self.producto_2.id,
            'cantidad': '10', 'valor_pen': '100',
        }, format='json', **self.headers)
        self.assertEqual(si.status_code, 201, si.data)
        conf = self.client.post(reverse('saldo-inicial-confirmar', args=[si.data['id']]), format='json', **self.headers)
        self.assertEqual(conf.status_code, 200, conf.data)
        destino = Almacen.objects.create(empresa=self.empresa, establecimiento=self.establecimiento, codigo='ALM2', nombre='DESTINO')
        tr = self.client.post(reverse('transferencia-list-create'), {
            'almacen_origen': self.almacen.id, 'almacen_destino': destino.id, 'fecha': '2026-01-20',
            'detalles': [{'producto': self.producto_2.id, 'cantidad_base': '4'}],
        }, format='json', **self.headers)
        self.assertEqual(tr.status_code, 201, tr.data)
        conf = self.client.post(reverse('transferencia-confirmar', args=[tr.data['id']]), format='json', **self.headers)
        self.assertEqual(conf.status_code, 200, conf.data)
        self.assertEqual(self.stock(self.producto_2), Decimal('6'))
