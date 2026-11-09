"""
Bloque 6 — utilidades comunes de la API.

- Validación de query params: un valor inválido responde 400 con un mensaje claro
  (antes: ValueError / DataError → 500). No se capturan errores reales del servidor.
- Paginación OPCIONAL: solo se pagina si el cliente envía `page` o `page_size`, para no
  romper a los clientes actuales que esperan la lista completa.
"""
from datetime import date

from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination

ENTERO_MAXIMO = 2_147_483_647  # rango de IntegerField/AutoField en PostgreSQL


def entero_param(params, *nombres, minimo=1, requerido=False):
    """Primer parámetro presente entre `nombres`, como entero positivo; None si no hay."""
    nombre, valor = next(((n, params.get(n)) for n in nombres if params.get(n) not in (None, '')), (nombres[0], None))
    if valor is None:
        if requerido:
            raise ValidationError({nombre: 'Este parámetro es obligatorio.'})
        return None
    texto = str(valor).strip()
    if not texto.lstrip('-').isdigit():
        raise ValidationError({nombre: f"'{valor}' no es un número entero válido."})
    numero = int(texto)
    if numero < minimo or numero > ENTERO_MAXIMO:
        raise ValidationError({nombre: f'Debe ser un entero entre {minimo} y {ENTERO_MAXIMO}.'})
    return numero


def fecha_param(params, nombre, requerido=False):
    valor = params.get(nombre)
    if valor in (None, ''):
        if requerido:
            raise ValidationError({nombre: 'Este parámetro es obligatorio.'})
        return None
    try:
        return date.fromisoformat(str(valor).strip())
    except ValueError:
        raise ValidationError({nombre: f"'{valor}' no es una fecha válida (AAAA-MM-DD)."})


def opcion_param(params, nombre, opciones):
    valor = params.get(nombre)
    if valor in (None, ''):
        return None
    valor = str(valor).strip().upper()
    if valor not in opciones:
        raise ValidationError({nombre: f"Valor no permitido. Opciones: {', '.join(sorted(opciones))}."})
    return valor


class PaginacionOpcional(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500

    def paginate_queryset(self, queryset, request, view=None):
        params = request.query_params
        if 'page' not in params and 'page_size' not in params:
            return None  # compatibilidad: lista completa
        # Valores no numéricos → 400 (DRF devolvería 404 o ignoraría el valor).
        entero_param(params, 'page')
        entero_param(params, 'page_size')
        return super().paginate_queryset(queryset, request, view)


def paginar_lista(request, items, view=None):
    """
    Pagina una lista ya calculada (p. ej. filas del Kardex). Devuelve (items, meta) donde
    meta es None si el cliente no pidió paginación.
    """
    paginador = PaginacionOpcional()
    pagina = paginador.paginate_queryset(items, request, view)
    if pagina is None:
        return items, None
    return pagina, {
        'count': paginador.page.paginator.count,
        'page': paginador.page.number,
        'page_size': paginador.get_page_size(request),
        'num_pages': paginador.page.paginator.num_pages,
        'next': paginador.get_next_link(),
        'previous': paginador.get_previous_link(),
    }
