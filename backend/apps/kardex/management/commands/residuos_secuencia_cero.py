"""
Bloque 5 — diagnóstico de RESIDUO_AUTOMATICO antiguos con secuencia 0 (creados al
confirmar antes del Bloque 4). SOLO LISTA; no modifica datos.

No se repara: la tabla `movimiento` es inmutable (trigger trg_movimiento_no_update) y
esos residuos son consistentes en sí mismos, porque su valorización y todo recálculo
posterior usan el mismo orden (fecha, prioridad, secuencia=0, id). Cada caso se clasifica:
- SIN_EFECTO: es el único ajuste (prioridad 3) del producto ese día; la secuencia 0 no
  altera el orden respecto de ningún otro movimiento.
- ORDEN_ANTICIPADO: hay otros ajustes ese día y el residuo queda antes que ellos. El
  saldo es coherente, pero si se quiere otra posición se debe anular el origen y
  volver a registrarlo (extorno), con revisión contable.
- PERIODO_CERRADO: pertenece a un período cerrado (solo informativo).
"""
from django.core.management.base import BaseCommand

from apps.kardex.models import Movimiento


def diagnosticar(empresa_id=None):
    residuos = Movimiento.objects.filter(
        tipo_operacion__codigo_interno='RESIDUO_AUTOMATICO', prioridad_dia=3, secuencia=0,
    ).select_related('periodo', 'producto', 'valorizacion').order_by('empresa_id', 'producto_id', 'fecha_movimiento', 'id')
    if empresa_id:
        residuos = residuos.filter(empresa_id=empresa_id)
    resultado = []
    for mov in residuos:
        otros = Movimiento.objects.filter(
            empresa_id=mov.empresa_id, producto_id=mov.producto_id,
            fecha_movimiento=mov.fecha_movimiento, prioridad_dia=3,
        ).exclude(pk=mov.pk).count()
        if mov.periodo.estado == 'CERRADO':
            estado = 'PERIODO_CERRADO'
        elif otros:
            estado = 'ORDEN_ANTICIPADO'
        else:
            estado = 'SIN_EFECTO'
        resultado.append({'movimiento': mov, 'estado': estado, 'otros_ajustes_del_dia': otros})
    return resultado


class Command(BaseCommand):
    help = 'Lista los RESIDUO_AUTOMATICO con secuencia 0 y su efecto en el orden (no modifica datos).'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', type=int, help='Limitar a una empresa (id).')

    def handle(self, *args, **opciones):
        casos = diagnosticar(opciones.get('empresa'))
        if not casos:
            self.stdout.write('No hay residuos automáticos con secuencia 0.')
            return
        for caso in casos:
            mov = caso['movimiento']
            valor = getattr(mov, 'valorizacion', None)
            self.stdout.write(
                f"{caso['estado']:<17} mov={mov.id} empresa={mov.empresa_id} producto={mov.producto.codigo_interno} "
                f"fecha={mov.fecha_movimiento.isoformat()} periodo={mov.periodo.anio}-{mov.periodo.mes:02d} "
                f"importe={valor.valor_movimiento_pen if valor else mov.valor_ajuste_pen} "
                f"otros_ajustes_del_dia={caso['otros_ajustes_del_dia']}"
            )
        resumen = {}
        for caso in casos:
            resumen[caso['estado']] = resumen.get(caso['estado'], 0) + 1
        self.stdout.write(f"Total: {len(casos)} | " + ' | '.join(f'{k}: {v}' for k, v in sorted(resumen.items())))
        self.stdout.write('Solo diagnóstico: los movimientos son inmutables y no se modificó ningún dato.')
