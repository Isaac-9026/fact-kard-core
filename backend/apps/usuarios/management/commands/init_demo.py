import os

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalogos.models import Moneda
from apps.empresas.models import ConfigEmpresa, Empresa, Establecimiento
from apps.usuarios.models import Usuario, UsuarioEmpresa


class Command(BaseCommand):
    help = 'SOLO DESARROLLO (DEBUG=True): crea idempotentemente una empresa y un administrador demo.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('init_demo solo se permite en desarrollo (DEBUG=True). Nunca en producción.')
        username = (os.environ.get('DEMO_USERNAME') or 'admin_demo').strip()
        password = os.environ.get('DEMO_PASSWORD', '')
        if not password:
            raise CommandError('Define DEMO_PASSWORD (en el .env de la raíz) para crear el usuario demo.')
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError('DEMO_PASSWORD no es válida: ' + ' '.join(exc.messages)) from exc
        moneda = Moneda.objects.get(codigo='PEN')

        empresa, _ = Empresa.objects.get_or_create(
            ruc='20123456789',
            defaults={
                'razon_social': 'FACT-KARD DEMO S.A.C.',
                'nombre_comercial': 'FACT-KARD DEMO',
                'direccion': 'Lima, Perú',
                'moneda_base_codigo': moneda,
            },
        )
        establecimiento, _ = Establecimiento.objects.get_or_create(
            empresa=empresa,
            codigo_sunat='0000',
            defaults={'nombre': 'Principal', 'direccion': empresa.direccion},
        )
        configuracion, _ = ConfigEmpresa.objects.get_or_create(empresa=empresa)
        if configuracion.establecimiento_principal_id != establecimiento.id:
            configuracion.establecimiento_principal = establecimiento
            configuracion.save(update_fields=['establecimiento_principal'])

        usuario, creado = Usuario.objects.get_or_create(
            username=username,
            defaults={
                'email': 'admin_demo@factkard.local',
                'password_hash': '',
                'es_admin_global': True,
                'activo': True,
            },
        )
        if creado or not usuario.check_password(password):
            usuario.set_password(password)
            usuario.es_admin_global = True
            usuario.activo = True
            usuario.save(update_fields=['password_hash', 'es_admin_global', 'activo'])

        UsuarioEmpresa.objects.update_or_create(
            usuario=usuario,
            empresa=empresa,
            defaults={'rol': 'ADMIN', 'activo': True},
        )
        self.stdout.write(self.style.SUCCESS(f'Usuario demo listo: {username}'))
