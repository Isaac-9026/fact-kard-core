from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.usuarios'

    def ready(self):
        # Bloque 7: advertencias de despliegue (manage.py check --deploy).
        from config import checks  # noqa: F401
