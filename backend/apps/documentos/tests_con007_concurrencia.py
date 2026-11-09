"""
CON-007 concurrencia: dos notas de crédito confirmadas a la vez sobre la misma
línea de origen no pueden devolver, sumadas, más que la cantidad original.
La confirmación bloquea el documento de origen (select_for_update).
"""
import threading
from decimal import Decimal

from django.db import connection
from django.test import TransactionTestCase
from rest_framework.exceptions import ValidationError

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.kardex.models import Movimiento
from apps.kardex.services import anular_documento_motor, confirmar_documento_motor


class ConfirmacionConcurrenteDeNotasTests(Bloque2Fixture, TransactionTestCase):
    def setUp(self):
        self.crear_base()
        self.compra = self.compra_confirmada('10', '10')
        detalle = DocumentoDetalle.objects.get(documento_id=self.compra, linea=1)
        self.notas = []
        for _ in range(2):
            data = self.payload(
                'COMPRA', [self.linea('DEVOLUCION_COMPRA', '6', '10', detalle_origen=detalle.id)],
                tipo=self.nota_credito, origen=Documento.objects.get(pk=self.compra), fecha='2026-01-15',
            )
            nota_id = self.crear(data).data['id']
            self.revisar(nota_id)
            self.notas.append(nota_id)

    def _en_paralelo(self, *acciones):
        barrera = threading.Barrier(len(acciones))
        resultados = [None] * len(acciones)

        def correr(i, accion):
            try:
                barrera.wait(timeout=10)
                accion()
                resultados[i] = 'OK'
            except ValidationError as exc:
                resultados[i] = f'400: {exc.detail}'
            except Exception as exc:  # noqa: BLE001 - se reporta en la aserción
                resultados[i] = f'ERROR {type(exc).__name__}: {exc}'
            finally:
                connection.close()

        hilos = [threading.Thread(target=correr, args=(i, a)) for i, a in enumerate(acciones)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)
        return resultados

    def _confirmar(self, nota_id):
        return lambda: confirmar_documento_motor(
            documento_id=nota_id, empresa_id=self.empresa.id, usuario_id=self.usuario.id,
        )

    def test_solo_una_de_dos_notas_simultaneas_se_confirma(self):
        resultados = self._en_paralelo(*(self._confirmar(n) for n in self.notas))

        self.assertEqual(sorted('OK' if r == 'OK' else r[:3] for r in resultados), ['400', 'OK'], resultados)
        self.assertTrue(any('solo quedan 4 disponibles' in r for r in resultados), resultados)
        estados = sorted(Documento.objects.filter(pk__in=self.notas).values_list('estado', flat=True))
        self.assertEqual(estados, ['BORRADOR', 'CONFIRMADO'])
        self.assertEqual(self.stock(), Decimal('4'))
        self.assertEqual(self.saldo().cantidad_total, Decimal('4.00000000'))

    def test_anular_origen_mientras_se_confirma_una_nota_no_duplica_la_reversa(self):
        resultados = self._en_paralelo(
            self._confirmar(self.notas[0]),
            lambda: anular_documento_motor(
                documento_id=self.compra, empresa_id=self.empresa.id,
                usuario_id=self.usuario.id, motivo='QA concurrencia',
            ),
        )

        self.assertEqual(sorted('OK' if r == 'OK' else r[:3] for r in resultados), ['400', 'OK'], resultados)
        compra = Documento.objects.get(pk=self.compra)
        nota = Documento.objects.get(pk=self.notas[0])
        # Solo uno de los dos efectos pudo aplicarse; nunca ambos.
        self.assertNotEqual((compra.estado, nota.estado), ('ANULADO', 'CONFIRMADO'))
        if compra.estado == 'ANULADO':
            self.assertEqual(self.stock(), Decimal('0'))
        else:
            self.assertEqual(nota.estado, 'CONFIRMADO')
            self.assertEqual(self.stock(), Decimal('4'))
        self.assertFalse(Movimiento.objects.filter(empresa=self.empresa, producto=self.producto)
                         .filter(valorizacion__isnull=True).exists())
