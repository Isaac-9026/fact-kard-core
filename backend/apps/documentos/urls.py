from django.urls import path
from apps.documentos.views import (
    DocumentoListCreateView,
    DocumentoDetailView,
    DocumentoRevisarView,
    DocumentoConfirmarView,
    DocumentoAnularView,
    DocumentoCapturaSubirView,
    DocumentoCapturaListView,
    DocumentoCapturaDetailView,
    CapturaCampoCorregirView,
    DocumentoCapturaGenerarBorradorView,
    SerieComprobanteListCreateView,
    SerieComprobanteDetailView,
    DocumentoCondicionPagoView,
    DocumentoValidacionElectronicaView,
    DocumentoMotivoNotaView,
    DetalleCodigoAfectacionView,
    PagoDocumentoListCreateView,
    PagoDocumentoAnularView,
    CuentasPorCobrarView,
    CuentasPorPagarView,
)
from django.conf import settings

urlpatterns = [
    path('', DocumentoListCreateView.as_view(), name='documento-list-create'),
    path('capturas/', DocumentoCapturaListView.as_view(), name='documento-captura-list'),
    path('capturas/subir/', DocumentoCapturaSubirView.as_view(), name='documento-captura-subir'),
    path('capturas/<int:pk>/', DocumentoCapturaDetailView.as_view(), name='documento-captura-detail'),
    path('capturas/<int:pk>/corregir-campo/', CapturaCampoCorregirView.as_view(), name='captura-campo-corregir'),
    path('capturas/<int:pk>/generar-borrador/', DocumentoCapturaGenerarBorradorView.as_view(), name='documento-captura-generar-borrador'),
    # Bloque 16
    path('series/', SerieComprobanteListCreateView.as_view(), name='serie-comprobante-list-create'),
    path('series/<int:pk>/', SerieComprobanteDetailView.as_view(), name='serie-comprobante-detail'),
    path('pagos/', PagoDocumentoListCreateView.as_view(), name='pago-documento-list-create'),
    path('pagos/<int:pk>/anular/', PagoDocumentoAnularView.as_view(), name='pago-documento-anular'),
    path('cuentas-por-cobrar/', CuentasPorCobrarView.as_view(), name='cuentas-por-cobrar'),
    path('cuentas-por-pagar/', CuentasPorPagarView.as_view(), name='cuentas-por-pagar'),
    path('<int:pk>/condicion-pago/', DocumentoCondicionPagoView.as_view(), name='documento-condicion-pago'),
    # Bloque 17A: preparación tributaria (solo lectura) y motivo de nota.
    path('<int:pk>/validacion-electronica/', DocumentoValidacionElectronicaView.as_view(),
         name='documento-validacion-electronica'),
    path('<int:pk>/motivo-nota/', DocumentoMotivoNotaView.as_view(), name='documento-motivo-nota'),
    path('<int:pk>/detalles/<int:detalle_id>/codigo-afectacion/', DetalleCodigoAfectacionView.as_view(),
         name='documento-detalle-codigo-afectacion'),
    path('<int:pk>/', DocumentoDetailView.as_view(), name='documento-detail'),
    path('<int:pk>/revisar/', DocumentoRevisarView.as_view(), name='documento-revisar'),
    path('<int:pk>/confirmar/', DocumentoConfirmarView.as_view(), name='documento-confirmar'),
    path('<int:pk>/anular/', DocumentoAnularView.as_view(), name='documento-anular'),
]

if 'apps.emision_electronica' in settings.INSTALLED_APPS:
    from apps.emision_electronica.views import (
        DocumentoDescargarXmlFirmadoView, DocumentoDescargarXmlView, DocumentoFirmarXmlView, DocumentoGenerarXmlView,
        BandejaSunatView, DocumentoConsultarSunatView, DocumentoDescargarCdrView, DocumentoEnviarSunatView, DocumentoPrepararEmisionView,
        DocumentoDescargarPdfView, DocumentoDescargarZipView, DocumentoGenerarPdfView,
    )
    from apps.emision_electronica.lotes.views import (
        DocumentoComunicarBajaView, ResumenSunatConsultarView, ResumenSunatDetailView, ResumenSunatEnviarView,
        ResumenSunatGenerarView, ResumenSunatListView,
    )
    urlpatterns += [
        path('emision-electronica/bandeja/', BandejaSunatView.as_view(), name='bandeja-sunat'),
        path('emision-electronica/resumenes/', ResumenSunatListView.as_view(), name='resumen-sunat-list'),
        path('emision-electronica/resumenes/generar/', ResumenSunatGenerarView.as_view(), name='resumen-sunat-generar'),
        path('emision-electronica/resumenes/<int:pk>/', ResumenSunatDetailView.as_view(), name='resumen-sunat-detail'),
        path('emision-electronica/resumenes/<int:pk>/enviar/', ResumenSunatEnviarView.as_view(), name='resumen-sunat-enviar'),
        path('emision-electronica/resumenes/<int:pk>/consultar/', ResumenSunatConsultarView.as_view(), name='resumen-sunat-consultar'),
        path('<int:pk>/emision-electronica/preparar/', DocumentoPrepararEmisionView.as_view(), name='documento-preparar-emision'),
        path('<int:pk>/emision-electronica/generar-xml/', DocumentoGenerarXmlView.as_view(), name='documento-generar-xml'),
        path('<int:pk>/emision-electronica/xml/', DocumentoDescargarXmlView.as_view(), name='documento-descargar-xml'),
        path('<int:pk>/emision-electronica/firmar/', DocumentoFirmarXmlView.as_view(), name='documento-firmar-xml'),
        path('<int:pk>/emision-electronica/xml-firmado/', DocumentoDescargarXmlFirmadoView.as_view(), name='documento-descargar-xml-firmado'),
        path('<int:pk>/emision-electronica/enviar-sunat/', DocumentoEnviarSunatView.as_view(), name='documento-enviar-sunat'),
        path('<int:pk>/emision-electronica/consultar-sunat/', DocumentoConsultarSunatView.as_view(), name='documento-consultar-sunat'),
        path('<int:pk>/comunicar-baja/', DocumentoComunicarBajaView.as_view(), name='documento-comunicar-baja'),
        path('<int:pk>/emision-electronica/cdr/', DocumentoDescargarCdrView.as_view(), name='documento-descargar-cdr'),
        path('<int:pk>/emision-electronica/generar-pdf/', DocumentoGenerarPdfView.as_view(), name='documento-generar-pdf'),
        path('<int:pk>/emision-electronica/pdf/', DocumentoDescargarPdfView.as_view(), name='documento-descargar-pdf'),
        path('<int:pk>/emision-electronica/zip/', DocumentoDescargarZipView.as_view(), name='documento-descargar-zip'),
    ]
