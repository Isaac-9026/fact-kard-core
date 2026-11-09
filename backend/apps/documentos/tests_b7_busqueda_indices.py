"""
Bloque 7 — el buscador de documentos ahora se resuelve en el servidor (paginación real) y
debe aceptar "SERIE-NUMERO"; índices nuevos presentes en la base de datos.
"""
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento


class BusquedaDocumentosTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.ids = [self.compra_confirmada('1', '10', fecha=f'2026-01-{10 + i:02d}') for i in range(3)]

    def buscar(self, texto, **extra):
        resp = self.client.get(reverse('documento-list-create'), {'search': texto, 'page_size': 10, **extra}, **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        return {d['id'] for d in resp.data['results']}, resp.data['count']

    def test_serie_guion_numero(self):
        doc = Documento.objects.get(pk=self.ids[1])
        encontrados, total = self.buscar(f'{doc.serie_normalizada}-{doc.numero_normalizado}')
        self.assertIn(doc.id, encontrados)
        self.assertEqual(total, 1)
        # Fragmentos como en el filtro anterior del navegador ("…01-2" dentro de "F001-2…").
        encontrados, _ = self.buscar(f'{doc.serie_normalizada[-2:]}-{doc.numero_normalizado[:1]}')
        self.assertIn(doc.id, encontrados)

    def test_busqueda_simple_y_filtros_combinados(self):
        doc = Documento.objects.get(pk=self.ids[0])
        self.assertEqual(self.buscar(doc.serie_normalizada)[1], 3)
        self.assertEqual(self.buscar(doc.ruc_emisor, estado='CONFIRMADO')[1], 3)
        self.assertEqual(self.buscar(doc.ruc_emisor, estado='BORRADOR')[1], 0)
        self.assertEqual(self.buscar('NO-EXISTE-XYZ')[1], 0)


class IndicesBloque7Tests(TestCase):
    def test_indices_creados(self):
        with connection.cursor() as c:
            c.execute("select indexname from pg_indexes where indexname = any(%s)", [[
                'ix_movimiento_empresa_fecha', 'ix_documento_emp_estado_fecha',
                'ix_auditoria_empresa_fecha', 'ix_token_revocado_expira',
            ]])
            self.assertEqual(len(c.fetchall()), 4)
