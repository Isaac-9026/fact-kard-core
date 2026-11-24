"""
Importación Excel "Entradas y salidas" (formato Kardex por producto) — paso 1: previsualización.

Casos tomados de los archivos reales del cliente (BETOTAL / PHYTEX 500): ventas con boleta y
factura sin RUC, compra con dos líneas del mismo producto, ventas a costo 0 devueltas el mismo día
con nota de crédito de otra serie, y comprobantes repartidos en varios archivos.
"""
import io
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from apps.catalogos.models import TipoComprobante
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.importacion_kardex_excel import leer_archivo, previsualizar_importacion_kardex
from apps.empresas.models import Periodo
from apps.usuarios.models import Usuario, UsuarioEmpresa

RUC_PROV = '20555000111'


def excel(filas, opcionales=()):
    """Arma un .xlsx con el mismo encabezado de dos filas del sistema del cliente."""
    wb = Workbook()
    ws = wb.active
    ws.append([None, 'COMPROBANTE', None, None, None, 'Tipo de Operación', 'ENTRADAS', None, None, 'SALIDAS', None, None, *opcionales])
    ws.append([None, 'Fecha', 'Tipo', 'Serie', 'Número', None, 'Cantidad', 'Costo Unitario', 'Costo Total',
               'Cantidad', 'Costo Unitario', 'Costo Total', *([None] * len(opcionales))])
    ws.merge_cells('B1:E1')
    ws.merge_cells('F1:F2')
    ws.merge_cells('G1:I1')
    ws.merge_cells('J1:L1')
    for fila in filas:
        ws.append(fila)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    buffer.name = 'kardex.xlsx'
    return buffer


def venta(codigo, dia, tipo, serie, numero, cant, cu, extra=()):
    return [codigo, date(2026, 1, dia), tipo, serie, numero, '01 Venta', 0, 0, 0, cant, cu, cant * cu if cu else 0, *extra]


def compra(codigo, dia, serie, numero, cant, cu, ruc=RUC_PROV):
    return [codigo, date(2026, 1, dia), 1, serie, numero, '02 Compra', cant, cu, cant * cu, 0, 0, 0, ruc]


def devolucion(codigo, dia, serie, numero, cant):
    return [codigo, date(2026, 1, dia), 7, serie, numero, '05 Devolución Recibida', cant, 0, 0, 0, 0, 0]


OPC = ('RUC/DNI',)


class ImportacionKardexBase(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        TipoComprobante.objects.get_or_create(codigo_sunat='03', defaults={'descripcion': 'BOLETA'})
        self.p1 = self.crear_producto('011004')
        self.p2 = self.crear_producto('011049')

    def previa(self, *archivos):
        return previsualizar_importacion_kardex(
            empresa_id=self.empresa.id, archivos=[(f'archivo{i}.xlsx', a) for i, a in enumerate(archivos, 1)],
        )

    def comp(self, datos, serie, numero):
        return next(c for c in datos['comprobantes'] if c['serie'] == serie and c['numero'] == str(numero))


class LecturaTests(ImportacionKardexBase):
    def test_lee_el_formato_del_cliente_con_decimales_exactos(self):
        filas = leer_archivo(excel([
            venta('011004', 4, 3, 'BS01', 42521, 0.5, 34.77655),
            [None] * 12,
            compra('011004', 11, 'F035', 1081, 20, 34.253814),
        ], OPC), 'betotal.xlsx')
        self.assertEqual(len(filas), 2)
        v, c = filas
        self.assertEqual((v.fila, v.tipo, v.serie, v.numero, v.operacion, v.naturaleza), (3, '03', 'BS01', '42521', '01', 'SALIDA'))
        self.assertEqual(v.cantidad, Decimal('0.5'))
        self.assertEqual(v.costo_unitario, Decimal('34.77655'))
        self.assertEqual((c.fila, c.clase, c.naturaleza, c.ruc), (5, 'COMPRA', 'ENTRADA', RUC_PROV))
        self.assertEqual(c.cantidad, Decimal('20'))

    def test_errores_de_fila_no_se_pierden(self):
        filas = leer_archivo(excel([
            ['011004', date(2026, 1, 2), 3, 'BS01', 1, '01 Venta', 1, 1, 1, 1, 1, 1],
            ['011004', 'mañana', 3, 'BS01', 2, '01 Venta', 0, 0, 0, 1, 1, 1],
            ['011004', date(2026, 1, 2), 3, 'BS01', 3, '09 Consumo', 0, 0, 0, 1, 1, 1],
            ['011004', date(2026, 1, 2), 'X', 'BS01', 4, '01 Venta', 0, 0, 0, 1, 1, 1],
            ['011004', date(2026, 1, 2), 3, 'BS01', 5, '02 Compra', 0, 0, 0, 1, 1, 1],
            [None, date(2026, 1, 2), 3, 'BS01', 6, '01 Venta', 0, 0, 0, 'abc', 1, 1],
        ]), 'x.xlsx')
        self.assertEqual(len(filas), 6)
        mensajes = [' '.join(f.errores) for f in filas]
        self.assertIn('entrada y de salida a la vez', mensajes[0])
        self.assertIn('Fecha inválida', mensajes[1])
        self.assertIn('Tipo de operación no soportado', mensajes[2])
        self.assertIn('Tipo de comprobante inválido', mensajes[3])
        self.assertIn('Compra sin cantidad de entrada', mensajes[4])
        self.assertIn('Falta el código', mensajes[5])
        self.assertIn('no es un número válido', mensajes[5])

    def test_archivo_sin_formato(self):
        wb = Workbook()
        wb.active.append(['Código', 'Descripción'])
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        with self.assertRaisesMessage(ValidationError, 'no tiene el formato Entradas y salidas'):
            leer_archivo(buffer, 'otro.xlsx')
        with self.assertRaisesMessage(ValidationError, 'No se pudo leer'):
            leer_archivo(io.BytesIO(b'no es excel'), 'malo.xlsx')


class PrevisualizacionTests(ImportacionKardexBase):
    def test_comprobantes_nuevos_ordenados_con_entradas_primero(self):
        datos = self.previa(excel([
            venta('011004', 4, 3, 'BS01', 42521, 0.5, 34.77655),
            venta('011004', 11, 1, 'FS01', 15799, 1, 34.6),
            compra('011004', 11, 'F035', 1081, 20, 34.253814),
        ], OPC))
        r = datos['resumen']
        self.assertEqual((r['filas'], r['comprobantes'], r['nuevos'], r['con_error']), (3, 3, 3, 0))
        self.assertTrue(r['puede_confirmar'])
        self.assertEqual([c['serie'] for c in datos['comprobantes']], ['BS01', 'F035', 'FS01'])
        factura = self.comp(datos, 'FS01', 15799)
        self.assertIn('VARIOS (importación)', ' '.join(factura['observaciones']))
        self.assertIn('Sin precio de venta', ' '.join(factura['observaciones']))

    def test_comprobante_repartido_en_dos_archivos_se_agrupa(self):
        datos = self.previa(
            excel([venta('011004', 5, 3, 'BS01', 500, 1, 10)]),
            excel([venta('011049', 5, 3, 'BS01', 500, 2, 20)]),
        )
        c = self.comp(datos, 'BS01', 500)
        self.assertEqual((c['lineas'], c['productos'], c['estado']), (2, ['011004', '011049'], 'NUEVO'))
        self.assertEqual(datos['resumen']['comprobantes'], 1)

    def test_compra_con_dos_lineas_del_mismo_producto_no_es_duplicado(self):
        datos = self.previa(excel([
            compra('011004', 24, 'F035', 8159, 10, 35.89661),
            compra('011004', 24, 'F035', 8159, 2, 35.898305),
        ], OPC))
        c = self.comp(datos, 'F035', 8159)
        self.assertEqual((c['lineas'], c['estado']), (2, 'NUEVO'))

    def test_compra_sin_ruc_es_error(self):
        datos = self.previa(excel([compra('011004', 11, 'F035', 1081, 20, 34)[:12]]))
        c = self.comp(datos, 'F035', 1081)
        self.assertEqual(c['estado'], 'ERROR')
        self.assertIn('RUC del proveedor', c['mensaje'])
        self.assertFalse(datos['resumen']['puede_confirmar'])

    def test_misma_serie_numero_de_proveedores_distintos_no_se_mezcla(self):
        datos = self.previa(excel([
            compra('011004', 5, 'F001', 123, 1, 10, ruc=RUC_PROV),
            compra('011004', 6, 'F001', 123, 1, 10, ruc='20555000222'),
        ], OPC))
        self.assertEqual(datos['resumen']['nuevos'], 2)

    def test_producto_y_periodos_invalidos_bloquean_todo_el_comprobante(self):
        datos = self.previa(excel([
            venta('011004', 6, 3, 'BS01', 700, 1, 10),
            venta('999999', 6, 3, 'BS01', 700, 1, 10),
            ['011004', date(2025, 12, 20), 3, 'BS01', 701, '01 Venta', 0, 0, 0, 1, 1, 1],
            ['011004', date(2026, 2, 3), 3, 'BS01', 702, '01 Venta', 0, 0, 0, 1, 1, 1],
        ]))
        self.assertIn('999999 no existe', self.comp(datos, 'BS01', 700)['mensaje'])
        self.assertIn('2025-12 está cerrado', self.comp(datos, 'BS01', 701)['mensaje'])
        self.assertIn('No existe el período 2026-02', self.comp(datos, 'BS01', 702)['mensaje'])
        linea_buena = datos['filas'][0]
        self.assertEqual(linea_buena['estado'], 'ERROR')
        self.assertIn('Otra línea del mismo comprobante tiene error.', linea_buena['errores'])
        self.assertEqual(datos['resumen']['filas_con_error'], 4)

    def test_mismo_comprobante_con_fechas_distintas(self):
        datos = self.previa(
            excel([venta('011004', 5, 3, 'BS01', 800, 1, 10)]),
            excel([venta('011049', 6, 3, 'BS01', 800, 1, 10)]),
        )
        self.assertIn('fechas distintas', self.comp(datos, 'BS01', 800)['mensaje'])


class DevolucionesTests(ImportacionKardexBase):
    def test_devolucion_se_empareja_con_la_venta_del_mismo_dia(self):
        datos = self.previa(excel([
            devolucion('011049', 10, 'B001', 3, 0.39),
            devolucion('011049', 10, 'B001', 5, 0.398),
            venta('011049', 10, 1, 'FS01', 16711, 0.39, 0),
            venta('011049', 10, 1, 'FS01', 16713, 0.398, 0),
        ]))
        nc3, nc5 = self.comp(datos, 'B001', 3), self.comp(datos, 'B001', 5)
        self.assertEqual(nc3['estado'], 'NUEVO')
        self.assertEqual(nc3['origen'], {'fuente': 'EXCEL', 'comprobante': 'FS01-16711', 'tipo': '01'})
        self.assertEqual(nc5['origen']['comprobante'], 'FS01-16713')
        self.assertIn('de otra serie', ' '.join(nc3['observaciones']))
        self.assertIn('Costo 0 en el Excel', ' '.join(self.comp(datos, 'FS01', 16711)['observaciones']))
        self.assertEqual(datos['comprobantes'][0]['naturaleza'], 'ENTRADA')

    def test_devolucion_sin_venta_de_origen_es_error(self):
        datos = self.previa(excel([
            venta('011049', 10, 3, 'BS01', 1, 0.5, 40),
            devolucion('011049', 9, 'B001', 9, 0.5),
        ]))
        c = self.comp(datos, 'B001', 9)
        self.assertEqual(c['estado'], 'ERROR')
        self.assertIn('Devolución sin comprobante de origen', c['mensaje'])

    def test_devolucion_con_tipo_que_no_es_nota(self):
        datos = self.previa(excel([
            ['011049', date(2026, 1, 10), 3, 'BS01', 9, '05 Devolución Recibida', 1, 0, 0, 0, 0, 0],
        ]))
        self.assertIn('nota de crédito (tipo 7)', self.comp(datos, 'BS01', 9)['mensaje'])

    def test_devolucion_se_empareja_con_venta_ya_registrada(self):
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '10', '10', producto=self.p2)], fecha='2026-01-02')
        self.documento_confirmado(
            'VENTA', [self.linea('VENTA', '2', '15', producto=self.p2)], fecha='2026-01-05', tercero=self.cliente,
            serie='F001',
        )
        datos = self.previa(excel([devolucion('011049', 8, 'B001', 20, 2)]))
        c = self.comp(datos, 'B001', 20)
        self.assertEqual(c['estado'], 'NUEVO')
        self.assertEqual(c['origen']['fuente'], 'SISTEMA')


class ExistentesTests(ImportacionKardexBase):
    def registrar_compra(self, productos):
        lineas = [self.linea('COMPRA', '10', '10', producto=p) for p in productos]
        payload = self.payload('COMPRA', lineas, fecha='2026-01-03', serie='F035')
        payload['numero'] = '1081'
        doc_id = self.crear(payload).data['id']
        self.revisar(doc_id)
        self.confirmar(doc_id)

    def test_ya_existe_se_omite_sin_sobrescribir(self):
        self.registrar_compra([self.p1])
        datos = self.previa(excel([compra('011004', 3, 'F035', 1081, 10, 10)], OPC))
        c = self.comp(datos, 'F035', 1081)
        self.assertEqual(c['estado'], 'YA_EXISTE')
        self.assertIn('se omite', c['mensaje'])
        self.assertFalse(datos['resumen']['puede_confirmar'])

    def test_comprobante_registrado_sin_un_producto_es_conflicto(self):
        self.registrar_compra([self.p1])
        datos = self.previa(
            excel([compra('011004', 3, 'F035', 1081, 10, 10)], OPC),
            excel([compra('011049', 3, 'F035', 1081, 5, 10)], OPC),
        )
        c = self.comp(datos, 'F035', 1081)
        self.assertEqual(c['estado'], 'CONFLICTO')
        self.assertIn('sin los productos 011049', c['mensaje'])
        self.assertEqual(datos['resumen']['conflictos'], 1)
        self.assertFalse(datos['resumen']['puede_confirmar'])


class EndpointTests(ImportacionKardexBase):
    url = reverse('importacion-entradas-salidas-previsualizar')

    def subir(self, *archivos, **headers):
        return self.client.post(self.url, {'archivos': list(archivos)}, format='multipart', **(headers or self.headers))

    def test_previsualiza_varios_archivos_sin_grabar(self):
        from apps.documentos.models import Documento
        a = excel([venta('011004', 5, 3, 'BS01', 500, 1, 10)])
        b = excel([venta('011049', 5, 3, 'BS01', 500, 2, 20)])
        a.name, b.name = '011004.xlsx', '011049.xlsx'
        resp = self.subir(a, b)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['resumen']['comprobantes'], 1)
        self.assertEqual({f['archivo'] for f in resp.data['filas']}, {'011004.xlsx', '011049.xlsx'})
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())

    def test_validaciones_del_archivo(self):
        malo = io.BytesIO(b'x')
        malo.name = 'datos.csv'
        self.assertEqual(self.subir(malo).status_code, 400)
        self.assertEqual(self.client.post(self.url, {}, format='multipart', **self.headers).status_code, 400)
        roto = io.BytesIO(b'no es excel')
        roto.name = 'roto.xlsx'
        resp = self.subir(roto)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('archivos', resp.data)

    def test_solo_administradores_y_empresa_activa(self):
        usuario = Usuario.objects.create(username='usuario_imp', email='u@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.empresa, rol='USUARIO')
        self.client.force_authenticate(user=usuario)
        self.assertEqual(self.subir(excel([venta('011004', 5, 3, 'BS01', 1, 1, 1)])).status_code, 403)
        self.client.force_authenticate(user=self.usuario)
        resp = self.subir(excel([venta('011004', 5, 3, 'BS01', 1, 1, 1)]), HTTP_X_EMPRESA_ID=str(self.otra_empresa.id))
        self.assertEqual(resp.status_code, 403)

    def test_productos_de_otra_empresa_no_cuentan(self):
        Periodo.objects.create(empresa=self.otra_empresa, anio=2026, mes=1, orden=202601,
                               fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 31))
        datos = previsualizar_importacion_kardex(
            empresa_id=self.otra_empresa.id, archivos=[('a.xlsx', excel([venta('011004', 5, 3, 'BS01', 1, 1, 1)]))],
        )
        self.assertIn('011004 no existe', datos['comprobantes'][0]['mensaje'])
