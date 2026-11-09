"""
Bloque 16 — flujo comercial y financiero: series y correlativos, condición de pago, pagos,
cuentas por cobrar/pagar, terceros (catálogo 06, DNI/RUC), historial, productos y registro de
ventas/compras. Incluye intentos de acceso a datos de otra empresa (IDOR).
"""
import io
import threading
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.auditoria.models import Auditoria
from apps.catalogos.models import MetodoPago, TipoComprobante
from apps.documentos import finanzas
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoCuota, PagoDocumento, SerieComprobante
from apps.empresas.models import Establecimiento, Periodo
from apps.inventario.documentos_identidad import digito_verificador_ruc, es_ruc_valido
from apps.inventario.models import Almacen, Tercero
from apps.usuarios.models import Usuario, UsuarioEmpresa

D = Decimal
HOY = date.today()


def ruc(base10):
    return f'{base10}{digito_verificador_ruc(base10)}'


class FinanzasFixture(Bloque2Fixture):
    def setUp(self):
        self.crear_base()
        self.boleta = TipoComprobante.objects.create(codigo_sunat='03', descripcion='BOLETA DE VENTA')
        for codigo, desc in (('EFECTIVO', 'Efectivo'), ('TRANSFERENCIA', 'Transferencia'), ('YAPE', 'Yape')):
            MetodoPago.objects.get_or_create(codigo=codigo, defaults={'descripcion': desc})
        self.compra_confirmada('100', '10', fecha='2026-01-05')  # stock para vender

    # ---- helpers ---------------------------------------------------------------------------
    def crear_serie(self, serie='F001', tipo=None, establecimiento=None, ultimo=0, esperado=201, headers=None):
        resp = self.client.post(reverse('serie-comprobante-list-create'), {
            'serie': serie, 'tipo_comprobante': (tipo or self.factura).id,
            'establecimiento': (establecimiento or self.establecimiento).id, 'ultimo_correlativo': ultimo,
        }, format='json', **(headers or self.headers))
        self.assertEqual(resp.status_code, esperado, resp.data)
        return resp.data

    def venta(self, *, serie=None, esperado=201, cantidad='1', precio='100', tipo=None, tercero='cliente', almacen=None, **extra):
        linea = self.linea('VENTA', cantidad, precio)
        if almacen:
            linea['almacen'] = almacen.id
        data = self.payload('VENTA', [linea], tipo=tipo, tercero=self.cliente if tercero == 'cliente' else tercero)
        if tercero is None:
            data['tercero'] = None
        if serie is not None:
            data.pop('serie')
            data.pop('numero')
            data['serie_comprobante'] = serie
        data.update(extra)
        resp = self.client.post(reverse('documento-list-create'), data, format='json', **self.headers)
        self.assertEqual(resp.status_code, esperado, getattr(resp, 'data', resp))
        return resp

    def confirmar_doc(self, doc_id):
        self.revisar(doc_id)
        self.confirmar(doc_id)

    def pagar(self, doc_id, monto, esperado=201, fecha=None, metodo='EFECTIVO', headers=None, **extra):
        resp = self.client.post(reverse('pago-documento-list-create'), {
            'documento': doc_id, 'fecha': str(fecha or date(2026, 1, 20)), 'monto': str(monto),
            'metodo_pago': metodo, **extra,
        }, format='json', **(headers or self.headers))
        self.assertEqual(resp.status_code, esperado, getattr(resp, 'data', resp))
        return resp

    def detalle(self, doc_id):
        return self.client.get(reverse('documento-detail', args=[doc_id]), **self.headers).data

    def venta_credito(self, total_precio='100', vencimiento=None, cuotas=None, confirmar=True):
        extra = {'condicion_pago': 'CREDITO', 'fecha_vencimiento': str(vencimiento or HOY + timedelta(days=30))}
        if cuotas is not None:
            extra['cuotas'] = cuotas
        doc = self.venta(precio=total_precio, **extra).data
        if confirmar:
            self.confirmar_doc(doc['id'])
        return doc


class SeriesTests(FinanzasFixture, TestCase):
    def test_correlativo_inicial_y_siguiente(self):
        serie = self.crear_serie('F001')
        self.assertEqual(serie['siguiente_numero'], '00000001')
        uno = self.venta(serie=serie['id']).data
        dos = self.venta(serie=serie['id']).data
        self.assertEqual((uno['serie'], uno['numero'], dos['numero']), ('F001', '00000001', '00000002'))
        self.assertEqual(SerieComprobante.objects.get(pk=serie['id']).ultimo_correlativo, 2)
        self.assertTrue(Auditoria.objects.filter(accion='ASIGNAR_CORRELATIVO', registro_id=serie['id']).count() == 2)

    def test_continua_desde_el_ultimo_correlativo_configurado(self):
        serie = self.crear_serie('F001', ultimo=25)
        self.assertEqual(self.venta(serie=serie['id']).data['numero'], '00000026')

    def test_el_numero_enviado_por_el_frontend_se_ignora(self):
        serie = self.crear_serie('F001', ultimo=7)
        self.assertEqual(self.venta(serie=serie['id'], numero='99999').data['numero'], '00000008')

    def test_dos_series_distintas_son_independientes(self):
        a, b = self.crear_serie('F001'), self.crear_serie('F002')
        self.venta(serie=a['id'])
        self.venta(serie=a['id'])
        self.assertEqual(self.venta(serie=b['id']).data['numero'], '00000001')

    def test_dos_establecimientos(self):
        anexo = Establecimiento.objects.create(empresa=self.empresa, codigo_sunat='0001', nombre='ANEXO')
        alm_anexo = Almacen.objects.create(empresa=self.empresa, establecimiento=anexo, codigo='ALM2', nombre='ANEXO')
        serie_anexo = self.crear_serie('F002', establecimiento=anexo)
        resp = self.venta(serie=serie_anexo['id'], esperado=400)
        self.assertIn('es del establecimiento 0001', str(resp.data))
        # El anexo necesita stock propio para confirmar, pero la numeración ya funciona en borrador.
        self.assertEqual(self.venta(serie=serie_anexo['id'], almacen=alm_anexo).data['numero'], '00000001')

    def test_dos_empresas_mismo_codigo_de_serie(self):
        mia = self.crear_serie('F001')
        otra = SerieComprobante.objects.create(empresa=self.otra_empresa, tipo_comprobante=self.factura,
                                               serie='F001', ultimo_correlativo=500,
                                               establecimiento=Establecimiento.objects.create(
                                                   empresa=self.otra_empresa, codigo_sunat='0000', nombre='P'))
        self.assertEqual(self.venta(serie=mia['id']).data['numero'], '00000001')
        otra.refresh_from_db()
        self.assertEqual(otra.ultimo_correlativo, 500)

    def test_duplicados_y_formato(self):
        self.crear_serie('F001')
        self.crear_serie('F001', esperado=400)
        self.crear_serie('B001', esperado=400)  # una factura no usa serie B
        self.crear_serie('F01', esperado=400)
        self.crear_serie('B001', tipo=self.boleta)

    def test_numero_manual_en_serie_automatica_y_compra_con_serie(self):
        serie = self.crear_serie('F001')
        data = self.payload('VENTA', [self.linea('VENTA', '1', '100')], serie='F001')
        resp = self.client.post(reverse('documento-list-create'), data, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('correlativo automático', str(resp.data))
        compra = self.payload('COMPRA', [self.linea('COMPRA', '1', '10')])
        compra['serie_comprobante'] = serie['id']
        resp = self.client.post(reverse('documento-list-create'), compra, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('solo se usa en ventas', str(resp.data))

    def test_serie_usada_no_se_edita_ni_elimina_y_el_borrador_no_se_borra(self):
        serie = self.crear_serie('F001')
        doc = self.venta(serie=serie['id']).data
        url = reverse('serie-comprobante-detail', args=[serie['id']])
        self.assertEqual(self.client.patch(url, {'ultimo_correlativo': 0}, format='json', **self.headers).status_code, 400)
        self.assertEqual(self.client.patch(url, {'serie': 'F009'}, format='json', **self.headers).status_code, 400)
        self.assertEqual(self.client.delete(url, **self.headers).status_code, 400)
        self.assertEqual(self.client.patch(url, {'activo': False}, format='json', **self.headers).status_code, 200)
        self.assertEqual(self.client.delete(reverse('documento-detail', args=[doc['id']]), **self.headers).status_code, 400)
        resp = self.venta(serie=serie['id'], esperado=400)
        self.assertIn('inactiva', str(resp.data))
        self.assertTrue(Auditoria.objects.filter(entidad='SERIE_COMPROBANTE', accion='ACTUALIZAR').exists())

    def test_si_la_creacion_falla_el_correlativo_no_avanza(self):
        serie = self.crear_serie('F001')
        self.venta(serie=serie['id'], esperado=400, cantidad='-1')
        self.venta(serie=serie['id'], esperado=400, fecha_emision='2026-02-15')  # fuera del período
        self.assertEqual(SerieComprobante.objects.get(pk=serie['id']).ultimo_correlativo, 0)

    def test_idor_serie_de_otra_empresa(self):
        est_otra = Establecimiento.objects.create(empresa=self.otra_empresa, codigo_sunat='0000', nombre='P')
        otra = SerieComprobante.objects.create(empresa=self.otra_empresa, tipo_comprobante=self.factura,
                                               serie='F777', establecimiento=est_otra)
        url = reverse('serie-comprobante-detail', args=[otra.id])
        self.assertEqual(self.client.get(url, **self.headers).status_code, 404)
        self.assertEqual(self.client.patch(url, {'activo': False}, format='json', **self.headers).status_code, 404)
        self.assertEqual(self.client.delete(url, **self.headers).status_code, 404)
        self.assertNotIn(otra.id, [s['id'] for s in self.client.get(reverse('serie-comprobante-list-create'), **self.headers).data])
        resp = self.venta(serie=otra.id, esperado=400)
        self.assertIn('no pertenece a la empresa activa', str(resp.data))
        # Establecimiento de otra empresa al crear la serie.
        self.crear_serie('F888', establecimiento=est_otra, esperado=400)
        otra.refresh_from_db()
        self.assertEqual((otra.ultimo_correlativo, otra.activo), (0, True))

    def test_usuario_sin_rol_admin_no_administra_series(self):
        usuario = Usuario.objects.create(username='solo_usuario', email='u@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.empresa, rol='USUARIO')
        self.client.force_authenticate(user=usuario)
        self.crear_serie('F001', esperado=403)
        self.assertEqual(self.client.get(reverse('serie-comprobante-list-create'), **self.headers).status_code, 200)


class SeriesConcurrenciaTests(Bloque2Fixture, TransactionTestCase):
    def setUp(self):
        self.crear_base()

    def test_dos_solicitudes_no_obtienen_el_mismo_correlativo(self):
        serie = SerieComprobante.objects.create(empresa=self.empresa, tipo_comprobante=self.factura, serie='F001',
                                                establecimiento=self.establecimiento)
        numeros, errores, barrera = [], [], threading.Barrier(8)

        def tomar():
            try:
                barrera.wait()
                from django.db import transaction
                with transaction.atomic():
                    _, numero = finanzas.asignar_correlativo(
                        empresa_id=self.empresa.id, usuario_id=self.usuario.id, serie_id=serie.id,
                        tipo_comprobante=self.factura, almacen_ids={self.almacen.id})
                numeros.append(numero)
            except Exception as exc:  # pragma: no cover - se informa abajo
                errores.append(exc)
            finally:
                connection.close()

        hilos = [threading.Thread(target=tomar) for _ in range(8)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(errores, [])
        self.assertEqual(sorted(numeros), [str(i).zfill(8) for i in range(1, 9)])
        serie.refresh_from_db()
        self.assertEqual(serie.ultimo_correlativo, 8)


class CondicionPagoTests(FinanzasFixture, TestCase):
    def test_contado_por_defecto(self):
        doc = self.venta().data
        self.assertEqual((doc['condicion_pago'], doc['fecha_vencimiento'], doc['cuotas']), ('CONTADO', None, []))

    def test_credito_requiere_vencimiento_valido(self):
        resp = self.venta(esperado=400, condicion_pago='CREDITO')
        self.assertIn('fecha_vencimiento', resp.data)
        self.venta(esperado=400, condicion_pago='CREDITO', fecha_vencimiento='2026-01-01')  # antes de la emisión
        doc = self.venta(condicion_pago='CREDITO', fecha_vencimiento='2026-03-10').data
        self.assertEqual((doc['condicion_pago'], doc['fecha_vencimiento']), ('CREDITO', '2026-03-10'))
        self.venta(esperado=400, condicion_pago='CONTADO', fecha_vencimiento='2026-03-10')

    def test_credito_con_cuotas(self):
        # Total = 100 + 18 IGV = 118
        doc = self.venta(condicion_pago='CREDITO', fecha_vencimiento='2026-03-10', cuotas=[
            {'fecha_vencimiento': '2026-02-10', 'monto': '59.00'},
            {'fecha_vencimiento': '2026-03-10', 'monto': '59.00'},
        ]).data
        self.assertEqual([(c['numero'], c['monto']) for c in doc['cuotas']], [(1, '59.00000000'), (2, '59.00000000')])
        self.assertEqual(DocumentoCuota.objects.filter(documento_id=doc['id'], empresa=self.empresa).count(), 2)

    def test_suma_incorrecta_de_cuotas_y_fechas(self):
        resp = self.venta(esperado=400, condicion_pago='CREDITO', fecha_vencimiento='2026-03-10', cuotas=[
            {'fecha_vencimiento': '2026-02-10', 'monto': '50.00'},
            {'fecha_vencimiento': '2026-03-10', 'monto': '59.00'},
        ])
        self.assertIn('suma de las cuotas', str(resp.data))
        resp = self.venta(esperado=400, condicion_pago='CREDITO', fecha_vencimiento='2026-03-10', cuotas=[
            {'fecha_vencimiento': '2026-02-10', 'monto': '118.00'}])
        self.assertIn('última cuota', str(resp.data))
        self.venta(esperado=400, condicion_pago='CREDITO', fecha_vencimiento='2026-03-10', cuotas=[
            {'fecha_vencimiento': '2026-04-10', 'monto': '118.00'}])
        self.assertEqual(Documento.objects.filter(clase='VENTA').count(), 0)

    def test_nota_no_lleva_condicion_propia(self):
        venta = self.venta().data
        self.confirmar_doc(venta['id'])
        data = self.payload('VENTA', [self.linea('NC_VENTA_SIN_DEVOLUCION', '1', '5')], tipo=self.nota_credito,
                            origen=Documento.objects.get(pk=venta['id']), fecha='2026-01-12')
        data.update(condicion_pago='CREDITO', fecha_vencimiento='2026-02-12')
        resp = self.client.post(reverse('documento-list-create'), data, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)

    def test_cambio_de_condicion_auditado_y_bloqueado_con_pagos(self):
        doc = self.venta().data
        self.confirmar_doc(doc['id'])
        url = reverse('documento-condicion-pago', args=[doc['id']])
        resp = self.client.put(url, {'condicion_pago': 'CREDITO', 'fecha_vencimiento': '2026-04-01', 'motivo': 'Acuerdo'},
                               format='json', **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(Auditoria.objects.filter(accion='CAMBIAR_CONDICION_PAGO', registro_id=doc['id']).exists())
        self.pagar(doc['id'], '10')
        resp = self.client.put(url, {'condicion_pago': 'CONTADO'}, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)


class PagosTests(FinanzasFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.doc = self.venta_credito()  # 118.00

    def finanzas_doc(self):
        return self.detalle(self.doc['id'])['finanzas']

    def test_pago_total(self):
        self.pagar(self.doc['id'], '118.00')
        f = self.finanzas_doc()
        self.assertEqual((D(f['pagado']), D(f['saldo_pendiente']), f['estado_financiero']), (D('118'), D('0'), 'PAGADO'))
        # Los ceros se envían como '0.00000000' (no en notación científica '0E-8').
        self.assertEqual((f['saldo_pendiente'], f['monto_vencido'], f['total_notas_credito']), ('0.00000000',) * 3)
        cuentas = self.client.get(reverse('cuentas-por-cobrar'), {'condicion': 'TODAS', 'estado': 'PAGADO'}, **self.headers).data
        self.assertEqual(cuentas['resultados'][0]['saldo_pendiente'], '0.00000000')
        self.assertTrue(Auditoria.objects.filter(accion='REGISTRAR_PAGO').exists())

    def test_pago_parcial_y_multiples(self):
        self.pagar(self.doc['id'], '18.00')
        self.assertEqual(self.finanzas_doc()['estado_financiero'], 'PARCIAL')
        self.pagar(self.doc['id'], '50.00', metodo='YAPE', referencia='OP-123')
        self.pagar(self.doc['id'], '50.00', metodo='TRANSFERENCIA')
        f = self.finanzas_doc()
        self.assertEqual((D(f['pagado']), D(f['saldo_pendiente']), f['estado_financiero']), (D('118'), D('0'), 'PAGADO'))
        self.assertEqual(len(self.detalle(self.doc['id'])['pagos']), 3)

    def test_sobrepago_rechazado(self):
        self.pagar(self.doc['id'], '100.00')
        resp = self.pagar(self.doc['id'], '18.01', esperado=400)
        self.assertIn('supera el saldo pendiente', str(resp.data))
        self.pagar(self.doc['id'], '18.00')

    def test_documento_borrador_anulado_o_nota(self):
        borrador = self.venta().data
        self.assertIn('BORRADOR', str(self.pagar(borrador['id'], '1', esperado=400).data))
        anulado = self.venta().data
        self.confirmar_doc(anulado['id'])
        self.anular(anulado['id'])
        self.assertIn('ANULADO', str(self.pagar(anulado['id'], '1', esperado=400).data))
        nc = self.documento_confirmado('VENTA', [self.linea('NC_VENTA_SIN_DEVOLUCION', '1', '5')], tipo=self.nota_credito,
                                       origen=Documento.objects.get(pk=self.doc['id']), fecha='2026-01-12')
        self.assertIn('notas de crédito/débito', str(self.pagar(nc, '1', esperado=400).data))

    def test_validaciones_de_fecha_moneda_y_metodo(self):
        self.pagar(self.doc['id'], '1', esperado=400, fecha=HOY + timedelta(days=1))
        self.pagar(self.doc['id'], '1', esperado=400, fecha=date(2026, 1, 1))  # antes de la emisión
        self.pagar(self.doc['id'], '1', esperado=400, moneda_codigo='USD')
        self.pagar(self.doc['id'], '1', esperado=400, metodo='BITCOIN')
        self.pagar(self.doc['id'], '0', esperado=400)

    def test_reversion_y_anulacion_del_comprobante(self):
        pago = self.pagar(self.doc['id'], '50').data
        resp = self.anular(self.doc['id'], esperado=400)
        self.assertIn('Anule primero los pagos', str(resp.data))
        url = reverse('pago-documento-anular', args=[pago['id']])
        self.assertEqual(self.client.post(url, {}, format='json', **self.headers).status_code, 400)  # sin motivo
        resp = self.client.post(url, {'motivo': 'Pago duplicado'}, format='json', **self.headers)
        self.assertEqual((resp.status_code, resp.data['estado']), (200, 'ANULADO'))
        self.assertEqual(self.client.post(url, {'motivo': 'otra vez'}, format='json', **self.headers).status_code, 400)
        self.assertEqual(D(self.finanzas_doc()['saldo_pendiente']), D('118'))
        self.assertTrue(Auditoria.objects.filter(accion='ANULAR_PAGO', registro_id=pago['id']).exists())
        self.anular(self.doc['id'])
        self.assertTrue(PagoDocumento.objects.filter(pk=pago['id'], estado='ANULADO').exists())  # no se borra

    def test_idor_documento_y_pago_de_otra_empresa(self):
        otro_doc = Documento.objects.create(
            empresa=self.otra_empresa, clase='VENTA', periodo=Periodo.objects.create(
                empresa=self.otra_empresa, anio=2026, mes=1, orden=202601, fecha_inicio=date(2026, 1, 1),
                fecha_fin=date(2026, 1, 31), estado='ABIERTO'),
            ruc_emisor=self.otra_empresa.ruc, tipo_comprobante=self.factura, serie='F001', serie_normalizada='F001',
            numero='1', numero_normalizado='1', fecha_emision=date(2026, 1, 10), moneda_codigo=self.pen,
            subtotal=100, igv=18, total=118, estado='CONFIRMADO')
        self.assertIn('no pertenece a la empresa activa', str(self.pagar(otro_doc.id, '1', esperado=400).data))
        otro_pago = PagoDocumento.objects.create(empresa=self.otra_empresa, documento=otro_doc, fecha=date(2026, 1, 11),
                                                 monto=D('1'), moneda_codigo=self.pen,
                                                 metodo_pago=MetodoPago.objects.get(pk='EFECTIVO'))
        resp = self.client.post(reverse('pago-documento-anular', args=[otro_pago.id]), {'motivo': 'x'}, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        otro_pago.refresh_from_db()
        self.assertEqual(otro_pago.estado, 'VIGENTE')
        listado = self.client.get(reverse('pago-documento-list-create'), {'documento': otro_doc.id}, **self.headers).data
        self.assertEqual(listado, [])
        self.assertEqual(self.client.get(reverse('documento-detail', args=[otro_doc.id]), **self.headers).status_code, 404)
        resp = self.client.put(reverse('documento-condicion-pago', args=[otro_doc.id]),
                               {'condicion_pago': 'CREDITO', 'fecha_vencimiento': '2026-03-01'}, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        # Cuotas de otra empresa: no aparecen en ningún detalle ni listado propio.
        DocumentoCuota.objects.create(empresa=self.otra_empresa, documento=otro_doc, numero=1,
                                      fecha_vencimiento=date(2026, 2, 1), monto=D('118'))
        cuentas = self.client.get(reverse('cuentas-por-cobrar'), {'condicion': 'TODAS'}, **self.headers).data
        self.assertNotIn(otro_doc.id, [c['id'] for c in cuentas['resultados']])

    def test_usuario_sin_rol_admin_no_registra_pagos(self):
        usuario = Usuario.objects.create(username='cajero', email='c@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.empresa, rol='USUARIO')
        self.client.force_authenticate(user=usuario)
        self.pagar(self.doc['id'], '1', esperado=403)


class CuentasTests(FinanzasFixture, TestCase):
    def cuentas(self, url='cuentas-por-cobrar', **params):
        resp = self.client.get(reverse(url), params, **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        return {c['id']: c for c in resp.data['resultados']}, resp.data

    def test_pendiente_parcial_pagado_vencido(self):
        pendiente = self.venta_credito(vencimiento=HOY + timedelta(days=30))
        parcial = self.venta_credito(vencimiento=HOY + timedelta(days=30))
        pagado = self.venta_credito(vencimiento=HOY + timedelta(days=30))
        vencido = self.venta_credito(vencimiento=date(2026, 1, 25))  # ya pasó
        self.pagar(parcial['id'], '18')
        self.pagar(pagado['id'], '118')
        filas, datos = self.cuentas()
        estados = {k: v['estado_financiero'] for k, v in filas.items()}
        self.assertEqual(estados, {pendiente['id']: 'PENDIENTE', parcial['id']: 'PARCIAL',
                                   pagado['id']: 'PAGADO', vencido['id']: 'VENCIDO'})
        self.assertEqual(D(filas[parcial['id']]['saldo_pendiente']), D('100'))
        self.assertEqual(D(filas[vencido['id']]['monto_vencido']), D('118'))
        self.assertEqual(D(datos['totales']['PEN']['saldo_pendiente']), D('118') * 3 - D('18'))
        for estado, esperado in (('VENCIDO', {vencido['id']}), ('PAGADO', {pagado['id']}),
                                 ('ABIERTOS', {pendiente['id'], parcial['id'], vencido['id']})):
            self.assertEqual(set(self.cuentas(estado=estado)[0]), esperado, estado)

    def test_cuotas_vencidas_y_notas_de_credito(self):
        doc = self.venta_credito(vencimiento=HOY + timedelta(days=60), cuotas=[
            {'fecha_vencimiento': '2026-01-20', 'monto': '59.00'},
            {'fecha_vencimiento': str(HOY + timedelta(days=60)), 'monto': '59.00'},
        ])
        fila = self.cuentas()[0][doc['id']]
        self.assertEqual((fila['estado_financiero'], D(fila['monto_vencido'])), ('VENCIDO', D('59')))
        self.pagar(doc['id'], '59')
        self.assertEqual(self.cuentas()[0][doc['id']]['estado_financiero'], 'PARCIAL')
        # Una NC reduce lo que se debe (total ajustado 118 − 11.80 = 106.20).
        self.documento_confirmado('VENTA', [self.linea('NC_VENTA_SIN_DEVOLUCION', '1', '10')], tipo=self.nota_credito,
                                  origen=Documento.objects.get(pk=doc['id']), fecha='2026-01-22')
        fila = self.cuentas()[0][doc['id']]
        self.assertEqual((D(fila['total_ajustado']), D(fila['saldo_pendiente'])), (D('106.20'), D('47.20')))

    def test_filtros_contado_compras_y_tercero(self):
        contado = self.venta().data
        self.confirmar_doc(contado['id'])
        self.assertNotIn(contado['id'], self.cuentas()[0])
        self.assertIn(contado['id'], self.cuentas(condicion='TODAS')[0])
        compra = self.documento_confirmado('COMPRA', [self.linea('COMPRA', '1', '50')], fecha='2026-01-15')
        Documento.objects.filter(pk=compra).update(condicion_pago='CREDITO', fecha_vencimiento=HOY + timedelta(days=5))
        filas, datos = self.cuentas('cuentas-por-pagar')
        self.assertEqual((list(filas), datos['clase']), ([compra], 'COMPRA'))
        self.assertEqual(self.cuentas('cuentas-por-pagar', tercero=self.cliente.id)[0], {})
        self.assertEqual(self.client.get(reverse('cuentas-por-cobrar'), {'estado': 'RARO'}, **self.headers).status_code, 400)


class TercerosTests(FinanzasFixture, TestCase):
    def crear_tercero(self, tipo, numero, esperado=201, **extra):
        resp = self.client.post(reverse('tercero-list-create'), {
            'tipo_documento': tipo, 'numero_documento': numero, 'razon_social': f'T {numero}', 'es_cliente': True, **extra,
        }, format='json', **self.headers)
        self.assertEqual(resp.status_code, esperado, resp.data)
        return resp

    def test_validacion_ruc(self):
        valido = ruc('2060123456')
        self.assertTrue(es_ruc_valido(valido) and es_ruc_valido('20100070970'))
        self.crear_tercero('6', valido)
        invalido = valido[:10] + str((int(valido[10]) + 1) % 10)
        self.assertIn('dígito verificador', str(self.crear_tercero('6', invalido, 400).data))
        self.crear_tercero('6', '2060123456', 400)       # 10 dígitos
        self.crear_tercero('6', '30601234561', 400)      # prefijo inválido

    def test_validacion_dni_y_otros(self):
        self.crear_tercero('1', '45678912')
        self.assertIn('8 dígitos', str(self.crear_tercero('1', '4567891', 400).data))
        self.crear_tercero('1', '4567891A', 400)
        self.crear_tercero('7', 'AB123456')
        self.assertIn('catálogo 06', str(self.crear_tercero('RUCX', '45678912', 400).data))

    def test_alias_se_normaliza_y_no_duplica(self):
        valido = ruc('2060765432')
        resp = self.crear_tercero('RUC', valido)
        self.assertEqual(resp.data['tipo_documento'], '6')
        self.assertIn('Ya existe un tercero', str(self.crear_tercero('6', valido, 400).data))
        self.assertEqual(self.crear_tercero('DNI', '12345678').data['tipo_documento'], '1')

    def test_reglas_cliente_proveedor_y_factura(self):
        solo_cliente = Tercero.objects.create(empresa=self.empresa, tipo_documento='6', numero_documento=ruc('2061111111'),
                                              razon_social='SOLO CLIENTE', es_cliente=True)
        compra = self.payload('COMPRA', [self.linea('COMPRA', '1', '10')], tercero=solo_cliente)
        resp = self.client.post(reverse('documento-list-create'), compra, format='json', **self.headers)
        self.assertIn('no está registrado como proveedor', str(resp.data))
        resp = self.venta(esperado=400, tercero=self.proveedor)
        self.assertIn('no está registrado como cliente', str(resp.data))
        resp = self.venta(esperado=400, tercero=None)
        self.assertIn('requiere un cliente identificado con RUC', str(resp.data))
        persona = Tercero.objects.create(empresa=self.empresa, tipo_documento='1', numero_documento='45678912',
                                         razon_social='JUAN PEREZ', es_cliente=True)
        self.venta(esperado=400, tercero=persona)                     # factura con DNI
        data = self.payload('VENTA', [self.linea('VENTA', '1', '10')], tipo=self.boleta, tercero=persona, serie='B001')
        self.assertEqual(self.client.post(reverse('documento-list-create'), data, format='json', **self.headers).status_code, 201)
        data = self.payload('VENTA', [self.linea('VENTA', '1', '10')], tipo=self.boleta, serie='B001')
        data['tercero'] = None                                         # boleta a cliente varios
        self.assertEqual(self.client.post(reverse('documento-list-create'), data, format='json', **self.headers).status_code, 201)

    def test_historial_del_tercero(self):
        doc = self.venta_credito()
        self.pagar(doc['id'], '18')
        resp = self.client.get(reverse('tercero-historial', args=[self.cliente.id]), **self.headers)
        self.assertEqual(resp.status_code, 200)
        fila = next(f for f in resp.data['comprobantes'] if f['id'] == doc['id'])
        self.assertEqual((fila['condicion_pago'], D(fila['total_ajustado']), D(fila['pagado']), D(fila['saldo_pendiente']),
                          fila['estado_financiero']), ('CREDITO', D('118'), D('18'), D('100'), 'PARCIAL'))
        self.assertEqual(resp.data['clases'], ['VENTA'])
        prov = self.client.get(reverse('tercero-historial', args=[self.proveedor.id]), **self.headers).data
        self.assertEqual(prov['clases'], ['COMPRA'])
        self.assertTrue(all(f['clase'] == 'COMPRA' for f in prov['comprobantes']))
        otro = Tercero.objects.create(empresa=self.otra_empresa, tipo_documento='6', numero_documento='20666000111',
                                      razon_social='AJENO', es_cliente=True)
        self.assertEqual(self.client.get(reverse('tercero-historial', args=[otro.id]), **self.headers).status_code, 404)


class HistorialConciliacionTests(FinanzasFixture, TestCase):
    """B16-QA-001: el historial concilia como CxC (original ± notas = ajustado; ajustado − pagado = saldo)."""

    def venta_credito_exonerada(self, total):
        data = self.payload('VENTA', [self.linea('VENTA', '1', total, igv='0', afectacion_igv='EXONERADO')])
        data.update({'condicion_pago': 'CREDITO', 'fecha_vencimiento': str(HOY + timedelta(days=30))})
        doc_id = self.crear(data).data['id']
        self.confirmar_doc(doc_id)
        return doc_id

    def nota(self, origen_id, efecto, monto, gravada=False):
        operacion = 'NC_VENTA_SIN_DEVOLUCION' if efecto == 'NC' else 'ND_CARGO_VENTA'
        extra = {} if gravada else {'igv': '0', 'afectacion_igv': 'EXONERADO'}
        return self.documento_confirmado(
            'VENTA', [self.linea(operacion, '1', monto, **extra)],
            tipo=self.nota_credito if efecto == 'NC' else self.nota_debito,
            origen=Documento.objects.get(pk=origen_id), fecha='2026-01-12')

    def historial(self):
        resp = self.client.get(reverse('tercero-historial', args=[self.cliente.id]), **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data

    def comprobar(self, doc_id, original, nc, nd, ajustado, pagado, saldo):
        datos = self.historial()
        fila = next(f for f in datos['comprobantes'] if f['id'] == doc_id)
        claves = ('total_original', 'total_notas_credito', 'total_notas_debito', 'total_ajustado', 'pagado', 'saldo_pendiente')
        esperado = tuple(D(x) for x in (original, nc, nd, ajustado, pagado, saldo))
        self.assertEqual(tuple(D(fila[k]) for k in claves), esperado)
        self.assertNotIn('total', fila)  # ya no hay un "total" ambiguo
        self.assertEqual(D(fila['total_ajustado']) - D(fila['pagado']), D(fila['saldo_pendiente']))
        # Mismos valores que CxC (única fuente: finanzas.valores_financieros).
        cxc = self.client.get(reverse('cuentas-por-cobrar'), {'condicion': 'TODAS'}, **self.headers).data
        c = next(r for r in cxc['resultados'] if r['id'] == doc_id)
        for k_hist, k_cxc in zip(claves, ('total', *claves[1:])):
            self.assertEqual(fila[k_hist], c[k_cxc], k_hist)
        r = next(x for x in datos['resumen'] if x['clase'] == 'VENTA')
        self.assertEqual(D(r['total_ajustado']) - D(r['pagado']), D(r['saldo_pendiente']))
        return datos

    def test_caso1_nc(self):
        doc = self.venta_credito()['id']  # 100 + IGV = 118
        self.nota(doc, 'NC', '10', gravada=True)  # 11.80
        self.pagar(doc, '18')
        datos = self.comprobar(doc, '118', '11.80', '0', '106.20', '18', '88.20')
        nota = next(f for f in datos['comprobantes'] if f['es_nota'])
        self.assertEqual((D(nota['total_original']), nota['total_ajustado'], nota['saldo_pendiente']), (D('11.80'), None, None))

    def test_caso2_nd(self):
        doc = self.venta_credito_exonerada('100')
        self.nota(doc, 'ND', '15')
        self.pagar(doc, '30')
        self.comprobar(doc, '100', '0', '15', '115', '30', '85')

    def test_caso3_nc_y_nd(self):
        doc = self.venta_credito_exonerada('100')
        self.nota(doc, 'NC', '20')
        self.nota(doc, 'ND', '15')
        self.pagar(doc, '30')
        self.comprobar(doc, '100', '20', '15', '95', '30', '65')

    def test_caso4_notas_anuladas_no_ajustan(self):
        doc = self.venta_credito_exonerada('100')
        nc = self.nota(doc, 'NC', '20')
        nd = self.nota(doc, 'ND', '15')
        self.pagar(doc, '30')
        self.comprobar(doc, '100', '20', '15', '95', '30', '65')
        self.anular(nc)
        self.comprobar(doc, '100', '0', '15', '115', '30', '85')
        self.anular(nd)
        datos = self.comprobar(doc, '100', '0', '0', '100', '30', '70')
        anuladas = [f for f in datos['comprobantes'] if f['es_nota']]
        self.assertTrue(anuladas and all(f['estado'] == 'ANULADO' and f['total_ajustado'] is None for f in anuladas))
        r = next(x for x in datos['resumen'] if x['clase'] == 'VENTA')
        self.assertEqual((D(r['total_original']), D(r['total_ajustado']), D(r['saldo_pendiente'])), (D('100'), D('100'), D('70')))

    def test_pago_total_y_resumen(self):
        doc = self.venta_credito_exonerada('100')
        self.nota(doc, 'NC', '20')
        self.pagar(doc, '80')
        datos = self.comprobar(doc, '100', '20', '0', '80', '80', '0')
        fila = next(f for f in datos['comprobantes'] if f['id'] == doc)
        self.assertEqual((fila['estado_financiero'], fila['saldo_pendiente']), ('PAGADO', '0.00000000'))


class ProductoComercialTests(FinanzasFixture, TestCase):
    def test_precio_y_afectacion_sugeridos_no_tocan_el_costo(self):
        url = reverse('producto-detail', args=[self.producto.id])
        resp = self.client.patch(url, {'precio_venta_sugerido': '25.5', 'afectacion_igv_defecto': 'EXONERADO'},
                                 format='json', **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual((resp.data['precio_venta_sugerido'], resp.data['afectacion_igv_defecto']), ('25.50000000', 'EXONERADO'))
        self.assertEqual(self.client.patch(url, {'precio_venta_sugerido': '-1'}, format='json', **self.headers).status_code, 400)
        self.assertEqual(self.client.patch(url, {'afectacion_igv_defecto': 'OTRA'}, format='json', **self.headers).status_code, 400)
        kardex = self.client.get(reverse('kardex-report'), {'producto_id': self.producto.id}, **self.headers).data
        self.assertEqual(D(kardex['movimientos'][-1]['cpp']), D('10'))


class RegistroComercialTests(FinanzasFixture, TestCase):
    def test_registro_de_ventas_y_compras(self):
        venta = self.venta().data
        self.confirmar_doc(venta['id'])
        self.documento_confirmado('VENTA', [self.linea('NC_VENTA_SIN_DEVOLUCION', '1', '10')], tipo=self.nota_credito,
                                  origen=Documento.objects.get(pk=venta['id']), fecha='2026-01-12')
        anulada = self.venta().data
        self.confirmar_doc(anulada['id'])
        self.anular(anulada['id'])
        self.venta()  # borrador: no aparece
        resp = self.client.get(reverse('registro-ventas'), {'periodo_id': self.enero.id}, **self.headers)
        self.assertEqual(resp.status_code, 200)
        filas = resp.data['filas']
        self.assertEqual(sorted(f['estado'] for f in filas), ['ANULADO', 'CONFIRMADO', 'CONFIRMADO'])
        nc = next(f for f in filas if f['tipo_comprobante_codigo'] == '07')
        self.assertEqual((D(nc['base']), D(nc['igv']), D(nc['total'])), (D('-10'), D('-1.8'), D('-11.8')))
        self.assertEqual(D(resp.data['totales']['PEN']['total']), D('118') - D('11.8'))
        compras = self.client.get(reverse('registro-compras'), {'periodo_id': self.enero.id}, **self.headers).data
        self.assertEqual(compras['filas'][0]['tercero_razon_social'], 'PROVEEDOR B2')
        xlsx = self.client.get(reverse('registro-ventas-excel'), {'periodo_id': self.enero.id}, **self.headers)
        self.assertEqual(xlsx.status_code, 200)
        self.assertIn('Registro_Ventas_2026-01', xlsx['Content-Disposition'])
        hoja = openpyxl.load_workbook(io.BytesIO(xlsx.content)).active
        self.assertEqual(hoja['A4'].value, 'Fecha')
        otro_periodo = Periodo.objects.create(empresa=self.otra_empresa, anio=2026, mes=1, orden=202601,
                                              fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 31))
        self.assertEqual(self.client.get(reverse('registro-ventas'), {'periodo_id': otro_periodo.id}, **self.headers).status_code, 400)


class MigracionCatalogo06Tests(FinanzasFixture, TestCase):
    """
    B16-QA-002: la migración inventario 0004 normaliza alias del catálogo 06 y detecta TODAS las
    colisiones en memoria antes de escribir; ante un conflicto no modifica ningún tercero.
    """

    def setUp(self):
        super().setUp()
        import importlib
        self.mig = importlib.import_module('apps.inventario.migrations.0004_producto_comercial_tercero_catalogo06')
        with connection.cursor() as c:
            c.execute('SET CONSTRAINTS ALL IMMEDIATE')  # vacía los triggers diferidos del fixture
            c.execute('ALTER TABLE tercero DROP CONSTRAINT chk_tercero_tipo_documento')  # datos "antiguos"

    def _normalizar(self):
        from django.apps import apps as registro
        self.mig.normalizar_tipos_documento(registro, None)

    def _tercero(self, tipo, numero, empresa=None):
        return Tercero.objects.create(empresa=empresa or self.empresa, tipo_documento=tipo, numero_documento=numero,
                                      razon_social=f'T {tipo} {numero}', es_cliente=True)

    def _estado(self):
        return dict(Tercero.objects.values_list('id', 'tipo_documento'))

    def _conflicto(self, tipo_a, tipo_b, numero):
        a, b = self._tercero(tipo_a, numero), self._tercero(tipo_b, numero)
        libre = self._tercero('DNI', '40000001')  # normalizable y sin conflicto: tampoco debe cambiar
        antes = self._estado()
        with self.assertRaises(RuntimeError) as ctx:
            self._normalizar()
        mensaje = str(ctx.exception)
        self.assertIn('Duplicados lógicos', mensaje)
        self.assertIn('no se modificó ningún tercero', mensaje)
        for t, tipo in ((a, tipo_a), (b, tipo_b)):
            self.assertIn(f'tercero {t.id} (tipo {tipo!r}', mensaje)  # IDs y valores originales
        self.assertEqual(self._estado(), antes)  # caso H: nada quedó modificado
        self.assertEqual(Tercero.objects.get(pk=libre.pk).tipo_documento, 'DNI')
        self.assertEqual(Tercero.objects.filter(numero_documento=numero).count(), 2)  # no fusiona ni elimina

    def test_alias_normalizan(self):
        for valor in ('RUC', '6', '06', ' ruc ', ' 06'):
            self.assertEqual(self.mig.tipo_normalizado(valor), '6', valor)
        for valor in ('DNI', '1', '01', 'dni'):
            self.assertEqual(self.mig.tipo_normalizado(valor), '1', valor)
        for valor, codigo in (('CE', '4'), ('04', '4'), ('CARNET', '4'), ('PASAPORTE', '7'), ('07', '7'),
                              ('PAS', '7'), ('CDI', 'A'), ('00', '0'), ('0', '0'), ('A', 'A')):
            self.assertEqual(self.mig.tipo_normalizado(valor), codigo, valor)
        self.assertIsNone(self.mig.tipo_normalizado('XYZ'))

    def test_caso_a_ruc_y_6(self):
        self._conflicto('RUC', '6', ruc('2061111111'))

    def test_caso_b_ruc_y_06(self):
        self._conflicto('RUC', '06', ruc('2061111112'))

    def test_caso_c_6_y_06(self):
        self._conflicto('6', '06', ruc('2061111113'))

    def test_caso_d_dni_y_1(self):
        self._conflicto('DNI', '1', '41111111')

    def test_caso_e_dni_y_01(self):
        self._conflicto('DNI', '01', '41111112')

    def test_caso_f_sin_colision_normaliza(self):
        t = [self._tercero('RUC', ruc('2061111114')), self._tercero('06', ruc('2061111115')),
             self._tercero('DNI', '41111113'), self._tercero('01', '41111114'), self._tercero('CE', 'X12345'),
             self._tercero('6', ruc('2061111116'))]
        self._normalizar()
        self.assertEqual([Tercero.objects.get(pk=x.pk).tipo_documento for x in t], ['6', '6', '1', '1', '4', '6'])

    def test_caso_g_misma_identidad_en_otra_empresa_no_es_conflicto(self):
        numero = ruc('2061111117')
        a = self._tercero('RUC', numero)
        b = self._tercero('06', numero, empresa=self.otra_empresa)
        self._normalizar()
        self.assertEqual((Tercero.objects.get(pk=a.pk).tipo_documento, Tercero.objects.get(pk=b.pk).tipo_documento), ('6', '6'))

    def test_caso_h_tipo_desconocido_tampoco_modifica_nada(self):
        self._tercero('RUC', ruc('2061111118'))
        raro = self._tercero('XYZ', '123')
        antes = self._estado()
        with self.assertRaisesMessage(RuntimeError, f'tercero {raro.id}'):
            self._normalizar()
        self.assertEqual(self._estado(), antes)

    def test_varias_colisiones_se_listan_todas(self):
        a1, a2 = self._tercero('RUC', ruc('2061111119')), self._tercero('06', ruc('2061111119'))
        b1, b2 = self._tercero('DNI', '41111115'), self._tercero('01', '41111115')
        with self.assertRaises(RuntimeError) as ctx:
            self._normalizar()
        for t in (a1, a2, b1, b2):
            self.assertIn(f'tercero {t.id} ', str(ctx.exception))
