"""
Bloque 17A — catálogos 09 (tipo de nota de crédito) y 10 (tipo de nota de débito) SUNAT.

Fuente: Anexo 8 de la R.S. 097-2012/SUNAT (catálogos del Anexo E, R.S. 245-2017/SUNAT) y
modificatorias (09: códigos 11-13). Inactivos los que el sistema aún no soporta:
- 12 (IVAP): la tasa del IVAP no está implementada.
- 13 (corrección del monto neto pendiente de pago y/o fechas de vencimiento): nota sin importe
  que solo corrige cuotas; requiere un flujo propio que no existe todavía.
"""
CATALOGO_09 = (
    ('01', 'Anulación de la operación', True),
    ('02', 'Anulación por error en el RUC', True),
    ('03', 'Corrección por error en la descripción', True),
    ('04', 'Descuento global', True),
    ('05', 'Descuento por ítem', True),
    ('06', 'Devolución total', True),
    ('07', 'Devolución por ítem', True),
    ('08', 'Bonificación', True),
    ('09', 'Disminución en el valor', True),
    ('10', 'Otros conceptos', True),
    ('11', 'Ajustes de operaciones de exportación', True),
    ('12', 'Ajustes afectos al IVAP', False),
    ('13', 'Corrección del monto neto pendiente de pago y/o fechas de vencimiento', False),
)
CATALOGO_10 = (
    ('01', 'Intereses por mora', True),
    ('02', 'Aumento en el valor', True),
    ('03', 'Penalidades / otros conceptos', True),
)
MOTIVOS_NOTA = {'09': CATALOGO_09, '10': CATALOGO_10}
