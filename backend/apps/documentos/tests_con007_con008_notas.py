"""
Regresión CON-007 (validaciones de notas) y CON-008 (anulación con notas).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.kardex.models import Movimiento


class NotasBase(Bloque2Fixture):
    def setUp(self):
        self.crear_base()

    def detalle(self, doc_id, linea=1):
        return DocumentoDetalle.objects.get(documento_id=doc_id, linea=linea)

    def devolucion_compra(self, compra_id, cantidad, **kwargs):
        linea = self.linea(
            'DEVOLUCION_COMPRA', cantidad, '10', detalle_origen=self.detalle(compra_id).id,
            **kwargs.pop('linea_extra', {}),
        )
        return self.payload(
            'COMPRA', [linea], tipo=self.nota_credito, origen=Documento.objects.get(pk=compra_id),
            fecha=kwargs.pop('fecha', '2026-01-15'), **kwargs,
        )

    def venta_confirmada(self, cantidad='6', fecha='2026-01-12'):
        return self.documento_confirmado('VENTA', [self.linea('VENTA', cantidad, '30')], fecha=fecha)


class NotasValidasTests(NotasBase, TestCase):
    def test_nc_compra_valida_devuelve_al_costo_de_la_compra(self):
        compra = self.compra_confirmada('10', '10')
        nc = self.crear(self.devolucion_compra(compra, '4')).data['id']
        self.revisar(nc)
        self.confirmar(nc)

        self.assertEqual(self.stock(), Decimal('6'))
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('6.00000000'))
        self.assertEqual(saldo.valor_total_pen, Decimal('60.00000000'))
        salida = self.movimientos().get(documento_detalle__documento_id=nc)
        self.assertEqual(salida.naturaleza, 'SALIDA')
        self.assertEqual(salida.valorizacion.costo_unitario_pen, Decimal('10.00000000'))

    def test_nc_venta_valida_reingresa_al_costo_de_la_venta(self):
        self.compra_confirmada('10', '10')
        venta = self.venta_confirmada('6')
        nc = self.crear(self.payload(
            'VENTA', [self.linea('DEVOLUCION_VENTA', '2', '30', detalle_origen=self.detalle(venta).id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=venta), fecha='2026-01-14',
        )).data['id']
        self.revisar(nc)
        self.confirmar(nc)

        self.assertEqual(self.stock(), Decimal('6'))
        entrada = self.movimientos().get(documento_detalle__documento_id=nc)
        self.assertEqual(entrada.naturaleza, 'ENTRADA')
        self.assertEqual(entrada.valorizacion.costo_unitario_pen, Decimal('10.00000000'))
        self.assertEqual(self.saldo().valor_total_pen, Decimal('60.00000000'))

    def test_nd_compra_ajuste_valor_aumenta_el_costo(self):
        compra = self.compra_confirmada('10', '10')
        nd = self.crear(self.payload(
            'COMPRA', [self.linea('ND_CARGO_COMPRA', '1', '20', detalle_origen=self.detalle(compra).id)],
            tipo=self.nota_debito, origen=Documento.objects.get(pk=compra), fecha='2026-01-15',
        )).data['id']
        self.revisar(nd)
        self.confirmar(nd)
        self.assertEqual(self.saldo().valor_total_pen, Decimal('120.00000000'))
        self.assertEqual(self.stock(), Decimal('10'))


class NotasOrigenInvalidoTests(NotasBase, TestCase):
    def _assert_rechazada(self, data, texto):
        antes = Documento.objects.filter(empresa=self.empresa).count()
        resp = self.crear(data, esperado=400)
        self.assertIn(texto, str(resp.data))
        self.assertEqual(Documento.objects.filter(empresa=self.empresa).count(), antes)

    def test_origen_borrador_rechazado(self):
        compra = self.crear(self.payload('COMPRA', [self.linea('COMPRA')])).data['id']
        self._assert_rechazada(self.devolucion_compra(compra, '1'), 'estado BORRADOR')

    def test_origen_anulado_rechazado(self):
        compra = self.compra_confirmada()
        self.anular(compra)
        self._assert_rechazada(self.devolucion_compra(compra, '1'), 'estado ANULADO')

    def test_origen_de_otra_empresa_rechazado(self):
        ajena = Documento.objects.create(
            empresa=self.otra_empresa, clase='COMPRA', periodo=self.enero, ruc_emisor=self.RUC_PROVEEDOR,
            tipo_comprobante=self.factura, serie='F009', serie_normalizada='F009', numero='1',
            numero_normalizado='1', fecha_emision=date(2026, 1, 5), moneda_codigo=self.pen, estado='CONFIRMADO',
        )
        data = self.payload('COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '5')], tipo=self.nota_credito)
        data['documento_origen'] = ajena.id
        self._assert_rechazada(data, 'no pertenece a la empresa activa')

    def test_tercero_distinto_rechazado(self):
        compra = self.compra_confirmada()
        self._assert_rechazada(
            self.devolucion_compra(compra, '1', tercero=self.proveedor_2), 'mismo tercero',
        )

    def test_moneda_incompatible_rechazada_con_400_y_no_500(self):
        self.crear_tc(date(2026, 1, 15), '3.75000000')
        compra = self.compra_confirmada()  # PEN
        self._assert_rechazada(self.devolucion_compra(compra, '1', moneda='USD'), 'misma moneda')

    def test_nota_sobre_otra_nota_rechazada(self):
        compra = self.compra_confirmada()
        nc = self.crear(self.devolucion_compra(compra, '1')).data['id']
        self.revisar(nc)
        self.confirmar(nc)
        data = self.payload('COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '1')], tipo=self.nota_debito,
                            origen=Documento.objects.get(pk=nc), fecha='2026-01-20')
        self._assert_rechazada(data, 'no puede ser otra nota')

    def test_nota_con_fecha_anterior_al_origen_rechazada(self):
        compra = self.compra_confirmada(fecha='2026-01-10')
        self._assert_rechazada(self.devolucion_compra(compra, '1', fecha='2026-01-05'), 'no puede ser anterior')

    def test_clase_incompatible_rechazada(self):
        self.compra_confirmada()
        venta = self.venta_confirmada('2')
        data = self.payload(
            'COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '5')], tipo=self.nota_credito,
            origen=Documento.objects.get(pk=venta), fecha='2026-01-15',
        )
        self._assert_rechazada(data, 'documento de origen es de VENTA')


class NotasDetalleOrigenTests(NotasBase, TestCase):
    def test_detalle_de_otro_documento_rechazado(self):
        compra_1 = self.compra_confirmada()
        compra_2 = self.compra_confirmada()
        data = self.devolucion_compra(compra_1, '1')
        data['detalles'][0]['detalle_origen'] = self.detalle(compra_2).id
        resp = self.crear(data, esperado=400)
        self.assertIn('no pertenece al documento de origen', str(resp.data))

    def test_producto_distinto_al_de_la_linea_origen_rechazado(self):
        compra = self.compra_confirmada()
        data = self.devolucion_compra(compra, '1')
        data['detalles'][0]['producto'] = self.producto_2.id
        data['detalles'][0]['producto_unidad'] = self.producto_2.unidades.get().id
        resp = self.crear(data, esperado=400)
        self.assertIn('no coincide con el de la línea de origen', str(resp.data))

    def test_devolucion_fisica_sin_detalle_origen_rechazada(self):
        compra = self.compra_confirmada()
        data = self.payload('COMPRA', [self.linea('DEVOLUCION_COMPRA', '1', '10')], tipo=self.nota_credito,
                            origen=Documento.objects.get(pk=compra), fecha='2026-01-15')
        resp = self.crear(data, esperado=400)
        self.assertIn('detalle_origen', str(resp.data))


class NotasCantidadAcumuladaTests(NotasBase, TestCase):
    def test_devolucion_acumulada_mayor_al_original_rechazada_al_crear(self):
        compra = self.compra_confirmada('10', '10')
        nc_1 = self.crear(self.devolucion_compra(compra, '6')).data['id']
        self.revisar(nc_1)
        self.confirmar(nc_1)

        resp = self.crear(self.devolucion_compra(compra, '5'), esperado=400)

        self.assertIn('solo quedan 4 disponibles', str(resp.data))
        self.assertEqual(self.stock(), Decimal('4'))

    def test_dos_borradores_validos_por_separado_no_superan_el_original_al_confirmar(self):
        compra = self.compra_confirmada('10', '10')
        nc_1 = self.crear(self.devolucion_compra(compra, '6')).data['id']
        nc_2 = self.crear(self.devolucion_compra(compra, '6')).data['id']  # válido: aún nada confirmado
        self.revisar(nc_1)
        self.revisar(nc_2)
        self.confirmar(nc_1)

        resp = self.confirmar(nc_2, esperado=400)

        self.assertIn('solo quedan 4 disponibles', str(resp.data))
        self.assertEqual(Documento.objects.get(pk=nc_2).estado, 'BORRADOR')
        self.assertFalse(Movimiento.objects.filter(documento_detalle__documento_id=nc_2).exists())
        self.assertEqual(self.stock(), Decimal('4'))

    def test_misma_linea_repetida_dentro_de_una_nota_se_suma(self):
        compra = self.compra_confirmada('10', '10')
        data = self.devolucion_compra(compra, '6')
        data['detalles'].append(dict(data['detalles'][0], cantidad_original='5', igv='9.00'))
        resp = self.crear(data, esperado=400)
        self.assertIn('se intenta devolver 11', str(resp.data))

    def test_nota_anulada_libera_la_cantidad(self):
        compra = self.compra_confirmada('10', '10')
        nc_1 = self.crear(self.devolucion_compra(compra, '10')).data['id']
        self.revisar(nc_1)
        self.confirmar(nc_1)
        self.anular(nc_1)
        self.crear(self.devolucion_compra(compra, '10'))  # vuelve a estar disponible


class NaturalezaIncompatibleTests(NotasBase, TestCase):
    def _assert_naturaleza_rechazada(self, data):
        resp = self.crear(data, esperado=400)
        self.assertIn('no es válida para', str(resp.data))

    def test_nc_compra_no_puede_sumar_stock(self):
        compra = self.compra_confirmada()
        data = self.payload(
            'COMPRA', [self.linea('COMPRA', '1', '10', detalle_origen=self.detalle(compra).id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=compra), fecha='2026-01-15',
        )
        self._assert_naturaleza_rechazada(data)

    def test_nc_venta_no_puede_retirar_stock(self):
        self.compra_confirmada()
        venta = self.venta_confirmada('2')
        data = self.payload(
            'VENTA', [self.linea('VENTA', '1', '30', detalle_origen=self.detalle(venta).id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=venta), fecha='2026-01-15',
        )
        self._assert_naturaleza_rechazada(data)

    def test_nd_compra_no_puede_mover_cantidades(self):
        compra = self.compra_confirmada()
        data = self.payload(
            'COMPRA', [self.linea('DEVOLUCION_COMPRA', '1', '10', detalle_origen=self.detalle(compra).id)],
            tipo=self.nota_debito, origen=Documento.objects.get(pk=compra), fecha='2026-01-15',
        )
        self._assert_naturaleza_rechazada(data)

    def test_factura_de_compra_no_admite_salida(self):
        self._assert_naturaleza_rechazada(self.payload('COMPRA', [self.linea('VENTA')]))

    def test_factura_de_venta_no_admite_entrada(self):
        self._assert_naturaleza_rechazada(self.payload('VENTA', [self.linea('COMPRA')]))

    def test_descuento_de_venta_que_afecta_kardex_rechazado(self):
        from apps.catalogos.models import TipoOperacion
        TipoOperacion.objects.create(
            codigo_interno='NC_VENTA_CON_KARDEX', descripcion='X', naturaleza='AJUSTE_VALOR',
            afecta_kardex=True, origen_requerido='DOCUMENTO',
        )
        self.op['NC_VENTA_CON_KARDEX'] = TipoOperacion.objects.get(codigo_interno='NC_VENTA_CON_KARDEX')
        self.compra_confirmada()
        venta = self.venta_confirmada('2')
        data = self.payload(
            'VENTA', [self.linea('NC_VENTA_CON_KARDEX', '1', '5')],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=venta), fecha='2026-01-15',
        )
        resp = self.crear(data, esperado=400)
        self.assertIn('no puede afectar el Kardex', str(resp.data))

    def test_descuento_de_venta_sin_kardex_permitido(self):
        self.compra_confirmada()
        venta = self.venta_confirmada('2')
        nc = self.crear(self.payload(
            'VENTA', [self.linea('NC_VENTA_SIN_DEVOLUCION', '1', '5')],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=venta), fecha='2026-01-15',
        )).data['id']
        self.revisar(nc)
        self.confirmar(nc)
        self.assertFalse(Movimiento.objects.filter(documento_detalle__documento_id=nc).exists())

    def test_confirmacion_revalida_la_matriz_si_el_borrador_fue_manipulado(self):
        compra = self.compra_confirmada()
        nc = self.crear(self.devolucion_compra(compra, '1')).data['id']
        self.revisar(nc)
        DocumentoDetalle.objects.filter(documento_id=nc).update(tipo_operacion=self.op['COMPRA'])
        resp = self.confirmar(nc, esperado=400)
        self.assertIn('no es válida para', str(resp.data))
        self.assertEqual(Documento.objects.get(pk=nc).estado, 'BORRADOR')


class AnulacionConNotasTests(NotasBase, TestCase):
    def test_documento_sin_notas_se_anula(self):
        compra = self.compra_confirmada('10', '10')
        self.anular(compra)
        self.assertEqual(Documento.objects.get(pk=compra).estado, 'ANULADO')
        self.assertEqual(self.stock(), Decimal('0'))
        self.assertEqual(self.saldo().valor_total_pen, Decimal('0E-8'))

    def test_documento_con_nota_confirmada_no_se_anula(self):
        compra = self.compra_confirmada('10', '10')
        nc = self.crear(self.devolucion_compra(compra, '4')).data['id']
        self.revisar(nc)
        self.confirmar(nc)
        movimientos_antes = self.movimientos().count()

        resp = self.anular(compra, esperado=400)

        self.assertIn('Debe anular primero las notas relacionadas', str(resp.data))
        self.assertIn('FC01-', str(resp.data))
        self.assertEqual(Documento.objects.get(pk=compra).estado, 'CONFIRMADO')
        self.assertEqual(self.movimientos().count(), movimientos_antes)
        self.assertEqual(self.stock(), Decimal('6'))

    def test_documento_ya_anulado_no_se_anula_de_nuevo(self):
        compra = self.compra_confirmada('10', '10')
        self.anular(compra)
        movimientos_antes = self.movimientos().count()

        resp = self.anular(compra, esperado=400)

        self.assertIn('ya se encuentra ANULADO', str(resp.data))
        self.assertEqual(self.movimientos().count(), movimientos_antes)
        self.assertEqual(self.stock(), Decimal('0'))

    def test_anulando_primero_la_nota_se_puede_anular_el_origen_sin_doble_reversa(self):
        compra = self.compra_confirmada('10', '10')
        nc = self.crear(self.devolucion_compra(compra, '4')).data['id']
        self.revisar(nc)
        self.confirmar(nc)
        self.anular(nc)
        self.assertEqual(self.stock(), Decimal('10'))
        self.anular(compra)
        self.assertEqual(self.stock(), Decimal('0'))
        self.assertEqual(self.saldo().cantidad_total, Decimal('0E-8'))
        self.assertEqual(self.saldo().valor_total_pen, Decimal('0E-8'))

    def test_nota_en_borrador_no_impide_anular_pero_luego_no_puede_confirmarse(self):
        compra = self.compra_confirmada('10', '10')
        nc = self.crear(self.devolucion_compra(compra, '4')).data['id']
        self.revisar(nc)
        self.anular(compra)
        resp = self.confirmar(nc, esperado=400)
        self.assertIn('estado ANULADO', str(resp.data))
        self.assertEqual(self.stock(), Decimal('0'))
