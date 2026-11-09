from django.core.management.base import BaseCommand
from apps.catalogos.models import (
    Moneda,
    TipoExistencia,
    UnidadMedida,
    TipoComprobante,
    TipoOperacion,
    MotivoNota,
)
from apps.catalogos.motivos_nota import MOTIVOS_NOTA


class Command(BaseCommand):
    help = 'Puebla de forma idempotente las tablas de catálogos oficiales SUNAT para FACT-KARD.'

    def handle(self, *args, **options):
        # 1. Monedas
        monedas = {
            'PEN': 'Soles',
            'USD': 'Dólares Americanos',
        }
        for codigo, nombre in monedas.items():
            Moneda.objects.update_or_create(codigo=codigo, defaults={'nombre': nombre})

        # 2. TipoExistencia (Tabla 5 SUNAT)
        tipos_existencia = [
            ('01', 'MERCADERIAS'),
            ('02', 'PRODUCTOS TERMINADOS'),
            ('03', 'MATERIAS PRIMAS'),
            ('05', 'ENVASES Y EMBALAJES'),
            ('06', 'MATERIALES AUXILIARES Y SUMINISTROS'),
            ('99', 'OTROS'),
        ]
        for codigo, descripcion in tipos_existencia:
            TipoExistencia.objects.update_or_create(codigo=codigo, defaults={'descripcion': descripcion})

        # 3. UnidadMedida (Tabla 6 SUNAT)
        unidades_medida = [
            ('NIU', 'UNIDADES'),
            ('BX', 'CAJAS'),
            ('PK', 'PAQUETES'),
            ('KGM', 'KILOGRAMOS'),
            ('LTR', 'LITROS'),
            ('GLI', 'GALONES'),
            ('ZZ', 'SERVICIO / OTROS'),
        ]
        for codigo, descripcion in unidades_medida:
            UnidadMedida.objects.update_or_create(codigo=codigo, defaults={'descripcion': descripcion})

        # 4. TipoComprobante (Tabla 10 SUNAT)
        tipos_comprobante = [
            ('01', 'FACTURA', False, 'NINGUNO'),
            ('03', 'BOLETA DE VENTA', False, 'NINGUNO'),
            ('07', 'NOTA DE CREDITO', True, 'CREDITO'),
            ('08', 'NOTA DE DEBITO', True, 'DEBITO'),
            ('00', 'OTROS', False, 'NINGUNO'),
        ]
        for codigo, descripcion, es_nota, efecto in tipos_comprobante:
            TipoComprobante.objects.update_or_create(
                codigo_sunat=codigo,
                defaults={
                    'descripcion': descripcion,
                    'es_nota': es_nota,
                    'efecto_nota': efecto,
                    'activo': True,
                }
            )

        # 5. TipoOperacion (Tabla 12 SUNAT + internas)
        # Fuente: Tabla 12 "Tipo de operación", Anexo 3 de la R.S. 169-2015/SUNAT (PLE).
        # Interpretación revisada en el Bloque 4 (ver catalogos/tests_b4_tabla12.py):
        # - 05 DEVOLUCION RECIBIDA (entrada) → devolución del cliente; 06 DEVOLUCION
        #   ENTREGADA (salida) → devolución al proveedor. No están invertidos. La tabla
        #   también tiene 24/25 (entrada por devolución del cliente / salida por devolución
        #   al proveedor), más específicos; no se cambian sin decisión contable.
        # - 22/23 (entrada/salida por identificación errónea) corrigen un bien mal
        #   identificado; no representan la anulación de un comprobante. Los extornos por
        #   anulación usan 99 OTROS.
        tipos_operacion = [
            ('SALDO_INICIAL', '16', 'SALDO INICIAL', 'ENTRADA', False, True, 'SALDO_INICIAL'),
            ('COMPRA', '02', 'COMPRA NACIONAL', 'ENTRADA', False, True, 'DOCUMENTO'),
            ('VENTA', '01', 'VENTA NACIONAL', 'SALIDA', False, True, 'DOCUMENTO'),
            ('BONIFICACION', '99', 'BONIFICACION RECIBIDA', 'ENTRADA', False, True, 'DOCUMENTO'),
            ('DEVOLUCION_VENTA', '05', 'DEVOLUCION DE VENTA', 'ENTRADA', False, True, 'MOV_ORIGEN'),
            ('DEVOLUCION_COMPRA', '06', 'DEVOLUCION A PROVEEDOR', 'SALIDA', False, True, 'MOV_ORIGEN'),
            ('NC_DESCUENTO_COMPRA', '99', 'DESCUENTO EN COMPRA (AJUSTE VALOR)', 'AJUSTE_VALOR', False, True, 'DOCUMENTO'),
            ('ND_CARGO_COMPRA', '99', 'CARGO EN COMPRA (AJUSTE VALOR)', 'AJUSTE_VALOR', False, True, 'DOCUMENTO'),
            ('NC_VENTA_SIN_DEVOLUCION', '99', 'DESCUENTO EN VENTA SIN DEVOLUCION', 'AJUSTE_VALOR', False, False, 'DOCUMENTO'),
            # Bloque 3: cargo en venta (ND); no afecta el costo del inventario.
            ('ND_CARGO_VENTA', '99', 'CARGO EN VENTA (NOTA DE DEBITO)', 'AJUSTE_VALOR', False, False, 'DOCUMENTO'),
            ('MERMA', '13', 'MERMA DE INVENTARIO', 'SALIDA', True, True, 'NOTA_INTERNA'),
            ('DESMEDRO', '14', 'DESMEDRO DE INVENTARIO', 'SALIDA', True, True, 'NOTA_INTERNA'),
            ('CONSUMO_INTERNO', '10', 'CONSUMO INTERNO', 'SALIDA', True, True, 'NOTA_INTERNA'),
            ('RETIRO', '12', 'RETIRO DE BIENES', 'SALIDA', True, True, 'NOTA_INTERNA'),
            ('AJUSTE_INGRESO', '99', 'AJUSTE POR SOBRANTE FISICO', 'ENTRADA', True, True, 'NOTA_INTERNA'),
            ('AJUSTE_SALIDA', '99', 'AJUSTE POR FALTANTE FISICO', 'SALIDA', True, True, 'NOTA_INTERNA'),
            ('AJUSTE_VALOR_MANUAL', '99', 'AJUSTE MANUAL DE VALORIZACION', 'AJUSTE_VALOR', True, True, 'NOTA_INTERNA'),
            ('TRANSFERENCIA_SALIDA', '11', 'TRANSFERENCIA ENTRE ALMACENES (SALIDA)', 'SALIDA', True, True, 'TRANSFERENCIA'),
            ('TRANSFERENCIA_ENTRADA', '21', 'TRANSFERENCIA ENTRE ALMACENES (ENTRADA)', 'ENTRADA', True, True, 'TRANSFERENCIA'),
            ('RESIDUO_AUTOMATICO', '99', 'AJUSTE AUTOMATICO DE RESIDUO', 'AJUSTE_VALOR', True, True, 'MOTOR'),
            # BE-005: extornos por anulación. Tabla 12 no tiene código específico → 99 (OTROS).
            ('EXTORNO_ENTRADA', '99', 'EXTORNO POR ANULACION (ENTRADA)', 'ENTRADA', True, True, 'MOV_EXTORNADO'),
            ('EXTORNO_SALIDA', '99', 'EXTORNO POR ANULACION (SALIDA)', 'SALIDA', True, True, 'MOV_EXTORNADO'),
            ('EXTORNO_AJUSTE_VALOR', '99', 'EXTORNO POR ANULACION (AJUSTE DE VALOR)', 'AJUSTE_VALOR', True, True, 'MOV_EXTORNADO'),
        ]
        for cod_int, cod_sun, desc, nat, interna, afecta, origen in tipos_operacion:
            TipoOperacion.objects.update_or_create(
                codigo_interno=cod_int,
                defaults={
                    'codigo_sunat': cod_sun,
                    'descripcion': desc,
                    'naturaleza': nat,
                    'es_interna': interna,
                    'afecta_kardex': afecta,
                    'origen_requerido': origen,
                    'activo': True,
                }
            )

        # 6. Bloque 17A: catálogos 09/10 (motivos de nota de crédito / débito)
        for catalogo, filas in MOTIVOS_NOTA.items():
            for codigo, descripcion, activo in filas:
                MotivoNota.objects.update_or_create(
                    catalogo=catalogo, codigo=codigo, defaults={'descripcion': descripcion, 'activo': activo})

        self.stdout.write(self.style.SUCCESS('Catálogos SUNAT poblados exitosamente.'))
