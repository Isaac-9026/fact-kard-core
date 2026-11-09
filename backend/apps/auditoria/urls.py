from django.urls import path
from apps.auditoria.views import AuditoriaGlobalListView, AuditoriaListView

app_name = 'auditoria'

urlpatterns = [
    path('', AuditoriaListView.as_view(), name='auditoria-list'),
    path('global/', AuditoriaGlobalListView.as_view(), name='auditoria-global'),  # Bloque 24: solo admin global
]
