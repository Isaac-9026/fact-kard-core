from django.urls import path
from apps.usuarios.views import CsrfView, LoginView, LogoutView, MeView, AsignacionesView

app_name = 'usuarios'

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('csrf/', CsrfView.as_view(), name='csrf'),
    path('me/', MeView.as_view(), name='me'),
    path('asignaciones/', AsignacionesView.as_view(), name='asignaciones'),
]
