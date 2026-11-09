from django.urls import path

from apps.kardex.views import (
    IncidenciaListView, IncidenciaUpdateView, MovimientoListView,
    RecalculoListCreateView, SaldosActualesView,
)

urlpatterns = [
    path('movimientos/', MovimientoListView.as_view(), name='kardex-movimientos'),
    path('saldos-actuales/', SaldosActualesView.as_view(), name='kardex-saldos-actuales'),
    path('incidencias/', IncidenciaListView.as_view(), name='kardex-incidencias'),
    path('incidencias/<int:pk>/', IncidenciaUpdateView.as_view(), name='kardex-incidencia-detail'),
    path('recalculos/', RecalculoListCreateView.as_view(), name='kardex-recalculos'),
]
