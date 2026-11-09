"""
B17A-QA-001 — código del Catálogo 07 en líneas gratuitas.

El campo canónico es documento_detalle.codigo_afectacion_igv (ya existía: lo valida
afectacion_igv.resolver_afectacion). La API ahora expone el catálogo con sus descripciones
oficiales y permite registrar el código en una línea gratuita ya guardada. Nada de esto toca
precio, IGV, totales, costo, Kardex ni movimientos.
"""
from django.test import TestCase
from django.urls import reverse

from apps.auditoria.models import Auditoria
from apps.documentos.afectacion_igv import CODIGOS_GRATUITOS, DESCRIPCIONES_CATALOGO_07
from apps.documentos.models import Documento, DocumentoDetalle
from apps.documentos.tests_b17a_tributario import TributarioFixture
from apps.kardex.models import Movimiento
from apps.usuarios.models import Usuario, UsuarioEmpresa


class Catalogo07Fixture(TributarioFixture):
    def venta_con_regalo(self, codigo=None, afectacion='GRATUITO', esperado=201, confirmar=True):
        regalo = self.linea('VENTA', '1', '0', igv='0', afectacion_igv=afectacion)
        if codigo is not None:
            regalo['codigo_afectacion_igv'] = codigo
        data = self.payload('VENTA', [self.linea('VENTA', '1', '100'), regalo])
        data.pop('serie')
        data.pop('numero')
        data['serie_comprobante'] = self.serie_f['id']
        resp = self.crear(data, esperado=esperado)
        if esperado != 201:
            return resp
        if confirmar:
            self.confirmar_doc(resp.data['id'])
        return resp.data['id']

    def linea_regalo(self, doc_id):
        return DocumentoDetalle.objects.get(documento_id=doc_id, linea=2)

    def poner_codigo(self, doc_id, detalle_id, codigo, esperado=200, headers=None):
        resp = self.client.put(reverse('documento-detalle-codigo-afectacion', args=[doc_id, detalle_id]),
                               {'codigo_afectacion_igv': codigo}, format='json', **(headers or self.headers))
        self.assertEqual(resp.status_code, esperado, getattr(resp, 'data', resp))
        return resp


class CatalogoApiTests(Catalogo07Fixture, TestCase):
    def test_catalogo_07_con_descripciones_oficiales(self):
        datos = self.client.get(reverse('afectacion-igv-catalogo'), **self.headers).data
        por_codigo = {f['codigo']: f for f in datos}
        self.assertEqual(len(datos), 18)
        self.assertEqual(por_codigo['15'], {'codigo': '15', 'descripcion': 'Gravado – Bonificaciones',
                                             'afectacion': 'GRATUITO', 'soportado': True})
        self.assertEqual(por_codigo['21']['descripcion'], 'Exonerado – Transferencia Gratuita')
        self.assertEqual((por_codigo['17']['soportado'], por_codigo['10']['afectacion']), (False, 'GRAVADO'))
        gratuitos = [f['codigo'] for f in datos if f['afectacion'] == 'GRATUITO']
        self.assertEqual(tuple(gratuitos), CODIGOS_GRATUITOS)
        self.assertEqual(CODIGOS_GRATUITOS, ('11', '12', '13', '14', '15', '16', '21', '31', '32', '33', '34', '35', '36'))
        self.assertEqual(set(DESCRIPCIONES_CATALOGO_07), set(por_codigo))


class LineaGratuitaTests(Catalogo07Fixture, TestCase):
    # Caso 1
    def test_gratuita_sin_codigo_no_preparada(self):
        doc = self.venta_con_regalo()
        r = self.validar(doc)
        self.assertError(r, 'Línea 2: operación gratuita sin código del catálogo 07 (11-16, 21 o 31-36)')

    # Caso 2
    def test_gratuita_con_codigo_lista(self):
        doc = self.venta_con_regalo('15')
        self.assertListo(self.validar(doc))
        linea = self.detalle(doc)['detalles'][1]
        self.assertEqual((linea['afectacion_igv'], linea['codigo_afectacion_igv']), ('GRATUITO', '15'))

    # Caso 3
    def test_codigo_gratuito_no_se_guarda_en_linea_gravada(self):
        resp = self.venta_con_regalo('15', afectacion='GRAVADO', esperado=400)
        self.assertIn('no coincide con el código SUNAT 15', str(resp.data))
        doc = self.emitir_factura()
        normal = DocumentoDetalle.objects.get(documento_id=doc, linea=1)
        resp = self.poner_codigo(doc, normal.id, '15', esperado=400)
        self.assertIn('solo se registra en líneas gratuitas', str(resp.data))
        normal.refresh_from_db()
        self.assertIsNone(normal.codigo_afectacion_igv)

    # Caso 4
    def test_documento_existente_registra_y_conserva_el_codigo(self):
        doc = self.venta_con_regalo()
        antes = Documento.objects.filter(pk=doc).values('subtotal', 'igv', 'total').get()
        movimientos = list(Movimiento.objects.order_by('id').values_list('id', 'cantidad_base', 'valor_ajuste_pen', 'naturaleza'))
        linea = self.linea_regalo(doc)
        self.assertEqual(self.poner_codigo(doc, linea.id, '31').data['detalles'][1]['codigo_afectacion_igv'], '31')
        self.assertEqual(self.detalle(doc)['detalles'][1]['codigo_afectacion_igv'], '31')  # al reabrir
        self.assertListo(self.validar(doc))
        self.poner_codigo(doc, linea.id, '15')
        aud = Auditoria.objects.filter(accion='CAMBIAR_CODIGO_AFECTACION', registro_id=linea.id).order_by('id')
        self.assertEqual([(a.valor_anterior['codigo_afectacion_igv'], a.valor_nuevo['codigo_afectacion_igv']) for a in aud],
                         [(None, '31'), ('31', '15')])
        # Solo información tributaria: importes y Kardex intactos.
        self.assertEqual(Documento.objects.filter(pk=doc).values('subtotal', 'igv', 'total').get(), antes)
        self.assertEqual(list(Movimiento.objects.order_by('id').values_list('id', 'cantidad_base', 'valor_ajuste_pen', 'naturaleza')), movimientos)

    # Caso 5
    def test_codigo_incompatible_rechazado(self):
        self.assertIn('no coincide', str(self.venta_con_regalo('10', esperado=400).data))
        self.assertIn('no existe en el Catálogo 07', str(self.venta_con_regalo('99', esperado=400).data))
        self.assertIn('no soportada', str(self.venta_con_regalo('17', esperado=400).data))
        doc = self.venta_con_regalo()
        linea = self.linea_regalo(doc)
        for codigo in ('10', '20', '40', '17', '99'):
            self.assertIn('no corresponde a una operación gratuita', str(self.poner_codigo(doc, linea.id, codigo, esperado=400).data))
        self.assertEqual(self.poner_codigo(doc, linea.id, '', esperado=400).status_code, 400)
        linea.refresh_from_db()
        self.assertIsNone(linea.codigo_afectacion_igv)
        # Dato incompatible heredado (gratuita con código oneroso) tampoco pasa la validación.
        DocumentoDetalle.objects.filter(pk=linea.pk).update(codigo_afectacion_igv='10')
        self.assertError(self.validar(doc), 'no es de operación gratuita')

    # Caso 6
    def test_lineas_normales_sin_cambios(self):
        doc = self.emitir_factura()
        linea = self.detalle(doc)['detalles'][0]
        self.assertEqual((linea['afectacion_igv'], linea['codigo_afectacion_igv']), ('GRAVADO', None))
        self.assertListo(self.validar(doc))
        # Mismos importes que antes del cambio: 100 + IGV 18.
        self.assertEqual(str(Documento.objects.get(pk=doc).total), '118.00000000')

    def test_permisos_y_multiempresa(self):
        doc = self.venta_con_regalo()
        linea = self.linea_regalo(doc)
        lector = Usuario.objects.create(username='lector_qa001', email='lq@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=lector, empresa=self.empresa, rol='USUARIO')
        self.client.force_authenticate(user=lector)
        self.poner_codigo(doc, linea.id, '15', esperado=403)
        self.client.force_authenticate(user=self.usuario)
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=self.otra_empresa, rol='ADMIN')
        self.poner_codigo(doc, linea.id, '15', esperado=404, headers={'HTTP_X_EMPRESA_ID': str(self.otra_empresa.id)})
        otra_linea = DocumentoDetalle.objects.filter(documento__clase='COMPRA').first()
        self.poner_codigo(doc, otra_linea.id, '15', esperado=404)  # línea de otro documento
        self.anular(doc)
        self.assertIn('anulado', str(self.poner_codigo(doc, linea.id, '15', esperado=400).data))
