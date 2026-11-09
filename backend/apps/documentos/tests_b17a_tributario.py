"""
Bloque 17A — preparación tributaria (sin XML, firma, envío ni CDR).

Datos fiscales del emisor y del establecimiento, catálogos 09/10 (motivos de NC/ND), reglas
tributarias previas (factura, boleta, NC, ND) y el estado derivado LISTO_PARA_EMISION /
NO_PREPARADO del endpoint de solo lectura `validacion-electronica`.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.auditoria.models import Auditoria
from apps.catalogos.models import UnidadMedida
from apps.documentos import reglas_tributarias as rt
from apps.documentos.models import Documento, DocumentoDetalle
try:
    from apps.emision_electronica.pruebas_coherencia import fijar_estado_sunat
except ImportError:
    def fijar_estado_sunat(doc, estado='ACEPTADO'):
        pass
from apps.documentos.tests_b16_finanzas import FinanzasFixture, ruc
from apps.empresas.models import Establecimiento, Periodo
from apps.inventario.models import Tercero
from apps.kardex.models import Movimiento
from apps.usuarios.models import Usuario, UsuarioEmpresa

DATOS_FISCALES = {
    'direccion': 'AV. LOS PINOS 123', 'ubigeo': '150101', 'departamento': 'LIMA', 'provincia': 'LIMA',
    'distrito': 'LIMA', 'codigo_pais': 'PE', 'nombre_comercial': 'B2 COMERCIAL',
}


class TributarioFixture(FinanzasFixture):
    def setUp(self):
        super().setUp()
        # Emisor con RUC válido (dígito verificador) y datos fiscales completos.
        self.empresa.ruc = ruc('2010010010')
        for campo, valor in DATOS_FISCALES.items():
            setattr(self.empresa, campo, valor)
        self.empresa.save()
        self.cliente.numero_documento = ruc('2066600011')
        self.cliente.save()
        self.serie_f = self.crear_serie('F001')
        self.serie_b = self.crear_serie('B001', tipo=self.boleta)
        self.serie_fc = self.crear_serie('FC01', tipo=self.nota_credito)
        self.serie_fd = self.crear_serie('FD01', tipo=self.nota_debito)
        self.serie_bc = self.crear_serie('BC01', tipo=self.nota_credito)

    # ---- helpers ---------------------------------------------------------------------------
    def validar(self, doc_id, headers=None, esperado=200):
        resp = self.client.get(reverse('documento-validacion-electronica', args=[doc_id]), **(headers or self.headers))
        self.assertEqual(resp.status_code, esperado, getattr(resp, 'data', resp))
        return resp.data

    def assertError(self, resultado, fragmento):
        self.assertFalse(resultado['listo'], resultado)
        self.assertEqual(resultado['estado'], rt.NO_PREPARADO)
        self.assertTrue(any(fragmento in e for e in resultado['errores']), (fragmento, resultado['errores']))

    def assertListo(self, resultado):
        self.assertEqual((resultado['listo'], resultado['estado'], resultado['errores']), (True, rt.LISTO_PARA_EMISION, []))

    def emitir_factura(self, confirmar=True, **kw):
        doc = self.venta(serie=self.serie_f['id'], **kw).data
        if confirmar:
            self.confirmar_doc(doc['id'])
        return doc['id']

    def emitir_boleta(self, tercero=None, cantidad='1', serie=None, confirmar=True, **kw):
        if serie is None:
            serie = self.serie_b['id']
        if isinstance(serie, str):  # serie manual
            data = self.payload('VENTA', [self.linea('VENTA', cantidad, '100')], tipo=self.boleta, serie=serie,
                                tercero=tercero)
            if tercero is None:
                data['tercero'] = None
            doc_id = self.crear(data).data['id']
        else:
            doc_id = self.venta(serie=serie, tipo=self.boleta, tercero=tercero, cantidad=cantidad, **kw).data['id']
        if confirmar:
            self.confirmar_doc(doc_id)
        return doc_id

    def nota(self, origen_id, *, tipo='NC', motivo=None, serie=None, monto='10', esperado=201, confirmar=True):
        es_nc = tipo == 'NC'
        operacion = 'NC_VENTA_SIN_DEVOLUCION' if es_nc else 'ND_CARGO_VENTA'
        data = self.payload('VENTA', [self.linea(operacion, '1', monto)],
                            tipo=self.nota_credito if es_nc else self.nota_debito,
                            origen=Documento.objects.get(pk=origen_id), fecha='2026-01-15')
        data.pop('serie')
        data.pop('numero')
        data['serie_comprobante'] = (serie or (self.serie_fc if es_nc else self.serie_fd))['id']
        if motivo is not None:
            data['motivo_nota'] = motivo
        resp = self.crear(data, esperado=esperado)
        if esperado != 201:
            return resp
        if confirmar:
            self.confirmar_doc(resp.data['id'])
        return resp.data['id']


# =============================================================================================
class CatalogosTests(TributarioFixture, TestCase):
    def test_catalogos_09_y_10(self):
        url = reverse('motivo-nota-list')
        nc = self.client.get(url, {'catalogo': '09'}, **self.headers).data
        self.assertEqual([m['codigo'] for m in nc], [f'{i:02d}' for i in range(1, 12)])  # 12 y 13 inactivos
        todos = self.client.get(url, {'catalogo': '09', 'todos': '1'}, **self.headers).data
        self.assertEqual(len(todos), 13)
        nd = self.client.get(url, {'catalogo': '10'}, **self.headers).data
        self.assertEqual([(m['codigo'], m['descripcion']) for m in nd],
                         [('01', 'Intereses por mora'), ('02', 'Aumento en el valor'), ('03', 'Penalidades / otros conceptos')])
        self.assertEqual(self.client.get(url, {'catalogo': '99'}, **self.headers).status_code, 400)

    def test_catalogo_07_y_unidades(self):
        doc = self.emitir_factura()
        linea = DocumentoDetalle.objects.get(documento_id=doc)
        self.assertEqual(rt.codigo_catalogo_07(linea), '10')
        DocumentoDetalle.objects.filter(pk=linea.pk).update(afectacion_igv='GRATUITO', codigo_afectacion_igv=None)
        self.assertError(self.validar(doc), 'gratuita sin código del catálogo 07')
        DocumentoDetalle.objects.filter(pk=linea.pk).update(codigo_afectacion_igv='15')
        self.assertNotIn('catálogo 07', ' '.join(self.validar(doc)['errores']))
        # Unidad: NIU es del catálogo 03; un código desconocido se advierte, uno imposible es error.
        DocumentoDetalle.objects.filter(pk=linea.pk).update(afectacion_igv='GRAVADO', codigo_afectacion_igv=None)
        UnidadMedida.objects.create(codigo='ABC', descripcion='RARA')
        self.pu.unidad_codigo_id = 'ABC'
        self.pu.save()
        r = self.validar(doc)
        self.assertTrue(r['listo'] and any("'ABC'" in a for a in r['advertencias']), r)
        # Sin presentación en la línea se usa la unidad base del producto.
        DocumentoDetalle.objects.filter(pk=linea.pk).update(producto_unidad=None)
        self.assertEqual(rt.unidad_de_linea(DocumentoDetalle.objects.get(pk=linea.pk)), 'ABC')
        self.assertTrue(self.validar(doc)['listo'])
        DocumentoDetalle.objects.filter(pk=linea.pk).update(producto=None, producto_unidad=None)
        self.assertError(self.validar(doc), 'falta la unidad de medida')
        DocumentoDetalle.objects.filter(pk=linea.pk).update(producto=self.producto, producto_unidad=self.pu)
        UnidadMedida.objects.create(codigo='UNIDAD', descripcion='MAL')
        self.pu.unidad_codigo_id = 'UNIDAD'
        self.pu.save()
        self.assertError(self.validar(doc), 'catálogo 03')


# =============================================================================================
class EmisorTests(TributarioFixture, TestCase):
    def datos(self, headers=None):
        return self.client.get(reverse('empresa-datos-fiscales'), **(headers or self.headers))

    def test_sin_domicilio(self):
        self.empresa.direccion = None
        self.empresa.save()
        v = self.datos().data['validacion']
        self.assertFalse(v['listo'])
        self.assertIn('Falta el domicilio fiscal del emisor.', v['errores'])
        self.assertError(self.validar(self.emitir_factura()), 'domicilio fiscal')

    def test_sin_ubigeo(self):
        self.empresa.ubigeo = None
        self.empresa.save()
        self.assertIn('Falta ubigeo del emisor.', self.datos().data['validacion']['errores'])
        self.assertError(self.validar(self.emitir_factura()), 'Falta ubigeo del emisor')

    def test_datos_completos(self):
        datos = self.datos().data
        self.assertEqual((datos['validacion']['listo'], datos['ubigeo'], datos['codigo_pais']), (True, '150101', 'PE'))
        self.assertListo(self.validar(self.emitir_factura()))

    def test_ruc_del_emisor_invalido(self):
        self.empresa.ruc = '20100100100'
        self.empresa.save()
        self.assertTrue(any('RUC del emisor' in e for e in self.datos().data['validacion']['errores']))

    def test_actualizar_datos_fiscales_valida_audita_y_no_cambia_ruc(self):
        url = reverse('empresa-datos-fiscales')
        resp = self.client.patch(url, {'ubigeo': '269999'}, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch(url, {'ubigeo': '150122', 'distrito': 'MIRAFLORES', 'ruc': '20000000001'},
                                 format='json', **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.empresa.refresh_from_db()
        self.assertEqual((self.empresa.ubigeo, self.empresa.distrito, self.empresa.ruc), ('150122', 'MIRAFLORES', ruc('2010010010')))
        aud = Auditoria.objects.filter(accion='ACTUALIZAR_DATOS_FISCALES').latest('id')
        self.assertEqual(aud.valor_nuevo, {'ubigeo': '150122', 'distrito': 'MIRAFLORES'})
        self.assertEqual(self.client.patch(url, {'codigo_pais': 'PER'}, format='json', **self.headers).status_code, 400)

    def test_usuario_no_admin_no_modifica(self):
        lector = Usuario.objects.create(username='lector17', email='l17@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=lector, empresa=self.empresa, rol='USUARIO')
        self.client.force_authenticate(user=lector)
        self.assertEqual(self.datos().status_code, 200)
        resp = self.client.patch(reverse('empresa-datos-fiscales'), {'ubigeo': '150122'}, format='json', **self.headers)
        self.assertEqual(resp.status_code, 403)

    def test_establecimiento_fiscal(self):
        url = reverse('establecimiento-list-create')
        resp = self.client.post(url, {'codigo_sunat': '0001', 'nombre': 'ANEXO', 'direccion': 'JR. X 1', 'ubigeo': '1501'},
                                format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(url, {'codigo_sunat': '0001', 'nombre': 'ANEXO', 'direccion': 'JR. X 1', 'ubigeo': '150130'},
                                format='json', **self.headers)
        self.assertEqual(resp.status_code, 201, resp.data)
        lista = {e['codigo_sunat']: e for e in self.client.get(url, **self.headers).data}
        self.assertEqual((lista['0000']['es_principal'], lista['0001']['es_principal'], lista['0001']['ubigeo']),
                         (True, False, '150130'))

    def test_establecimiento_invalido_bloquea(self):
        Establecimiento.objects.filter(pk=self.establecimiento.pk).update(codigo_sunat='PRINC')
        self.assertError(self.validar(self.emitir_factura()), 'debe tener 4 dígitos')


# =============================================================================================
class FacturaTests(TributarioFixture, TestCase):
    def test_confirmada_lista(self):
        self.assertListo(self.validar(self.emitir_factura()))

    def test_borrador(self):
        self.assertError(self.validar(self.emitir_factura(confirmar=False)), 'BORRADOR')

    def test_anulada(self):
        doc = self.emitir_factura()
        self.anular(doc)
        self.assertError(self.validar(doc), 'ANULADO')

    def test_cliente_sin_ruc(self):
        doc = self.emitir_factura()
        Tercero.objects.filter(pk=self.cliente.pk).update(tipo_documento='1', numero_documento='45678912')
        self.assertError(self.validar(doc), 'cliente con RUC válido')

    def test_cliente_ruc_digito_invalido(self):
        doc = self.emitir_factura()
        malo = self.cliente.numero_documento[:10] + str((int(self.cliente.numero_documento[10]) + 1) % 10)
        Tercero.objects.filter(pk=self.cliente.pk).update(numero_documento=malo)
        self.assertError(self.validar(doc), 'cliente con RUC válido')

    def test_cliente_ruc_valido(self):
        r = self.validar(self.emitir_factura())
        self.assertListo(r)
        self.assertEqual(r['tipo_comprobante'], '01')

    def test_serie_incorrecta(self):
        data = self.payload('VENTA', [self.linea('VENTA', '1', '100')], serie='X001')
        doc = self.crear(data).data['id']
        self.confirmar_doc(doc)
        r = self.validar(doc)
        self.assertError(r, "La serie 'X001' no es compatible")
        self.assertError(r, 'no usa una serie configurada')

    def test_serie_manual_aunque_empiece_con_f(self):
        doc = self.crear(self.payload('VENTA', [self.linea('VENTA', '1', '100')], serie='F777')).data['id']
        self.confirmar_doc(doc)
        self.assertError(self.validar(doc), 'no usa una serie configurada')

    def test_totales_incoherentes(self):
        doc = self.emitir_factura()
        Documento.objects.filter(pk=doc).update(total='999')
        self.assertError(self.validar(doc), 'subtotal + IGV')

    def test_compra_y_captura_no_se_emiten(self):
        compra = Documento.objects.filter(clase='COMPRA').first()
        self.assertError(self.validar(compra.id), 'Solo los comprobantes de venta')
        doc = self.emitir_factura()
        Documento.objects.filter(pk=doc).update(origen_captura='XML')
        self.assertError(self.validar(doc), 'ya fue emitido por otro sistema')

    def test_validar_no_modifica_nada(self):
        doc = self.emitir_factura()
        antes = (Documento.objects.get(pk=doc).__dict__.copy(), Movimiento.objects.count(), Auditoria.objects.count())
        self.validar(doc)
        self.validar(doc)
        despues = (Documento.objects.get(pk=doc).__dict__.copy(), Movimiento.objects.count(), Auditoria.objects.count())
        antes[0].pop('_state')
        despues[0].pop('_state')
        self.assertEqual(antes, despues)


# =============================================================================================
class BoletaTests(TributarioFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.dni = Tercero.objects.create(empresa=self.empresa, tipo_documento='1', numero_documento='45678912',
                                          razon_social='JUAN PEREZ', es_cliente=True)

    def test_serie_valida_cliente_dni(self):
        r = self.validar(self.emitir_boleta(tercero=self.dni))
        self.assertListo(r)
        self.assertEqual(r['tipo_comprobante'], '03')

    def test_serie_invalida(self):
        r = self.validar(self.emitir_boleta(tercero=self.dni, serie='F555'))
        self.assertError(r, "La serie 'F555' no es compatible")

    def test_cliente_con_documento_invalido(self):
        doc = self.emitir_boleta(tercero=self.dni)
        Tercero.objects.filter(pk=self.dni.pk).update(numero_documento='4567891')
        self.assertError(self.validar(doc), '8 dígitos')

    def test_consumidor_final_bajo_umbral(self):
        r = self.validar(self.emitir_boleta(tercero=None))  # 118 < 700
        self.assertListo(r)
        self.assertTrue(any('consumidor final' in a for a in r['advertencias']))

    def test_consumidor_final_sobre_umbral_requiere_identificacion(self):
        self.assertError(self.validar(self.emitir_boleta(tercero=None, cantidad='6')), 'requiere identificar al cliente')  # 708
        self.assertListo(self.validar(self.emitir_boleta(tercero=self.dni, cantidad='6')))

    def test_boleta_a_ruc_permitida(self):
        self.assertListo(self.validar(self.emitir_boleta(tercero=self.cliente)))


# =============================================================================================
class NotaCreditoTests(TributarioFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.origen = self.emitir_factura()
        fijar_estado_sunat(Documento.objects.get(pk=self.origen))  # Bloque 23: origen aceptado por SUNAT

    def test_sin_motivo(self):
        self.assertError(self.validar(self.nota(self.origen)), 'Falta el motivo de la nota (catálogo 09)')

    def test_con_motivo(self):
        nc = self.nota(self.origen, motivo='09')
        self.assertListo(self.validar(nc))
        detalle = self.detalle(nc)
        self.assertEqual((detalle['motivo_nota_codigo'], detalle['motivo_nota_descripcion']), ('09', 'Disminución en el valor'))

    def test_motivo_incoherente_solo_advierte(self):
        r = self.validar(self.nota(self.origen, motivo='07'))  # devolución por ítem sin devolución física
        self.assertListo(r)
        self.assertTrue(any('indica devolución' in a for a in r['advertencias']), r)

    def test_motivo_invalido_o_inactivo_se_rechaza_al_registrar(self):
        self.assertIn('no existe en el catálogo 09', str(self.nota(self.origen, motivo='99', esperado=400).data))
        self.assertIn('no está habilitado', str(self.nota(self.origen, motivo='13', esperado=400).data))
        data = self.payload('VENTA', [self.linea('VENTA', '1', '100')])
        data['motivo_nota'] = '01'
        self.assertIn('Solo las notas', str(self.crear(data, esperado=400).data))

    def test_origen_de_otra_empresa(self):
        nc = self.nota(self.origen, motivo='09')
        otra = Documento.objects.create(
            empresa=self.otra_empresa, clase='VENTA', periodo=Periodo.objects.create(
                empresa=self.otra_empresa, anio=2026, mes=1, orden=202601, fecha_inicio=date(2026, 1, 1),
                fecha_fin=date(2026, 1, 31), estado='ABIERTO'),
            ruc_emisor=self.otra_empresa.ruc, tipo_comprobante=self.factura, serie='F001', serie_normalizada='F001',
            numero='1', numero_normalizado='1', fecha_emision=date(2026, 1, 5), moneda_codigo=self.pen,
            subtotal=100, igv=18, total=118, estado='CONFIRMADO')
        Documento.objects.filter(pk=nc).update(documento_origen=otra)
        self.assertError(self.validar(nc), 'pertenece a otra empresa')

    def test_origen_correcto_y_serie_de_boleta(self):
        self.assertListo(self.validar(self.nota(self.origen, motivo='09')))
        nc_b = self.nota(self.origen, motivo='09', serie=self.serie_bc)  # serie B sobre una factura
        self.assertError(self.validar(nc_b), 'empieza con F')

    def test_cambiar_motivo_auditado(self):
        nc = self.nota(self.origen)
        url = reverse('documento-motivo-nota', args=[nc])
        self.assertEqual(self.client.put(url, {'motivo_nota': '02'}, format='json', **self.headers).status_code, 200)
        self.assertEqual(self.client.put(url, {'motivo_nota': '04'}, format='json', **self.headers).data['motivo_nota_codigo'], '04')
        aud = Auditoria.objects.filter(accion='CAMBIAR_MOTIVO_NOTA', registro_id=nc).order_by('id')
        self.assertEqual([a.valor_nuevo['motivo_nota'] for a in aud], ['09-02', '09-04'])
        self.assertListo(self.validar(nc))
        factura = reverse('documento-motivo-nota', args=[self.origen])
        self.assertEqual(self.client.put(factura, {'motivo_nota': '01'}, format='json', **self.headers).status_code, 400)


class NotaDebitoTests(TributarioFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.origen = self.emitir_factura()
        fijar_estado_sunat(Documento.objects.get(pk=self.origen))  # Bloque 23: origen aceptado por SUNAT

    def test_sin_motivo(self):
        self.assertError(self.validar(self.nota(self.origen, tipo='ND')), 'Falta el motivo de la nota (catálogo 10)')

    def test_con_motivo(self):
        self.assertListo(self.validar(self.nota(self.origen, tipo='ND', motivo='02')))

    def test_motivo_de_otro_catalogo(self):
        self.assertIn('no existe en el catálogo 10', str(self.nota(self.origen, tipo='ND', motivo='09', esperado=400).data))

    def test_origen_de_otra_empresa(self):
        nd = self.nota(self.origen, tipo='ND', motivo='01')
        otra = Documento.objects.create(
            empresa=self.otra_empresa, clase='VENTA', periodo=Periodo.objects.create(
                empresa=self.otra_empresa, anio=2026, mes=1, orden=202601, fecha_inicio=date(2026, 1, 1),
                fecha_fin=date(2026, 1, 31), estado='ABIERTO'),
            ruc_emisor=self.otra_empresa.ruc, tipo_comprobante=self.factura, serie='F001', serie_normalizada='F001',
            numero='2', numero_normalizado='2', fecha_emision=date(2026, 1, 5), moneda_codigo=self.pen,
            subtotal=100, igv=18, total=118, estado='CONFIRMADO')
        Documento.objects.filter(pk=nd).update(documento_origen=otra)
        self.assertError(self.validar(nd), 'pertenece a otra empresa')

    def test_borrador_y_origen_anulado(self):
        nd = self.nota(self.origen, tipo='ND', motivo='03', confirmar=False)
        self.assertError(self.validar(nd), 'BORRADOR')
        Documento.objects.filter(pk=self.origen).update(estado='ANULADO')
        self.assertError(self.validar(nd), 'El documento de origen está ANULADO')

    def test_contabilidad_de_la_nota_no_cambia(self):
        nd = self.nota(self.origen, tipo='ND', motivo='02')
        doc = Documento.objects.get(pk=nd)
        self.assertEqual((doc.estado, str(doc.total), doc.motivo_nota.catalogo), ('CONFIRMADO', '11.80000000', '10'))
        self.assertFalse(Movimiento.objects.filter(documento_detalle__documento_id=nd).exists())  # ND de venta: sin Kardex


# =============================================================================================
class MultiempresaTests(TributarioFixture, TestCase):
    def test_documento_de_otra_empresa(self):
        doc = self.emitir_factura()
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=self.otra_empresa, rol='ADMIN')
        otra = {'HTTP_X_EMPRESA_ID': str(self.otra_empresa.id)}
        self.validar(doc, headers=otra, esperado=404)
        resp = self.client.put(reverse('documento-motivo-nota', args=[doc]), {'motivo_nota': '01'}, format='json', **otra)
        self.assertEqual(resp.status_code, 404)
        # Los datos fiscales que se leen son los de la empresa activa, no los de otra.
        self.assertEqual(self.client.get(reverse('empresa-datos-fiscales'), **otra).data['ruc'], self.otra_empresa.ruc)

    def test_usuario_sin_acceso(self):
        doc = self.emitir_factura()
        extrano = Usuario.objects.create(username='extrano17', email='x17@test.pe', password_hash='x')
        self.client.force_authenticate(user=extrano)
        resp = self.client.get(reverse('documento-validacion-electronica', args=[doc]), **self.headers)
        self.assertIn(resp.status_code, (403, 404))
