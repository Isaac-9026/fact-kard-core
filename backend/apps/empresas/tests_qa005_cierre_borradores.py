"""
QA-005 — no se cierra un período con comprobantes en BORRADOR (no movieron el Kardex). Antes
era solo una advertencia. Mensaje con la cantidad y los comprobantes; los borradores de otro
período o de otra empresa no bloquean.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento
from apps.empresas.models import CierrePeriodo, Periodo


class CierreConBorradoresTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.compra_confirmada('10', '10', fecha='2026-01-05')

    def borrador(self, **kwargs):
        resp = self.crear(self.payload('COMPRA', [self.linea('COMPRA', '1', '10')], **kwargs))
        return resp.data['id']

    def cerrar(self, periodo=None):
        return self.client.post(reverse('periodo-cerrar', args=[(periodo or self.enero).id]), format='json', **self.headers)

    def test_borradores_del_periodo_bloquean_el_cierre_con_mensaje_claro(self):
        ids = [self.borrador(fecha='2026-01-20'), self.borrador(fecha='2026-01-21', serie='F777')]
        resp = self.cerrar()
        self.assertEqual(resp.status_code, 400)
        mensaje = str(resp.data['detail'])
        self.assertIn('hay 2 comprobante(s) en BORRADOR', mensaje)
        self.assertIn('COMPRA F777-', mensaje)
        self.assertEqual(sorted(int(d['id']) for d in resp.data['documentos_borrador']), sorted(ids))
        self.enero.refresh_from_db()
        self.assertEqual(self.enero.estado, 'ABIERTO')
        self.assertFalse(CierrePeriodo.objects.filter(periodo=self.enero).exists())

    def test_tras_confirmar_o_anular_los_borradores_si_cierra(self):
        uno, dos = self.borrador(fecha='2026-01-20'), self.borrador(fecha='2026-01-21')
        self.revisar(uno)
        self.confirmar(uno)
        self.anular(dos)
        self.assertEqual(Documento.objects.filter(periodo=self.enero, estado='BORRADOR').count(), 0)
        resp = self.cerrar()
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_borrador_de_otro_periodo_no_bloquea(self):
        febrero = Periodo.objects.create(empresa=self.empresa, anio=2026, mes=2, orden=202602,
                                         fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 2, 28), estado='ABIERTO')
        self.borrador(fecha='2026-02-03', periodo=febrero)
        resp = self.cerrar()
        self.assertEqual(resp.status_code, 200, resp.data)
        # Y febrero sí queda bloqueado por su propio borrador.
        self.assertEqual(self.cerrar(febrero).status_code, 400)

    def test_borrador_de_otra_empresa_no_bloquea(self):
        otro_periodo = Periodo.objects.create(empresa=self.otra_empresa, anio=2026, mes=1, orden=202601,
                                              fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 31), estado='ABIERTO')
        Documento.objects.create(
            empresa=self.otra_empresa, clase='COMPRA', periodo=otro_periodo, ruc_emisor='20555000111',
            tipo_comprobante=self.factura, serie='F001', serie_normalizada='F001', numero='9', numero_normalizado='9',
            fecha_emision=date(2026, 1, 10), moneda_codigo=self.pen, subtotal=0, igv=0, total=0, estado='BORRADOR',
        )
        self.assertEqual(self.cerrar().status_code, 200)
