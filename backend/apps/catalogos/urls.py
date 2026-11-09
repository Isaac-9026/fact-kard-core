from django.urls import path

from apps.catalogos.views import (
    MonedaListView,
    TipoComprobanteListView,
    TipoOperacionListView,
    TipoExistenciaListView,
    UnidadMedidaListView,
    MetodoPagoListView,
    MotivoNotaListView,
    AfectacionIgvCatalogoView,
    TipoCambioListCreateView,
    TipoCambioResolverView,
)


urlpatterns = [
    path('monedas/', MonedaListView.as_view(), name='moneda-list'),
    path('tipos-comprobante/', TipoComprobanteListView.as_view(), name='tipo-comprobante-list'),
    path('tipos-operacion/', TipoOperacionListView.as_view(), name='tipo-operacion-list'),
    path('tipos-existencia/', TipoExistenciaListView.as_view(), name='tipo-existencia-list'),
    path('metodos-pago/', MetodoPagoListView.as_view(), name='metodo-pago-list'),
    path('motivos-nota/', MotivoNotaListView.as_view(), name='motivo-nota-list'),
    path('afectaciones-igv/', AfectacionIgvCatalogoView.as_view(), name='afectacion-igv-catalogo'),
    path('unidades-medida/', UnidadMedidaListView.as_view(), name='unidad-medida-list'),
    path('tipos-cambio/', TipoCambioListCreateView.as_view(), name='tipo-cambio-list-create'),
    path('tipo-cambio/resolver/', TipoCambioResolverView.as_view(), name='tipo-cambio-resolver'),
]
