#!/usr/bin/env python3
"""
Bloque 9 — genera casos_documentos.json: casos de precisión con los importes ESPERADOS
calculados con decimal.Decimal + ROUND_HALF_UP (las reglas del backend), sin usar el código
del frontend ni del backend.

    python3 qa/precision/generar_casos.py   # reescribe casos_documentos.json

Los usan:
- frontend/src/utils/precisionDocumentos.test.ts  (cálculo del formulario = esperado)
- backend/apps/documentos/tests_b9_precision.py   (lo que guarda la API = esperado)
"""
import json
from decimal import ROUND_HALF_UP, Decimal as D
from pathlib import Path

Q8, Q6, Q2 = D('0.00000001'), D('0.000001'), D('0.01')
SIN_IGV = {'EXONERADO', 'INAFECTO', 'EXPORTACION'}

CASOS = [
    {
        'id': 'auditoria_0_00004875',
        'descripcion': 'Caso de la auditoría: IGV con float sin redondear a céntimos (0.03004875) vs Decimal HALF_UP (0.03).',
        'clase': 'COMPRA', 'tipo': 'FACTURA', 'moneda': 'PEN', 'fecha': '2026-01-10', 'tasa_pct': '18.00',
        'lineas': [{'operacion': 'COMPRA', 'cantidad': '2.5', 'precio': '0.066775', 'afectacion': 'GRAVADO'}],
        'antes': {'igv_lineas': ['0.03004875'], 'total': '0.19698625', 'diferencia_total': '0.00004875'},
    },
    {
        'id': 'suma_0_1_mas_0_2',
        'descripcion': '0.1 + 0.2 en dos líneas inafectas.',
        'clase': 'COMPRA', 'tipo': 'FACTURA', 'moneda': 'PEN', 'fecha': '2026-01-10', 'tasa_pct': '18.00',
        'lineas': [
            {'operacion': 'COMPRA', 'cantidad': '1', 'precio': '0.1', 'afectacion': 'INAFECTO'},
            {'operacion': 'COMPRA', 'cantidad': '1', 'precio': '0.2', 'afectacion': 'INAFECTO'},
        ],
    },
    {
        'id': 'compra_fraccionaria_precios_6_dec',
        'descripcion': 'Cantidades fraccionarias, precios de 4–6 decimales, factor de conversión, varias afectaciones.',
        'clase': 'COMPRA', 'tipo': 'FACTURA', 'moneda': 'PEN', 'fecha': '2026-01-10', 'tasa_pct': '18.00',
        'lineas': [
            {'operacion': 'COMPRA', 'cantidad': '3.333', 'precio': '12.345678', 'afectacion': 'GRAVADO'},
            {'operacion': 'COMPRA', 'cantidad': '7.25', 'precio': '0.0105', 'afectacion': 'GRAVADO', 'factor': '12.5'},
            {'operacion': 'COMPRA', 'cantidad': '0.125', 'precio': '99.9999', 'afectacion': 'EXONERADO'},
            {'operacion': 'COMPRA', 'cantidad': '1.5', 'precio': '1.005', 'afectacion': 'INAFECTO', 'factor': '0.333333'},
        ],
    },
    {
        'id': 'redondeo_mitad_hacia_arriba',
        'descripcion': 'Empates exactos: IGV 0.045 → 0.05 (HALF_UP; HALF_EVEN daría 0.04) y subtotal 1.267345665 → 1.26734567.',
        'clase': 'COMPRA', 'tipo': 'FACTURA', 'moneda': 'PEN', 'fecha': '2026-01-10', 'tasa_pct': '18.00',
        'lineas': [
            {'operacion': 'COMPRA', 'cantidad': '1', 'precio': '0.25', 'afectacion': 'GRAVADO'},
            {'operacion': 'COMPRA', 'cantidad': '0.1', 'precio': '0.12345665', 'afectacion': 'EXONERADO'},
            {'operacion': 'COMPRA', 'cantidad': '1', 'precio': '1.005', 'afectacion': 'INAFECTO'},
        ],
    },
    {
        'id': 'compra_usd_tc',
        'descripcion': 'Compra en USD con tipo de cambio de 3 decimales (los totales se guardan en USD).',
        'clase': 'COMPRA', 'tipo': 'FACTURA', 'moneda': 'USD', 'tc_venta': '3.751', 'fecha': '2026-01-12', 'tasa_pct': '18.00',
        'lineas': [
            {'operacion': 'COMPRA', 'cantidad': '12.5', 'precio': '8.3333', 'afectacion': 'GRAVADO'},
            {'operacion': 'COMPRA', 'cantidad': '4', 'precio': '19.995', 'afectacion': 'GRAVADO'},
        ],
    },
    {
        'id': 'tasa_historica_16',
        'descripcion': 'Tasa histórica configurada (16 % desde 2026-01-15): no se asume 18 %.',
        'clase': 'COMPRA', 'tipo': 'FACTURA', 'moneda': 'PEN', 'fecha': '2026-01-20', 'tasa_pct': '16.00',
        'tasa_historica': {'vigente_desde': '2026-01-15', 'tasa_pct': '16.00'},
        'lineas': [
            {'operacion': 'COMPRA', 'cantidad': '3', 'precio': '33.33', 'afectacion': 'GRAVADO'},
            {'operacion': 'COMPRA', 'cantidad': '2.75', 'precio': '4.4444', 'afectacion': 'GRAVADO'},
        ],
    },
    {
        'id': 'venta_exportacion_gratuito',
        'descripcion': 'Venta con línea gravada, exportación y bonificación gratuita.',
        'clase': 'VENTA', 'tipo': 'FACTURA', 'moneda': 'PEN', 'fecha': '2026-01-15', 'tasa_pct': '18.00',
        'requiere_stock': True,
        'lineas': [
            {'operacion': 'VENTA', 'cantidad': '1.5', 'precio': '45.678912', 'afectacion': 'GRAVADO'},
            {'operacion': 'VENTA', 'cantidad': '2', 'precio': '30.125', 'afectacion': 'EXPORTACION'},
            {'operacion': 'VENTA', 'cantidad': '1', 'precio': '0', 'afectacion': 'GRATUITO', 'bonificacion': True},
        ],
    },
    {
        'id': 'nc_descuento_compra',
        'descripcion': 'Nota de crédito de compra (descuento, ajuste de valor) sobre una factura.',
        'clase': 'COMPRA', 'tipo': 'NC', 'moneda': 'PEN', 'fecha': '2026-01-16', 'tasa_pct': '18.00',
        'origen': 'COMPRA',
        'lineas': [{'operacion': 'NC_DESCUENTO_COMPRA', 'cantidad': '1', 'precio': '3.456789', 'afectacion': 'GRAVADO'}],
    },
    {
        'id': 'nd_cargo_venta',
        'descripcion': 'Nota de débito de venta (cargo, ajuste de valor) sobre una factura.',
        'clase': 'VENTA', 'tipo': 'ND', 'moneda': 'PEN', 'fecha': '2026-01-16', 'tasa_pct': '18.00',
        'origen': 'VENTA', 'requiere_stock': True,
        'lineas': [{'operacion': 'ND_CARGO_VENTA', 'cantidad': '1', 'precio': '12.3456', 'afectacion': 'GRAVADO'}],
    },
]


def esperado(caso):
    tasa = D(caso['tasa_pct']) / D(100)
    lineas, subtotal, igv_total = [], D(0), D(0)
    for l in caso['lineas']:
        cant, precio = D(l['cantidad']), D(l['precio'])
        base = precio * cant
        if l['afectacion'] == 'GRAVADO':
            igv = (base * tasa).quantize(Q2, rounding=ROUND_HALF_UP)
        else:
            igv = D(0)  # sin IGV, o gratuito/bonificación (precio 0)
        cbase = (cant * D(l.get('factor', '1'))).quantize(Q6, rounding=ROUND_HALF_UP)
        lineas.append({
            'igv': f'{igv.quantize(Q8):f}',
            'cantidad_base': f'{cbase.quantize(Q8):f}',
            'importe': f'{base.quantize(Q8, rounding=ROUND_HALF_UP):f}',
        })
        subtotal += base
        igv_total += igv
    total = subtotal + igv_total
    q = lambda x: f'{x.quantize(Q8, rounding=ROUND_HALF_UP):f}'  # noqa: E731
    return {
        'lineas': lineas, 'subtotal': q(subtotal), 'igv': q(igv_total), 'total': q(total),
        # Lo que se muestra con 2 decimales (después de redondear a 8, como el backend).
        'total_2d': f'{D(q(total)).quantize(Q2, rounding=ROUND_HALF_UP):f}',
        'subtotal_2d': f'{D(q(subtotal)).quantize(Q2, rounding=ROUND_HALF_UP):f}',
    }


def main():
    salida = []
    for caso in CASOS:
        salida.append({**caso, 'esperado': esperado(caso)})
    destino = Path(__file__).with_name('casos_documentos.json')
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(salida)} casos → {destino}')


if __name__ == '__main__':
    main()
