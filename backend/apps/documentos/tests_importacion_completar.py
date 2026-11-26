"""
Importación Excel — «Completar comprobante».

Caso real: el Excel del cliente viene por producto (BETOTAL, SUERO…). Una boleta con dos productos
aparece en los dos archivos. Si se importan por separado, el segundo archivo no crea la boleta otra
vez: le agrega solo la línea que le falta, con su movimiento de Kardex, y ese lote se puede anular
revirtiendo solo esa línea.
"""
from datetime import date
from decimal import Decimal

from rest_framework.exceptions import ValidationError

from apps.auditoria.models import Auditoria
from apps.catalogos.models import MetodoPago
from apps.documentos.importacion_kardex_confirmar import anular_lote_importacion, confirmar_importacion_kardex
from apps.documentos.models import Documento, DocumentoDetalle, ImportacionLote, PagoDocumento
from apps.documentos.tests_importacion_kardex import OPC, ImportacionKardexBase, compra, excel, venta
from apps.kardex.models import Movimiento


class CompletarBase(ImportacionKardexBase):
    con_stock = True

    def importar(self, *archivos, nombre='kardex'):
        return confirmar_importacion_kardex(
            empresa_id=self.empresa.id, usuario=self.usuario,
            archivos=[(f'{nombre}{i}.xlsx', a) for i, a in enumerate(archivos, 1)],
        )

    def anular(self, lote_id, motivo='Se subió mal'):
        return anular_lote_importacion(empresa_id=self.empresa.id, lote_id=lote_id, usuario=self.usuario, motivo=motivo)

    def boleta(self, serie='BS01', numero=500):
        return Documento.objects.get(empresa=self.empresa, serie_normalizada=serie, numero_normalizado=str(numero))

    def lineas_vigentes(self, documento):
        return list(documento.detalles.filter(revertida_en__isnull=True).order_by('linea'))

    def movimientos(self, detalle):
        return Movimiento.objects.filter(documento_detalle=detalle)

    # Boleta BS01-500 del día 5: 3 de 011004 (archivo A) y 2 de 011049 (archivo B).
    PRECIO = ('RUC/DNI', 'Precio unitario')

    def archivo_a(self, numero=500, cant=3):
        return excel([venta('011004', 5, 3, 'BS01', numero, cant, 10, ('', 15))], self.PRECIO)

    def archivo_b(self, numero=500, cant=2, cu=10, dia=5):
        return excel([
            ['011049', date(2026, 1, dia), 3, 'BS01', numero, '01 Venta', 0, 0, 0, cant, cu, cant * cu, '', 20],
            venta('011049', 7, 3, 'BS01', 900, 1, 10, ('', 20)),
        ], self.PRECIO)


class PrevisualizacionCompletarTests(CompletarBase):
    def test_muestra_completar_y_la_linea_que_agregara(self):
        lote_a = self.importar(self.archivo_a())['lote']
        datos = self.previa(self.archivo_b())
        c = self.comp(datos, 'BS01', 500)
        self.assertEqual(c['estado'], 'COMPLETAR')
        self.assertEqual(c['completa_lote'], lote_a)
        self.assertEqual([(a['codigo'], a['cantidad']) for a in c['agregar']], [('011049', '2')])
        self.assertIn('Se agregará: 011049 × 2', c['mensaje'])
        r = datos['resumen']
        self.assertEqual((r['nuevos'], r['completar'], r['lineas_a_agregar'], r['conflictos']), (1, 1, 1, 0))
        self.assertTrue(r['puede_confirmar'])
        filas = [f for f in datos['filas'] if f['comprobante'] and f['comprobante'].endswith('BS01-500')]
        self.assertEqual([f['estado'] for f in filas], ['COMPLETAR'])

    def test_misma_cantidad_y_costo_se_omite(self):
        self.importar(self.archivo_a())
        datos = self.previa(excel([venta('011004', 5, 3, 'BS01', 500, 3, 10)]))
        self.assertEqual(self.comp(datos, 'BS01', 500)['estado'], 'YA_EXISTE')
        self.assertFalse(datos['resumen']['puede_confirmar'])

    def test_mismo_producto_otra_cantidad_es_conflicto(self):
        self.importar(self.archivo_a())
        datos = self.previa(excel([venta('011004', 5, 3, 'BS01', 500, 4, 10), venta('011049', 5, 3, 'BS01', 500, 2, 10)]))
        c = self.comp(datos, 'BS01', 500)
        self.assertEqual(c['estado'], 'CONFLICTO')
        self.assertIn('otra cantidad o costo', c['mensaje'])
        self.assertIn('011004: el Excel trae 4 a 10.00 y está registrado 3 a 10.00', c['mensaje'])
        self.assertEqual(c['agregar'], [])
        self.assertFalse(datos['resumen']['puede_confirmar'])

    def test_mismo_producto_otro_costo_es_conflicto(self):
        self.importar(self.archivo_a())
        datos = self.previa(excel([venta('011004', 5, 3, 'BS01', 500, 3, 11)]))
        self.assertEqual(self.comp(datos, 'BS01', 500)['estado'], 'CONFLICTO')

    def test_cabecera_distinta_es_conflicto(self):
        self.importar(self.archivo_a())
        datos = self.previa(self.archivo_b(dia=6))
        c = self.comp(datos, 'BS01', 500)
        self.assertEqual(c['estado'], 'CONFLICTO')
        self.assertIn('La cabecera no coincide', c['mensaje'])
        self.assertIn('fecha (registrada 05/01/2026)', c['mensaje'])

    def test_con_cobro_aplicado_es_conflicto(self):
        self.importar(self.archivo_a())
        metodo, _ = MetodoPago.objects.get_or_create(codigo='EFECTIVO', defaults={'descripcion': 'Efectivo'})
        PagoDocumento.objects.create(empresa=self.empresa, documento=self.boleta(), fecha=date(2026, 1, 5),
                                     monto=Decimal('1'), moneda_codigo=self.pen, metodo_pago=metodo)
        c = self.comp(self.previa(self.archivo_b()), 'BS01', 500)
        self.assertEqual(c['estado'], 'CONFLICTO')
        self.assertIn('cobros o pagos aplicados', c['mensaje'])

    def test_periodo_cerrado_es_conflicto(self):
        self.importar(self.archivo_a())
        periodo = self.boleta().periodo
        periodo.estado = 'CERRADO'
        periodo.save(update_fields=['estado'])
        datos = self.previa(self.archivo_b())
        # El período cerrado ya lo rechaza la validación general de filas; nunca se completa.
        self.assertIn(self.comp(datos, 'BS01', 500)['estado'], ('ERROR', 'CONFLICTO'))
        self.assertFalse(datos['resumen']['puede_confirmar'])

    def test_stock_de_la_linea_a_agregar_se_simula(self):
        self.importar(self.archivo_a())
        c = self.comp(self.previa(self.archivo_b(cant=500)), 'BS01', 500)
        self.assertEqual(c['estado'], 'ERROR')
        self.assertIn('Stock insuficiente de 011049', c['mensaje'])


class ConfirmarCompletarTests(CompletarBase):
    def test_agrega_solo_la_linea_faltante_con_su_movimiento(self):
        lote_a = self.importar(self.archivo_a())['lote']
        doc = self.boleta()
        original = doc.detalles.get()
        movs_original = list(self.movimientos(original).values_list('id', flat=True))
        stock_p2 = self.stock(self.p2)

        r = self.importar(self.archivo_b())
        self.assertEqual((r['comprobantes'], r['completados'], r['lineas_agregadas']), (1, 1, 1))
        doc.refresh_from_db()
        lineas = self.lineas_vigentes(doc)
        self.assertEqual([(d.linea, d.producto.codigo_interno, d.importacion_lote_id) for d in lineas],
                         [(1, '011004', None), (2, '011049', r['lote'])])
        self.assertEqual(doc.importacion_lote_id, lote_a)
        self.assertEqual(self.movimientos(lineas[1]).count(), 1)
        self.assertEqual(list(self.movimientos(original).values_list('id', flat=True)), movs_original)
        self.assertEqual(self.stock(self.p2), stock_p2 - 2 - 1)  # la línea agregada y la boleta nueva BS01-900
        self.assertEqual(lineas[1].costo_unitario_importado, Decimal('10'))
        self.assertEqual(lineas[1].precio_unitario, Decimal('20'))
        self.assertEqual((doc.subtotal, doc.igv, doc.total), (Decimal('85'), Decimal('15.30'), Decimal('100.30')))
        audit = Auditoria.objects.get(entidad='DOCUMENTO_DETALLE', accion='COMPLETAR', registro_id=lineas[1].id)
        self.assertEqual((audit.valor_nuevo['lote'], audit.valor_nuevo['lote_original']), (r['lote'], lote_a))
        self.assertTrue(Auditoria.objects.filter(entidad='DOCUMENTO', accion='COMPLETAR', registro_id=doc.id).exists())
        lote_b = ImportacionLote.objects.get(pk=r['lote'])
        self.assertEqual(lote_b.resumen['comprobantes_completados'][0]['comprobante'], 'BS01-500')

        # Volver a subir el mismo contenido (otro archivo) no agrega nada.
        datos = self.previa(self.archivo_b())
        self.assertEqual((datos['resumen']['nuevos'], datos['resumen']['completar']), (0, 0))
        self.assertEqual(self.comp(datos, 'BS01', 500)['estado'], 'YA_EXISTE')

    def test_completa_una_compra_con_costo_e_igv(self):
        self.importar(excel([compra('011004', 3, 'F035', 1081, 10, 10)], OPC))
        stock_p2 = self.stock(self.p2)
        datos = self.previa(excel([compra('011049', 3, 'F035', 1081, 4, 7.5)], OPC))
        self.assertEqual(self.comp(datos, 'F035', 1081)['estado'], 'COMPLETAR')
        self.importar(excel([compra('011049', 3, 'F035', 1081, 4, 7.5)], OPC))
        doc = self.boleta('F035', 1081)
        nueva = doc.detalles.get(linea=2)
        self.assertEqual((nueva.precio_unitario, nueva.igv, nueva.costo_unitario_pen),
                         (Decimal('7.5'), Decimal('5.40'), Decimal('7.50000000')))
        self.assertEqual(self.stock(self.p2), stock_p2 + 4)
        self.assertEqual((doc.subtotal, doc.igv, doc.total), (Decimal('130'), Decimal('23.40'), Decimal('153.40')))

    def test_revalida_al_confirmar(self):
        self.importar(self.archivo_a())
        self.assertTrue(self.previa(self.archivo_b())['resumen']['puede_confirmar'])
        metodo, _ = MetodoPago.objects.get_or_create(codigo='EFECTIVO', defaults={'descripcion': 'Efectivo'})
        PagoDocumento.objects.create(empresa=self.empresa, documento=self.boleta(), fecha=date(2026, 1, 5),
                                     monto=Decimal('1'), moneda_codigo=self.pen, metodo_pago=metodo)
        lotes = ImportacionLote.objects.count()
        with self.assertRaisesMessage(ValidationError, 'No se puede confirmar'):
            self.importar(self.archivo_b())
        self.assertEqual(ImportacionLote.objects.count(), lotes)
        self.assertEqual(self.boleta().detalles.count(), 1)

    def test_un_error_en_la_linea_agregada_no_graba_nada(self):
        self.importar(self.archivo_a())
        from unittest import mock
        with mock.patch('apps.documentos.importacion_kardex_confirmar.comparar_con_registrado',
                        return_value={'estado': 'CONFLICTO', 'agregar': [], 'mensaje': 'cambió'}):
            with self.assertRaisesMessage(ValidationError, 'No se pudo completar BS01-500'):
                self.importar(self.archivo_b())
        self.assertEqual(self.boleta().detalles.count(), 1)
        self.assertFalse(Documento.objects.filter(serie_normalizada='BS01', numero_normalizado='900').exists())


class AnularCompletarTests(CompletarBase):
    def preparar(self):
        lote_a = self.importar(self.archivo_a())['lote']
        stock_p2 = self.stock(self.p2)
        self.totales_a = Documento.objects.filter(pk=self.boleta().pk).values_list('subtotal', 'igv', 'total').get()
        lote_b = self.importar(self.archivo_b(cu=10))['lote']
        return lote_a, lote_b, stock_p2

    def test_anular_el_lote_que_completo_revierte_solo_sus_lineas(self):
        lote_a, lote_b, stock_p2 = self.preparar()
        doc = self.boleta()
        original = doc.detalles.get(linea=1)
        agregada = doc.detalles.get(linea=2)
        movs_original = list(self.movimientos(original).values_list('id', 'cantidad_base'))
        stock_p1 = self.stock(self.p1)
        r = self.anular(lote_b)
        self.assertEqual((r['lineas_revertidas'], r['comprobantes_revertidos']), (1, ['BS01-500']))
        doc.refresh_from_db()
        agregada.refresh_from_db()
        self.assertEqual(doc.estado, 'CONFIRMADO')
        self.assertIsNotNone(agregada.revertida_en)
        self.assertEqual([d.linea for d in self.lineas_vigentes(doc)], [1])
        self.assertEqual(list(self.movimientos(original).values_list('id', 'cantidad_base')), movs_original)
        self.assertFalse(Movimiento.objects.filter(movimiento_extornado__documento_detalle=original).exists())
        self.assertEqual(Movimiento.objects.filter(movimiento_extornado__documento_detalle=agregada).count(), 1)
        self.assertEqual(self.stock(self.p2), stock_p2)
        self.assertEqual(self.stock(self.p1), stock_p1)
        self.assertEqual((doc.subtotal, doc.igv, doc.total), self.totales_a)
        self.assertEqual(self.totales_a, (Decimal('45'), Decimal('8.10'), Decimal('53.10')))
        self.assertTrue(Auditoria.objects.filter(entidad='DOCUMENTO_DETALLE', accion='REVERTIR', registro_id=agregada.id).exists())
        # Se puede volver a completar con un lote nuevo.
        datos = self.previa(self.archivo_b())
        self.assertEqual(self.comp(datos, 'BS01', 500)['estado'], 'COMPLETAR')

    def test_anular_el_lote_original_se_bloquea_mientras_haya_lineas_de_otro_lote(self):
        lote_a, lote_b, stock_p2 = self.preparar()
        with self.assertRaises(ValidationError) as ctx:
            self.anular(lote_a)
        texto = str(ctx.exception.detail)
        self.assertIn(f'El lote {lote_b} agregó líneas a comprobantes de este lote (BS01-500)', texto)
        self.assertIn(f'Anule primero el lote {lote_b}', texto)
        self.assertEqual(self.boleta().estado, 'CONFIRMADO')

        self.anular(lote_b)
        self.anular(lote_a)
        doc = self.boleta()
        self.assertEqual(doc.estado, 'ANULADO')
        agregada = doc.detalles.get(linea=2)
        # La línea revertida no se extorna dos veces al anular el comprobante.
        self.assertEqual(Movimiento.objects.filter(movimiento_extornado__documento_detalle=agregada).count(), 1)
        self.assertEqual(self.stock(self.p2), stock_p2)
        self.assertEqual(self.stock(self.p1), Decimal('100'))
