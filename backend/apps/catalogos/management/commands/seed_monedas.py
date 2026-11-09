from django.core.management.base import BaseCommand

from apps.catalogos.models import Moneda


class Command(BaseCommand):
    help = 'Crea o actualiza idempotentemente las monedas base de FACT-KARD.'

    def handle(self, *args, **options):
        monedas = {
            'PEN': 'Soles',
            'USD': 'Dólares Americanos',
        }

        for codigo, nombre in monedas.items():
            Moneda.objects.update_or_create(
                codigo=codigo,
                defaults={'nombre': nombre},
            )

        self.stdout.write(self.style.SUCCESS('Monedas PEN y USD disponibles.'))
