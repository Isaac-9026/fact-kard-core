from decimal import Decimal, ROUND_HALF_UP

from rest_framework.exceptions import ValidationError

from apps.empresas.models import CierrePeriodo, Periodo
from apps.inventario.models import Producto
from apps.kardex.models import SaldoCppActual


OCHO_DECIMALES = Decimal('0.00000001')
SEIS_DECIMALES = Decimal('0.000001')


def _q8(valor):
    return Decimal(valor or 0).quantize(OCHO_DECIMALES, rounding=ROUND_HALF_UP)


def _texto(valor, precision=OCHO_DECIMALES):
    return format(Decimal(valor).quantize(precision, rounding=ROUND_HALF_UP), 'f')


def obtener_valores_factkard(*, empresa_id, periodo_id, producto_id):
    periodo = Periodo.objects.filter(pk=periodo_id, empresa_id=empresa_id).first()
    if not periodo:
        raise ValidationError({'periodo_id': 'El período no pertenece a la empresa activa.'})
    producto = Producto.objects.filter(pk=producto_id, empresa_id=empresa_id).first()
    if not producto:
        raise ValidationError({'producto_id': 'El producto no pertenece a la empresa activa.'})

    cierre = CierrePeriodo.objects.filter(periodo_id=periodo.id, vigente=True).first()
    if cierre:
        detalles = cierre.detalles.filter(producto_id=producto.id)
        if not detalles.exists():
            cantidad = cpp = valor = Decimal('0')
        else:
            cantidad = sum((detalle.saldo_cantidad or Decimal('0') for detalle in detalles), Decimal('0'))
            valor = sum((detalle.saldo_valor_pen or Decimal('0') for detalle in detalles), Decimal('0'))
            cpp = next((detalle.cpp_pen for detalle in detalles if detalle.cpp_pen is not None), Decimal('0'))
        fuente = 'CIERRE_PERIODO_DETALLE'
    elif periodo.estado == 'ABIERTO':
        saldo = SaldoCppActual.objects.filter(empresa_id=empresa_id, producto_id=producto.id).first()
        cantidad = saldo.cantidad_total if saldo else Decimal('0')
        cpp = saldo.cpp_pen if saldo and saldo.cpp_pen is not None else Decimal('0')
        valor = saldo.valor_total_pen if saldo else Decimal('0')
        fuente = 'SALDO_CPP_ACTUAL'
    else:
        raise ValidationError({'periodo_id': 'El período no tiene un cierre oficial vigente y no está abierto.'})

    return {
        'periodo_id': periodo.id,
        'producto_id': producto.id,
        'producto_codigo': producto.codigo_interno,
        'estado_periodo': periodo.estado,
        'fuente': fuente,
        'cierre_id': cierre.id if cierre else None,
        'cantidad_factkard': _texto(_q8(cantidad)),
        'cpp_factkard': _texto(_q8(cpp)),
        'valor_factkard': _texto(_q8(valor)),
    }


def comparar_piloto(*, empresa_id, datos):
    reales = obtener_valores_factkard(
        empresa_id=empresa_id,
        periodo_id=datos['periodo_id'],
        producto_id=datos['producto_id'],
    )
    cantidad_esperada = _q8(datos['cantidad_esperada'])
    cpp_esperado = _q8(datos['cpp_esperado'])
    valor_esperado = _q8(datos['valor_esperado'])
    tiempo_manual = Decimal(datos['tiempo_manual_segundos'])
    tiempo_factkard = Decimal(datos['tiempo_factkard_segundos'])
    if tiempo_manual <= 0:
        raise ValidationError({'tiempo_manual_segundos': 'Debe ser mayor que cero.'})
    if tiempo_factkard < 0:
        raise ValidationError({'tiempo_factkard_segundos': 'No puede ser negativo.'})

    diferencia_cantidad = _q8(Decimal(reales['cantidad_factkard']) - cantidad_esperada)
    diferencia_cpp = _q8(Decimal(reales['cpp_factkard']) - cpp_esperado)
    diferencia_valor = _q8(Decimal(reales['valor_factkard']) - valor_esperado)
    reduccion = ((tiempo_manual - tiempo_factkard) / tiempo_manual) * Decimal('100')
    cuadra = diferencia_cantidad == 0 and diferencia_cpp == 0 and diferencia_valor == 0
    return {
        **reales,
        'esperado': {
            'cantidad': _texto(cantidad_esperada),
            'cpp': _texto(cpp_esperado),
            'valor': _texto(valor_esperado),
        },
        'diferencias': {
            'cantidad': _texto(diferencia_cantidad),
            'cpp': _texto(diferencia_cpp),
            'valor': _texto(diferencia_valor),
        },
        'cuadra_100': cuadra,
        'reduccion_porcentaje': _texto(reduccion, SEIS_DECIMALES),
    }
