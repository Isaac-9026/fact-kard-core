import os
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.catalogos.models import TipoComprobante, TipoExistencia, TipoOperacion, UnidadMedida
from apps.documentos.models import Documento
from apps.documentos.services import confirmar_documento_validacion, crear_documento, revisar_documento
from apps.empresas.models import Empresa, Periodo
from apps.inventario.models import Almacen, Producto, ProductoUnidad, SaldoInicial, Tercero
from apps.inventario.services import confirmar_saldo_inicial
from apps.kardex.models import Movimiento, SaldoCppActual, StockAlmacen
from apps.usuarios.models import Usuario


class Command(BaseCommand):
    help = 'SOLO DESARROLLO (DEBUG=True): carga inventario inicial y diez ventas demo confirmadas hasta Kardex.'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('seed_demo_ventas solo se permite en desarrollo (DEBUG=True). Nunca en producción.')
        empresa = Empresa.objects.get(ruc='20123456789')
        usuario = Usuario.objects.get(username=(os.environ.get('DEMO_USERNAME') or 'admin_demo').strip())
        establecimiento = empresa.establecimientos.get(codigo_sunat='0000')

        periodo, _ = Periodo.objects.update_or_create(
            empresa=empresa,
            anio=2026,
            mes=11,
            defaults={
                'orden': 202611,
                'fecha_inicio': date(2026, 11, 1),
                'fecha_fin': date(2026, 11, 30),
                'estado': 'ABIERTO',
            },
        )
        almacen, _ = Almacen.objects.get_or_create(
            empresa=empresa,
            codigo='ALM-01',
            defaults={'establecimiento': establecimiento, 'nombre': 'Almacén Principal', 'activo': True},
        )
        cliente, _ = Tercero.objects.get_or_create(
            empresa=empresa,
            tipo_documento='6',
            numero_documento='20666000111',
            defaults={
                'razon_social': 'CLIENTE COMERCIAL DEMO S.A.C.',
                'nombre_comercial': 'CLIENTE DEMO',
                'direccion': 'Av. Principal 123, Lima',
                'es_cliente': True,
            },
        )
        tipo_existencia = TipoExistencia.objects.get(codigo='01')
        unidad = UnidadMedida.objects.get(codigo='NIU')
        producto, _ = Producto.objects.get_or_create(
            empresa=empresa,
            codigo_interno='PROD-DEMO-001',
            defaults={
                'descripcion': 'PRODUCTO DEMOSTRACIÓN FACT-KARD',
                'tipo_existencia_codigo': tipo_existencia,
                'precio_venta_sugerido': Decimal('35.00'),
                'afectacion_igv_defecto': 'GRAVADO',
            },
        )
        producto_unidad, _ = ProductoUnidad.objects.get_or_create(
            producto=producto,
            unidad_codigo=unidad,
            defaults={'factor_a_base': Decimal('1.00000000'), 'es_base': True},
        )

        saldo_inicial, creado = SaldoInicial.objects.get_or_create(
            empresa=empresa,
            periodo=periodo,
            almacen=almacen,
            producto=producto,
            defaults={
                'cantidad': Decimal('100.00000000'),
                'valor_pen': Decimal('2000.00000000'),
                'cpp_inicial': Decimal('20.00000000'),
                'estado': 'BORRADOR',
                'creado_por': usuario,
            },
        )
        if creado or saldo_inicial.estado == 'BORRADOR':
            confirmar_saldo_inicial(saldo_id=saldo_inicial.id, empresa_id=empresa.id, usuario=usuario)

        factura = TipoComprobante.objects.get(codigo_sunat='01')
        operacion_venta = TipoOperacion.objects.get(codigo_interno='VENTA')
        creadas = 0
        for numero in range(1, 11):
            numero_texto = f'{numero:08d}'
            existente = Documento.objects.filter(
                empresa=empresa,
                ruc_emisor=empresa.ruc,
                tipo_comprobante=factura,
                serie_normalizada='FDEM',
                numero_normalizado=str(numero),
            ).first()
            if existente:
                continue

            cantidad = Decimal('5.00000000')
            precio = Decimal(34 + numero).quantize(Decimal('0.00000001'))
            igv = (cantidad * precio * Decimal('0.18')).quantize(Decimal('0.00000001'))
            documento = crear_documento(
                empresa_id=empresa.id,
                usuario_id=usuario.id,
                datos_cabecera={
                    'clase': 'VENTA',
                    'periodo': periodo.id,
                    'tercero': cliente.id,
                    'tipo_comprobante': factura.id,
                    'serie': 'FDEM',
                    'numero': numero_texto,
                    'fecha_emision': date(2026, 11, numero + 1),
                    'moneda_codigo': 'PEN',
                    'condicion_pago': 'CONTADO',
                    'origen_captura': 'MANUAL',
                },
                detalles_datos=[{
                    'producto': producto.id,
                    'producto_unidad': producto_unidad.id,
                    'almacen': almacen.id,
                    'tipo_operacion': operacion_venta.id,
                    'descripcion_original': producto.descripcion,
                    'cantidad_original': cantidad,
                    'precio_unitario': precio,
                    'igv': igv,
                    'afectacion_igv': 'GRAVADO',
                    'codigo_afectacion_igv': '10',
                }],
            )
            revisar_documento(
                documento_id=documento.id,
                empresa_id=empresa.id,
                usuario_id=usuario.id,
                nuevo_estado_revision='REVISADO',
            )
            confirmar_documento_validacion(
                documento_id=documento.id,
                empresa_id=empresa.id,
                usuario_id=usuario.id,
            )
            creadas += 1

        ventas = Documento.objects.filter(empresa=empresa, clase='VENTA', estado='CONFIRMADO').count()
        movimientos = Movimiento.objects.filter(empresa=empresa, producto=producto).count()
        stock = StockAlmacen.objects.get(empresa=empresa, almacen=almacen, producto=producto)
        saldo = SaldoCppActual.objects.get(empresa=empresa, producto=producto)
        self.stdout.write(self.style.SUCCESS(
            f'Demo lista: {creadas} ventas nuevas, {ventas} ventas confirmadas, '
            f'{movimientos} movimientos Kardex, stock {stock.cantidad_actual}, CPP S/ {saldo.cpp_pen}.'
        ))
