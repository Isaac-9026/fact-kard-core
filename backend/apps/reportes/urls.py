from django.urls import path
from apps.reportes.views import (
    Formato131ExcelView, Formato131View, KardexExcelExportView,
    KardexReportView, PilotoComparadorView, RegistroComercialView,
)

urlpatterns = [
    path('kardex/', KardexReportView.as_view(), name='kardex-report'),
    path('kardex/excel/', KardexExcelExportView.as_view(), name='kardex-excel-export'),
    path('formato-13-1/', Formato131View.as_view(), name='formato-131'),
    path('formato-13-1/excel/', Formato131ExcelView.as_view(), name='formato-131-excel'),
    path('registro-ventas/', RegistroComercialView.as_view(clase='VENTA'), name='registro-ventas'),
    path('registro-ventas/excel/', RegistroComercialView.as_view(clase='VENTA', excel=True), name='registro-ventas-excel'),
    path('registro-compras/', RegistroComercialView.as_view(clase='COMPRA'), name='registro-compras'),
    path('registro-compras/excel/', RegistroComercialView.as_view(clase='COMPRA', excel=True), name='registro-compras-excel'),
    path('piloto-comparador/', PilotoComparadorView.as_view(), name='piloto-comparador'),
]
