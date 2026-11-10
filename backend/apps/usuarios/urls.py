from django.urls import path
from apps.usuarios.views import (
    CsrfView,
    LoginView,
    LogoutView,
    MeView,
    AsignacionesView,
    UsuarioGestionListCreateView,
    UsuarioGestionDetailView,
    UsuarioResetPasswordView,
    CambiarPasswordView,
)

app_name = 'usuarios'

urlpatterns = [
    path('', UsuarioGestionListCreateView.as_view(), name='usuario-list-create'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('csrf/', CsrfView.as_view(), name='csrf'),
    path('me/', MeView.as_view(), name='me'),
    path('asignaciones/', AsignacionesView.as_view(), name='asignaciones'),
    path('cambiar-password/', CambiarPasswordView.as_view(), name='cambiar-password'),
    path('<int:pk>/', UsuarioGestionDetailView.as_view(), name='usuario-detail'),
    path('<int:pk>/reset-password/', UsuarioResetPasswordView.as_view(), name='usuario-reset-password'),
]
