"""
Regresión CON-002: una línea con afecta_kardex_aplicado=True y sin producto se
saltaba con `continue` y el documento quedaba CONFIRMADO sin movimiento.
"""
from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle


class LineaSinProductoTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def _borrador(self, lineas):
        doc_id = self.crear(self.payload('COMPRA', lineas)).data['id']
        self.revisar(doc_id)
        return doc_id

    def test_lineas_con_producto_confirman_normalmente(self):
        doc_id = self._borrador([
            self.linea('COMPRA', '10', '10'),
            self.linea('COMPRA', '5', '20', producto=self.producto_2),
        ])
        self.confirmar(doc_id)
        self.assertEqual(Documento.objects.get(pk=doc_id).estado, 'CONFIRMADO')
        self.assertEqual(self.stock(), 10)
        self.assertEqual(self.stock(self.producto_2), 5)

    def test_linea_que_afecta_kardex_sin_producto_rechaza_sin_procesar_ninguna(self):
        # La primera línea es válida; la segunda queda sin producto (p. ej. captura sin homologar).
        doc_id = self._borrador([
            self.linea('COMPRA', '10', '10'),
            self.linea('COMPRA', '5', '20', producto=self.producto_2),
        ])
        DocumentoDetalle.objects.filter(documento_id=doc_id, linea=2).update(producto=None, producto_unidad=None)

        resp = self.confirmar(doc_id, esperado=400)

        self.assertIn('Las líneas 2 afectan el Kardex', str(resp.data))
        documento = Documento.objects.get(pk=doc_id)
        self.assertEqual(documento.estado, 'BORRADOR')
        self.assertEqual(documento.estado_revision, 'REVISADO')
        self.assertIsNone(documento.confirmado_en)
        # Ni la línea válida generó movimiento: no hay confirmación parcial.
        self.assertFalse(self.movimientos().exists())
        self.assertFalse(self.movimientos(self.producto_2).exists())
        self.assertIsNone(self.saldo())
        self.assertEqual(self.stock(), 0)

    def test_linea_que_no_afecta_kardex_sin_producto_no_bloquea(self):
        from apps.catalogos.models import TipoOperacion
        servicio = TipoOperacion.objects.create(
            codigo_interno='SERVICIO_COMPRA', descripcion='SERVICIO (no inventariable)', naturaleza='ENTRADA',
            afecta_kardex=False, origen_requerido='DOCUMENTO',
        )
        doc_id = self._borrador([self.linea('COMPRA', '10', '10')])
        DocumentoDetalle.objects.create(
            documento_id=doc_id, linea=2, producto=None, almacen=self.almacen,
            tipo_operacion=servicio, afecta_kardex_aplicado=False,
            descripcion_original='FLETE (servicio)', cantidad_original=1, factor_conversion=1, cantidad_base=1,
        )
        self.confirmar(doc_id)
        self.assertEqual(Documento.objects.get(pk=doc_id).estado, 'CONFIRMADO')
        self.assertEqual(self.movimientos().count(), 1)

    def test_borrador_de_captura_sin_homologar_no_puede_confirmarse(self):
        resp = self.generar_borrador(self.subir_xml(fecha='2026-01-10'))
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['lineas_sin_homologar'], 1)
        doc_id = resp.data['documento_id']
        self.revisar(doc_id)

        resp = self.confirmar(doc_id, esperado=400)

        self.assertIn('no tienen producto asignado', str(resp.data))
        self.assertEqual(Documento.objects.get(pk=doc_id).estado, 'BORRADOR')
