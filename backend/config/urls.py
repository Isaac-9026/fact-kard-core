from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.health import health
from apps.consulta_ruc.views import ConsultaRucEstadoView, ConsultaRucView

urlpatterns = [
    path('api/health/', health, name='health'),
    path('api/usuarios/', include('apps.usuarios.urls')),
    path('api/empresas/', include('apps.empresas.urls')),
    path('api/catalogos/', include('apps.catalogos.urls')),
    path('api/inventario/', include('apps.inventario.urls')),
    path('api/documentos/', include('apps.documentos.urls')),
    path('api/kardex/', include('apps.kardex.urls')),
    path('api/auditoria/', include('apps.auditoria.urls')),
    path('api/reportes/', include('apps.reportes.urls')),
    # Bloque 17C: consulta de datos fiscales por RUC (solo lectura, solo ADMIN, con límite de uso).
    path('api/consulta-ruc/<str:ruc>/', ConsultaRucView.as_view(), name='consulta-ruc'),
    # Bloque 17D: estado de la fuente de consulta RUC (solo metadatos del padrón, solo ADMIN).
    path('api/configuracion/consulta-ruc/estado/', ConsultaRucEstadoView.as_view(), name='consulta-ruc-estado'),
]

# Bloque 24: admin de Django (sin modelos registrados) solo con DJANGO_ADMIN_ENABLED (por defecto = DEBUG).
if settings.DJANGO_ADMIN_ENABLED:
    urlpatterns.insert(1, path('admin/', admin.site.urls))

# Bloque 8: Swagger/OpenAPI solo con API_DOCS_ENABLED=True (por defecto, solo en desarrollo).
if settings.API_DOCS_ENABLED:
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    ]
from django.conf.urls.static import static

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
