"""
Bloque 10 — B10-08: inyección de fórmulas en los Excel exportados (CWE-1236).

openpyxl guarda como FÓRMULA cualquier texto que empiece con "=" (p. ej. un código o una
descripción de producto `=HYPERLINK("http://...")`). Los reportes del sistema no usan
fórmulas propias: antes de guardar, toda celda marcada como fórmula vuelve a ser texto
literal (se ve igual que en la pantalla y Excel no la evalúa).
"""


def neutralizar_formulas(libro):
    for hoja in libro.worksheets:
        for fila in hoja.iter_rows():
            for celda in fila:
                if celda.data_type == 'f':
                    celda.data_type = 's'
    return libro
