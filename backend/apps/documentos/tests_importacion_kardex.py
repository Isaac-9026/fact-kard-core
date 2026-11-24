"""
Importación Excel "Entradas y salidas" (formato Kardex por producto) — paso 1: previsualización.

Casos tomados de los archivos reales del cliente (BETOTAL / PHYTEX 500): ventas con boleta y
factura sin RUC, compra con dos líneas del mismo producto, ventas a costo 0 devueltas el mismo día
con nota de crédito de otra serie, y comprobantes repartidos en varios archivos.
"""
import io
from datetime import date
from decimal import Decimal

from unittest import mock

import contextlib

from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook
from rest_framework.exceptions import ValidationError

from apps.catalogos.models import TipoComprobante
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.importacion_kardex_confirmar import anular_lote_importacion, confirmar_importacion_kardex
from apps.documentos.importacion_kardex_excel import leer_archivo, previsualizar_importacion_kardex
from apps.documentos.models import Documento, DocumentoDetalle, ImportacionLote
from apps.inventario.models import Almacen, Tercero
from apps.kardex.models import Movimiento, SaldoCppActual
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
    con_stock = True

    def setUp(self):
        self.crear_base()
        TipoComprobante.objects.get_or_create(codigo_sunat='03', defaults={'descripcion': 'BOLETA'})
        self.p1 = self.crear_producto('011004')
        self.p2 = self.crear_producto('011049')
        if self.con_stock:
            self.documento_confirmado('COMPRA', [
                self.linea('COMPRA', '100', '10', producto=self.p1), self.linea('COMPRA', '100', '10', producto=self.p2),
            ], fecha='2026-01-01')

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
    def test_devolucion_despues_de_su_venta_del_mismo_dia(self):
        datos = self.previa(excel([
            venta('011049', 10, 1, 'FS01', 16711, 0.39, 41.3),
            devolucion('011049', 10, 'B001', 3, 0.39),
        ]))
        nc = self.comp(datos, 'B001', 3)
        self.assertEqual(nc['estado'], 'NUEVO')
        self.assertEqual(nc['origen'], {'fuente': 'EXCEL', 'comprobante': 'FS01-16711', 'tipo': '01', 'aproximado': False})
        self.assertIn('de otra serie', ' '.join(nc['observaciones']))
        self.assertEqual([c['serie'] for c in datos['comprobantes']], ['FS01', 'B001'])

    def test_caso_real_devolucion_listada_antes_de_la_venta(self):
        """PHYTEX 500, 10/05/2023: las notas B001-3 y B001-5 están ANTES que las ventas FS01-16711/16713
        (a costo 0): devuelven ventas anteriores y su mercadería se vuelve a vender ese día."""
        datos = self.previa(excel([
            venta('011049', 2, 3, 'BS01', 100, 1, 41.3),
            devolucion('011049', 10, 'B001', 3, 0.39),
            devolucion('011049', 10, 'B001', 5, 0.398),
            venta('011049', 10, 1, 'FS01', 16711, 0.39, 0),
            venta('011049', 10, 1, 'FS01', 16713, 0.398, 0),
        ]))
        nc3, nc5 = self.comp(datos, 'B001', 3), self.comp(datos, 'B001', 5)
        self.assertEqual((nc3['estado'], nc5['estado']), ('NUEVO', 'NUEVO'))
        self.assertEqual(nc3['origen']['comprobante'], 'BS01-100')
        self.assertTrue(nc3['origen']['aproximado'])
        self.assertIn('Origen aproximado', ' '.join(nc3['observaciones']))
        self.assertIn('Costo 0 en el Excel', ' '.join(self.comp(datos, 'FS01', 16711)['observaciones']))
        self.assertEqual([c['serie'] for c in datos['comprobantes']], ['BS01', 'B001', 'B001', 'FS01', 'FS01'])

    def test_devolucion_que_supera_lo_vendido_no_se_empareja(self):
        datos = self.previa(excel([
            venta('011049', 2, 3, 'BS01', 100, 0.5, 41.3),
            devolucion('011049', 10, 'B001', 3, 0.4),
            devolucion('011049', 10, 'B001', 5, 0.4),
        ]))
        self.assertEqual(self.comp(datos, 'B001', 3)['estado'], 'NUEVO')
        self.assertEqual(self.comp(datos, 'B001', 5)['estado'], 'ERROR')

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
        a = excel([venta('011004', 5, 3, 'BS01', 500, 1, 10)])
        b = excel([venta('011049', 5, 3, 'BS01', 500, 2, 20)])
        a.name, b.name = '011004.xlsx', '011049.xlsx'
        antes = Documento.objects.count()
        resp = self.subir(a, b)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['resumen']['comprobantes'], 1)
        self.assertEqual({f['archivo'] for f in resp.data['filas']}, {'011004.xlsx', '011049.xlsx'})
        self.assertEqual(Documento.objects.count(), antes)

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


class ConfirmarTests(ImportacionKardexBase):
    """Paso 2: grabar por el flujo normal crear → revisar → confirmar, todo o nada, en un lote."""
    con_stock = False

    def archivo_completo(self):
        return excel([
            compra('011004', 3, 'F035', 1081, 20, 10),
            venta('011004', 5, 3, 'BS01', 42521, 5, 10.5, ('',)),
            venta('011004', 6, 1, 'FS01', 15799, 2, 10.2, ('',)),
            devolucion('011004', 6, 'B001', 3, 2) + [''],
        ], OPC)

    def importar(self, *archivos, **kwargs):
        return confirmar_importacion_kardex(
            empresa_id=self.empresa.id, usuario=self.usuario,
            archivos=[(f'archivo{i}.xlsx', a) for i, a in enumerate(archivos, 1)], **kwargs,
        )

    def test_graba_compras_ventas_y_devolucion_en_un_lote(self):
        r = self.importar(self.archivo_completo())
        self.assertEqual(r['comprobantes'], 4)
        lote = ImportacionLote.objects.get(pk=r['lote'])
        self.assertEqual((lote.estado, lote.formato, lote.almacen_id), ('CONFIRMADO', 'ENTRADAS_SALIDAS', self.almacen.id))
        self.assertEqual(lote.archivos.count(), 1)
        docs = {d.serie_normalizada: d for d in Documento.objects.filter(importacion_lote=lote)}
        self.assertEqual(set(docs), {'F035', 'BS01', 'FS01', 'B001'})
        for d in docs.values():
            self.assertEqual((d.estado, d.estado_revision, d.origen_captura), ('CONFIRMADO', 'REVISADO', 'IMPORTACION'))
        self.assertEqual(docs['F035'].tercero, self.proveedor)
        self.assertIsNone(docs['BS01'].tercero)
        self.assertEqual(docs['FS01'].tercero.razon_social, 'VARIOS (IMPORTACIÓN)')
        nota = docs['B001']
        self.assertEqual(nota.documento_origen, docs['FS01'])
        self.assertEqual(nota.tercero, docs['FS01'].tercero)
        linea = nota.detalles.get()
        self.assertEqual(linea.detalle_origen, docs['FS01'].detalles.get())
        compra_linea = docs['F035'].detalles.get()
        self.assertEqual(compra_linea.costo_unitario_importado, Decimal('10'))
        self.assertEqual(compra_linea.precio_unitario, Decimal('10'))
        self.assertEqual(compra_linea.igv, Decimal('36.00'))
        self.assertEqual(self.stock(self.p1), Decimal('15'))

    def test_stock_insuficiente_se_ve_en_la_previsualizacion(self):
        archivo = lambda: excel([
            compra('011004', 3, 'F035', 1081, 2, 10),
            venta('011004', 5, 3, 'BS01', 1, 1, 10, ('',)),
            venta('011004', 6, 3, 'BS01', 2, 5, 10, ('',)),
        ], OPC)
        datos = self.previa(archivo())
        c = self.comp(datos, 'BS01', 2)
        self.assertEqual(c['estado'], 'ERROR')
        self.assertIn('Stock insuficiente de 011004: hay 1 y sale 5', c['mensaje'])
        self.assertEqual(self.comp(datos, 'BS01', 1)['estado'], 'NUEVO')
        with self.assertRaisesMessage(ValidationError, 'No se puede confirmar'):
            self.importar(archivo())
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())
        self.assertFalse(ImportacionLote.objects.exists())

    def test_stock_cuenta_movimientos_ya_registrados(self):
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '3', '10', producto=self.p1)], fecha='2026-01-04')
        datos = self.previa(excel([
            venta('011004', 5, 3, 'BS01', 1, 2, 10, ('',)),
            venta('011004', 6, 3, 'BS01', 2, 2, 10, ('',)),
        ], OPC))
        self.assertEqual(self.comp(datos, 'BS01', 1)['estado'], 'NUEVO')
        self.assertIn('hay 1 y sale 2', self.comp(datos, 'BS01', 2)['mensaje'])

    def test_falla_inesperada_tambien_revierte(self):
        with mock.patch('apps.documentos.importacion_kardex_confirmar.confirmar_documento_validacion',
                        side_effect=[None, ValidationError({'estado': 'falla simulada'})]):
            with self.assertRaisesMessage(ValidationError, 'falla simulada'):
                self.importar(self.archivo_completo())
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())

    def test_no_confirma_con_errores_y_el_proveedor_se_elige_en_pantalla(self):
        sin_ruc = [compra('011004', 3, 'F035', 1081, 20, 10)[:12]]
        with self.assertRaisesMessage(ValidationError, 'No se puede confirmar'):
            self.importar(excel(sin_ruc))
        datos = self.previa(excel(sin_ruc))
        clave = datos['comprobantes'][0]['clave_proveedor']
        self.assertEqual(clave, '01-F035-1081-2026-01-03')
        self.assertEqual(datos['resumen']['requieren_proveedor'], 1)
        r = self.importar(excel(sin_ruc), proveedores={clave: '20555000222'})
        doc = Documento.objects.get(importacion_lote_id=r['lote'])
        self.assertEqual((doc.tercero, doc.ruc_emisor), (self.proveedor_2, '20555000222'))
        with self.assertRaisesMessage(ValidationError, 'RUC inválido'):
            self.previa(excel(sin_ruc)) if False else previsualizar_importacion_kardex(
                empresa_id=self.empresa.id, archivos=[('a.xlsx', excel(sin_ruc))], proveedores={clave: '123'},
            )

    def test_ruc_distinto_en_la_misma_compra_se_bloquea(self):
        datos = self.previa(
            excel([compra('011004', 3, 'F035', 1081, 20, 10, ruc=RUC_PROV)], OPC),
            excel([compra('011049', 3, 'F035', 1081, 5, 10, ruc='20555000112')], OPC),
        )
        self.assertEqual(datos['resumen']['con_error'], 2)
        self.assertIn('RUC distintos', datos['comprobantes'][0]['mensaje'])

    def test_registra_clientes_y_proveedores_nuevos(self):
        archivo = excel([
            compra('011004', 3, 'F099', 1, 10, 10, ruc='20777000111') + ['NUEVO PROVEEDOR SAC'],
            venta('011004', 4, 1, 'FS01', 9, 1, 10, ('20666000111', '')),
            venta('011004', 4, 3, 'BS01', 9, 1, 10, ('44556677', 'JUAN PEREZ')),
        ], ('RUC/DNI', 'Razón social'))
        previa = self.previa(archivo)
        self.assertIn('Se registrará el proveedor 20777000111.', self.comp(previa, 'F099', 1)['observaciones'])
        self.importar(archivo)
        nuevo = Tercero.objects.get(empresa=self.empresa, numero_documento='20777000111')
        self.assertEqual((nuevo.razon_social, nuevo.es_proveedor, nuevo.tipo_documento), ('NUEVO PROVEEDOR SAC', True, '6'))
        self.assertEqual(Documento.objects.get(serie_normalizada='FS01').tercero, self.cliente)
        dni = Tercero.objects.get(empresa=self.empresa, numero_documento='44556677')
        self.assertEqual((dni.tipo_documento, dni.es_cliente, dni.razon_social), ('1', True, 'JUAN PEREZ'))

    def test_el_mismo_archivo_no_se_importa_dos_veces(self):
        archivo = self.archivo_completo()
        r = self.importar(archivo)
        with self.assertRaisesMessage(ValidationError, f'(lote {r["lote"]})'):
            self.importar(archivo)

    def test_ya_existentes_se_omiten_y_lo_nuevo_se_graba(self):
        self.importar(excel([compra('011004', 3, 'F035', 1081, 20, 10)], OPC))
        r = self.importar(excel([
            compra('011004', 3, 'F035', 1081, 20, 10),
            venta('011004', 5, 3, 'BS01', 1, 1, 10, ('',)),
        ], OPC))
        self.assertEqual((r['comprobantes'], r['omitidos']), (1, 1))

    def test_almacen_obligatorio_si_hay_varios(self):
        otro = Almacen.objects.create(empresa=self.empresa, establecimiento=self.establecimiento, codigo='AL2', nombre='DOS')
        with self.assertRaisesMessage(ValidationError, 'Elija el almacén'):
            self.importar(self.archivo_completo())
        r = self.importar(self.archivo_completo(), almacen_id=otro.id)
        self.assertEqual(ImportacionLote.objects.get(pk=r['lote']).almacen, otro)
        self.assertTrue(DocumentoDetalle.objects.filter(documento__importacion_lote_id=r['lote'], almacen=otro).exists())

    def test_la_api_no_puede_crear_comprobantes_importados(self):
        datos = self.payload('VENTA', [self.linea('VENTA', '1', '10')], tercero=self.cliente)
        datos['origen_captura'] = 'IMPORTACION'
        resp = self.crear(datos, esperado=400)
        self.assertIn('origen_captura', resp.data)

    def test_endpoint_confirmar(self):
        url = reverse('importacion-entradas-salidas-confirmar')
        sin_ruc = excel([compra('011004', 3, 'F035', 1081, 20, 10)[:12]])
        sin_ruc.name = 'compras.xlsx'
        resp = self.client.post(url, {
            'archivos': [sin_ruc], 'almacen': self.almacen.id,
            'proveedores': '{"01-F035-1081-2026-01-03": "20555000111"}',
        }, format='multipart', **self.headers)
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['comprobantes'], 1)
        self.assertIn('segundos', resp.data)
        malo = excel([compra('011004', 4, 'F035', 2, 1, 1)[:12]])
        malo.name = 'b.xlsx'
        resp = self.client.post(url, {'archivos': [malo], 'proveedores': 'no-json'}, format='multipart', **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('proveedores', resp.data)

    def test_limite_de_comprobantes_por_lote(self):
        with mock.patch('apps.documentos.importacion_kardex_excel.MAX_COMPROBANTES_LOTE', 2):
            datos = self.previa(self.archivo_completo())
            self.assertTrue(datos['resumen']['excede_limite'])
            self.assertFalse(datos['resumen']['puede_confirmar'])
            with self.assertRaisesMessage(ValidationError, 'Divídalo por meses'):
                self.importar(self.archivo_completo())
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())


class AnularLoteTests(ImportacionKardexBase):
    """Paso 2b: el lote se anula completo o nada, de lo más reciente a lo más antiguo."""
    con_stock = False

    def archivo(self):
        return excel([
            compra('011004', 3, 'F035', 1081, 20, 10),
            venta('011004', 5, 3, 'BS01', 42521, 5, 10.5, ('',)),
            venta('011004', 6, 1, 'FS01', 15799, 2, 10.2, ('',)),
            devolucion('011004', 6, 'B001', 3, 2) + [''],
        ], OPC)

    def importar(self, archivo=None):
        return confirmar_importacion_kardex(
            empresa_id=self.empresa.id, usuario=self.usuario, archivos=[('kardex.xlsx', archivo or self.archivo())],
        )['lote']

    def anular(self, lote_id, motivo='Error de almacén'):
        return anular_lote_importacion(empresa_id=self.empresa.id, lote_id=lote_id, usuario=self.usuario, motivo=motivo)

    def test_anula_todo_y_revierte_el_kardex(self):
        lote_id = self.importar()
        self.assertEqual(self.stock(self.p1), Decimal('15'))
        r = self.anular(lote_id)
        self.assertEqual(r['comprobantes_anulados'], 4)
        lote = ImportacionLote.objects.get(pk=lote_id)
        self.assertEqual((lote.estado, lote.anulado_por, lote.motivo_anulacion), ('ANULADO', self.usuario, 'Error de almacén'))
        self.assertEqual(set(Documento.objects.filter(importacion_lote=lote).values_list('estado', flat=True)), {'ANULADO'})
        self.assertEqual(self.stock(self.p1), Decimal('0'))
        nota = Documento.objects.get(importacion_lote=lote, serie_normalizada='B001')
        self.assertEqual((nota.numero, nota.numero_normalizado), ('3', f'3~A{lote_id}'))

    def test_despues_de_anular_se_puede_volver_a_importar_el_mismo_archivo(self):
        lote_id = self.importar()
        self.anular(lote_id)
        datos = self.previa(self.archivo())
        self.assertEqual((datos['resumen']['nuevos'], datos['resumen']['conflictos']), (4, 0))
        nuevo = self.importar()
        self.assertNotEqual(nuevo, lote_id)
        self.assertEqual(self.stock(self.p1), Decimal('15'))
        self.assertEqual(Documento.objects.filter(serie_normalizada='F035', numero='1081').count(), 2)

    def test_no_anula_nada_si_un_comprobante_esta_en_periodo_cerrado(self):
        lote_id = self.importar()
        self.enero.estado = 'CERRADO'
        self.enero.save(update_fields=['estado'])
        with self.assertRaisesMessage(ValidationError, 'períodos cerrados (2026-01)'):
            self.anular(lote_id)
        self.assertEqual(ImportacionLote.objects.get(pk=lote_id).estado, 'CONFIRMADO')
        self.assertFalse(Documento.objects.filter(importacion_lote_id=lote_id, estado='ANULADO').exists())

    def test_no_anula_si_hay_notas_fuera_del_lote(self):
        lote_id = self.importar()
        venta_doc = Documento.objects.get(importacion_lote_id=lote_id, serie_normalizada='BS01')
        detalle = venta_doc.detalles.get()
        datos = self.payload(
            'VENTA', [self.linea('DEVOLUCION_VENTA', '1', '10.5', producto=self.p1, detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=venta_doc, fecha='2026-01-07', serie='BC01',
        )
        datos['tercero'] = None
        nota_id = self.crear(datos).data['id']
        self.revisar(nota_id)
        Documento.objects.filter(pk=nota_id).update(estado='CONFIRMADO')
        with self.assertRaisesMessage(ValidationError, 'notas fuera del lote'):
            self.anular(lote_id)
        self.assertEqual(ImportacionLote.objects.get(pk=lote_id).estado, 'CONFIRMADO')

    def test_si_una_anulacion_falla_no_se_anula_ninguno(self):
        lote_id = self.importar()
        self.documento_confirmado('VENTA', [self.linea('VENTA', '15', '12', producto=self.p1)],
                                  fecha='2026-01-20', tercero=self.cliente, serie='F001')
        with self.assertRaisesMessage(ValidationError, 'No se anuló nada'):
            self.anular(lote_id)
        self.assertFalse(Documento.objects.filter(importacion_lote_id=lote_id, estado='ANULADO').exists())
        self.assertEqual(ImportacionLote.objects.get(pk=lote_id).estado, 'CONFIRMADO')

    def test_validaciones(self):
        lote_id = self.importar()
        with self.assertRaisesMessage(ValidationError, 'motivo'):
            self.anular(lote_id, motivo='  ')
        self.anular(lote_id)
        with self.assertRaisesMessage(ValidationError, 'ya está anulado'):
            self.anular(lote_id)
        with self.assertRaisesMessage(ValidationError, 'no pertenece'):
            anular_lote_importacion(empresa_id=self.otra_empresa.id, lote_id=lote_id, usuario=self.usuario, motivo='otro motivo')

    def test_numero_anulado_a_mano_es_conflicto_en_la_previsualizacion(self):
        doc_id = self.documento_confirmado('COMPRA', [self.linea('COMPRA', '1', '10', producto=self.p1)],
                                           fecha='2026-01-02', serie='F035')
        Documento.objects.filter(pk=doc_id).update(numero='1081', numero_normalizado='1081', estado='ANULADO')
        datos = self.previa(excel([compra('011004', 3, 'F035', 1081, 20, 10)], OPC))
        c = self.comp(datos, 'F035', 1081)
        self.assertEqual(c['estado'], 'CONFLICTO')
        self.assertIn('ANULADO', c['mensaje'])

    def test_endpoints_lista_y_anular_con_password(self):
        lote_id = self.importar()
        lista = self.client.get(reverse('importacion-lotes'), **self.headers)
        self.assertEqual(lista.status_code, 200)
        self.assertEqual((lista.data[0]['id'], lista.data[0]['comprobantes'], lista.data[0]['archivos']), (lote_id, 4, ['kardex.xlsx']))
        url = reverse('importacion-lote-anular', args=[lote_id])
        sin_pass = self.client.post(url, {'motivo': 'Error de almacén'}, format='json', **self.headers)
        self.assertIn(sin_pass.status_code, (400, 403))
        mala = self.client.post(url, {'motivo': 'Error de almacén', 'password_confirmacion': 'otra'}, format='json', **self.headers)
        self.assertIn(mala.status_code, (400, 403))
        ok = self.client.post(url, {'motivo': 'Error de almacén', 'password_confirmacion': self.PASSWORD_PRUEBAS},
                              format='json', **self.headers)
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(ok.data['estado'], 'ANULADO')
        usuario = Usuario.objects.create(username='usuario_lote', email='l@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.empresa, rol='USUARIO')
        self.client.force_authenticate(user=usuario)
        self.assertEqual(self.client.post(url, {'motivo': 'x' * 10}, format='json', **self.headers).status_code, 403)


class ParidadModoLoteTests(ImportacionKardexBase):
    """Importar y anular en modo lote da el mismo Kardex que hacerlo comprobante por comprobante."""
    con_stock = False

    def foto(self):
        saldo = SaldoCppActual.objects.get(empresa=self.empresa, producto=self.p1)
        return (saldo.cantidad_total, saldo.valor_total_pen, saldo.cpp_pen, self.stock(self.p1), [
            (m.fecha_movimiento, m.naturaleza, m.cantidad_base, m.valorizacion.costo_unitario_pen,
             m.valorizacion.saldo_cantidad_empresa, m.valorizacion.saldo_valor_empresa)
            for m in Movimiento.objects.filter(empresa=self.empresa, producto=self.p1, generado_por_motor=False)
            .select_related('valorizacion').order_by('fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')
        ])

    def flujo(self):
        archivo = excel([
            compra('011004', 3, 'F035', 1081, 20, 10),
            venta('011004', 5, 3, 'BS01', 42521, 5, 10.5, ('',)),
            venta('011004', 6, 1, 'FS01', 15799, 2, 10.2, ('',)),
            devolucion('011004', 6, 'B001', 3, 2) + [''],
            compra('011004', 8, 'F035', 1090, 6, 13),
        ], OPC)
        lote = confirmar_importacion_kardex(empresa_id=self.empresa.id, usuario=self.usuario, archivos=[('a.xlsx', archivo)])['lote']
        importado = self.foto()
        anular_lote_importacion(empresa_id=self.empresa.id, lote_id=lote, usuario=self.usuario, motivo='paridad')
        return importado, self.foto()

    def test_misma_historia_con_movimientos_posteriores(self):
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '10', '12', producto=self.p1)], fecha='2026-01-20')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '20', producto=self.p1)], fecha='2026-01-25',
                                  tercero=self.cliente, serie='F001')
        try:
            with transaction.atomic():
                with mock.patch('apps.documentos.importacion_kardex_confirmar.modo_lote_kardex',
                                lambda **kw: contextlib.nullcontext()):
                    uno_a_uno = self.flujo()
                raise RuntimeError('deshacer')
        except RuntimeError:
            pass
        en_lote = self.flujo()
        self.assertEqual(en_lote, uno_a_uno)
        self.assertEqual(en_lote[0][0], Decimal('27'))
        self.assertEqual(en_lote[1][0], Decimal('6'))
