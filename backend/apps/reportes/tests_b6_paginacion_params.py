"""
Bloque 6 — paginación opcional (?page=&page_size=) y validación de query params (400,
nunca 500) en los listados que pueden crecer.
"""
from django.test import TestCase
from django.urls import reverse

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar_auditoria
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.kardex.models import Movimiento

ENDPOINTS_GET = [
    'kardex-report', 'kardex-excel-export', 'formato-131', 'formato-131-excel', 'piloto-comparador',
    'kardex-movimientos', 'kardex-incidencias', 'kardex-recalculos', 'documento-list-create',
    'documento-captura-list', 'auditoria:auditoria-list', 'tipo-cambio-list-create', 'cierre-list',
]
PARAMETROS = ['producto_id', 'producto', 'periodo_id', 'periodo', 'almacen_id', 'almacen', 'tipo_operacion_id',
              'establecimiento_id', 'fecha_desde', 'fecha_hasta', 'fecha', 'page', 'page_size']
VALORES_MALOS = ['abc', '-1', '0', '2026-13-45', '99999999999999999999', '1.5', "1' OR 1=1"]


class PaginacionTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        for i in range(5):
            self.compra_confirmada('1', str(10 + i), fecha=f'2026-01-{10 + i:02d}')

    def get(self, nombre, **params):
        resp = self.client.get(reverse(nombre), params, **self.headers)
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', None))
        return resp.data

    def test_sin_parametros_se_mantiene_la_lista_completa(self):
        self.assertIsInstance(self.get('documento-list-create'), list)
        self.assertEqual(len(self.get('kardex-movimientos')), 5)
        self.assertNotIn('paginacion', self.get('kardex-report'))

    def test_primera_y_siguiente_pagina(self):
        p1 = self.get('documento-list-create', page_size=2)
        self.assertEqual((p1['count'], len(p1['results'])), (5, 2))
        self.assertIsNone(p1['previous'])
        p2 = self.client.get(p1['next'], **self.headers).data
        p3 = self.get('documento-list-create', page_size=2, page=3)
        ids = [d['id'] for d in p1['results'] + p2['results'] + p3['results']]
        self.assertEqual(len(set(ids)), 5)  # sin repetidos ni faltantes
        self.assertIsNone(p3['next'])
        # Página fuera de rango: 404 (DRF), no 500.
        self.assertEqual(self.client.get(reverse('documento-list-create'), {'page': 9, 'page_size': 2},
                                         **self.headers).status_code, 404)

    def test_movimientos_y_kardex_paginados(self):
        movs = self.get('kardex-movimientos', page_size=2, page=2)
        esperados = list(Movimiento.objects.filter(empresa=self.empresa).order_by(
            'fecha_movimiento', 'prioridad_dia', 'secuencia', 'id').values_list('id', flat=True))[2:4]
        self.assertEqual([m['id'] for m in movs['results']], esperados)
        completo = self.get('kardex-report', producto_id=self.producto.id)
        pagina = self.get('kardex-report', producto_id=self.producto.id, page_size=2, page=3)
        self.assertEqual(pagina['paginacion']['count'], 5)
        self.assertEqual([f['id'] for f in pagina['movimientos']], [f['id'] for f in completo['movimientos']][4:])
        self.assertEqual(pagina['resumen'], completo['resumen'])  # el resumen siempre es del rango completo

    def test_filtros_mas_paginacion(self):
        data = self.get('kardex-report', producto_id=self.producto.id, fecha_desde='2026-01-12', page_size=2)
        self.assertEqual(data['paginacion']['count'], 3)
        self.assertEqual(data['resumen']['saldo_inicial_cantidad'], '2.00000000')
        movs = self.get('kardex-movimientos', producto=self.producto.id, periodo=self.enero.id, page_size=10)
        self.assertEqual(movs['count'], 5)
        docs = self.get('documento-list-create', clase='COMPRA', estado='CONFIRMADO', page_size=3)
        self.assertEqual((docs['count'], len(docs['results'])), (5, 3))

    def test_auditoria_paginada_y_aislada_por_empresa(self):
        for i in range(3):
            registrar_auditoria(self.otra_empresa.id, None, 'QA_OTRA', 'X', i)
        propias = Auditoria.objects.filter(empresa_id=self.empresa.id).count()
        data = self.get('auditoria:auditoria-list', page_size=1)
        self.assertEqual(data['count'], propias)
        self.assertFalse(any(r['accion'] == 'QA_OTRA' for r in self.get('auditoria:auditoria-list', page_size=500)['results']))
        # Otra empresa no asignada al usuario: 403 aun pidiendo una página.
        otra = self.client.get(reverse('documento-list-create'), {'page': 1},
                               HTTP_X_EMPRESA_ID=str(self.otra_empresa.id))
        self.assertEqual(otra.status_code, 403)

    def test_page_size_maximo(self):
        self.assertEqual(len(self.get('kardex-movimientos', page_size=10000)['results']), 5)


class ParametrosInvalidosTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.client.raise_request_exception = False

    def test_ningun_parametro_invalido_genera_500(self):
        errores = []
        for nombre in ENDPOINTS_GET:
            for parametro in PARAMETROS:
                for valor in VALORES_MALOS:
                    params = {parametro: valor}
                    if parametro not in ('periodo_id',):
                        params['periodo_id'] = self.enero.id
                    resp = self.client.get(reverse(nombre), params, **self.headers)
                    if resp.status_code >= 500:
                        errores.append((nombre, parametro, valor, resp.status_code))
        self.assertEqual(errores, [])

    def test_errores_esperables_son_400_con_mensaje(self):
        casos = [
            ('kardex-report', {'producto_id': 'abc'}, 'producto_id'),
            ('kardex-report', {'fecha_desde': '2026-13-45'}, 'fecha_desde'),
            ('kardex-report', {'fecha_desde': '2026-02-01', 'fecha_hasta': '2026-01-01'}, 'posterior'),
            ('formato-131', {'periodo_id': 'x'}, 'periodo_id'),
            ('formato-131', {}, 'obligatorio'),
            ('kardex-movimientos', {'producto': '1.5'}, 'producto'),
            ('documento-list-create', {'periodo': 'abc'}, 'periodo'),
            ('tipo-cambio-list-create', {'fecha': '31/01/2026'}, 'fecha'),
            ('documento-list-create', {'page': 'x'}, 'page'),
        ]
        for nombre, params, texto in casos:
            with self.subTest(nombre=nombre, params=params):
                resp = self.client.get(reverse(nombre), params, **self.headers)
                self.assertEqual(resp.status_code, 400, resp.content[:200])
                self.assertIn(texto, str(resp.data))
