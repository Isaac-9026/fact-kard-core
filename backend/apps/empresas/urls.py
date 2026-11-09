from django.urls import path

from apps.empresas.views import (
    EmpresaEstadoView,
    ConfigEmpresaView,
    DatosFiscalesEmpresaView,
    ConfigIgvDetailView,
    ConfigIgvListCreateView,
    ConfigIgvPeriodoView,
    EmpresaListCreateView,
    EmpresaDetailView,
    EmpresaIdentidadActivaView,
    EstablecimientoDetailView,
    EstablecimientoListCreateView,
    PeriodoCerrarView,
    PeriodoListCreateView,
    PeriodoReabrirView,
    CierrePeriodoListView,
    CompararCierresView,
)


urlpatterns = [
    path('', EmpresaListCreateView.as_view(), name='empresa-list-create'),
    path('identidad/', EmpresaIdentidadActivaView.as_view(), name='empresa-identidad-activa'),
    path('<int:pk>/', EmpresaDetailView.as_view(), name='empresa-detail'),
    path('<int:pk>/estado/', EmpresaEstadoView.as_view(), name='empresa-estado'),  # Bloque 24
    path('<int:pk>/identidad/', EmpresaDetailView.as_view(), name='empresa-identidad-detail'),
    path('config/', ConfigEmpresaView.as_view(), name='empresa-config'),
    path('datos-fiscales/', DatosFiscalesEmpresaView.as_view(), name='empresa-datos-fiscales'),
    path('establecimientos/', EstablecimientoListCreateView.as_view(), name='establecimiento-list-create'),
    path('establecimientos/<int:pk>/', EstablecimientoDetailView.as_view(), name='establecimiento-detail'),
    path('periodos/', PeriodoListCreateView.as_view(), name='periodo-list-create'),
    path('periodos/<int:pk>/cerrar/', PeriodoCerrarView.as_view(), name='periodo-cerrar'),
    path('periodos/<int:pk>/reabrir/', PeriodoReabrirView.as_view(), name='periodo-reabrir'),
    path('cierres/', CierrePeriodoListView.as_view(), name='cierre-list'),
    path('periodos/<int:pk>/comparar-cierres/', CompararCierresView.as_view(), name='comparar-cierres'),
    path('periodos/<int:periodo_id>/igv/', ConfigIgvPeriodoView.as_view(), name='periodo-config-igv'),
    path('config-igv/', ConfigIgvListCreateView.as_view(), name='config-igv-list-create'),
    path('config-igv/<int:pk>/', ConfigIgvDetailView.as_view(), name='config-igv-detail'),
]
