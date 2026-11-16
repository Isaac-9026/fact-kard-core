import re
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalogos.models import TipoExistencia, UnidadMedida
from apps.documentos.afectacion_igv import AFECTACIONES
from apps.inventario.models import Producto, ProductoEquivalencia, ProductoUnidad, Tercero
from apps.inventario.serializers import ProductoEquivalenciaSerializer, ProductoSerializer


def autogenerar_codigo_producto(empresa_id: int) -> str:
    """
    Busca códigos con formato PROD-XXXX en la empresa y devuelve el siguiente
    correlativo disponible sin colisionar con uq_producto_empresa_codigo.
    """
    codigos = Producto.objects.filter(
        empresa_id=empresa_id,
        codigo_interno__startswith='PROD-',
    ).values_list('codigo_interno', flat=True)

    max_num = 0
    for c in codigos:
        m = re.match(r'^PROD-(\d+)$', (c or '').strip(), re.IGNORECASE)
        if m:
            try:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num
            except ValueError:
                pass

    nuevo_num = max_num + 1
    nuevo_codigo = f"PROD-{nuevo_num:04d}"
    while Producto.objects.filter(empresa_id=empresa_id, codigo_interno=nuevo_codigo).exists():
        nuevo_num += 1
        nuevo_codigo = f"PROD-{nuevo_num:04d}"

    return nuevo_codigo


def ejecutar_alta_rapida_y_homologacion(*, empresa_id: int, usuario, datos: dict) -> dict:
    """
    Crea Producto + ProductoUnidad (base) + ProductoEquivalencia en 1 sola transacción atómica.
    Resuelve o registra al proveedor automáticamente si se envía 'captura'.
    """
    with transaction.atomic():
        # 1. Resolver Proveedor (Tercero)
        tercero_id = datos.get('tercero')
        captura_id = datos.get('captura')
        tercero = None

        if tercero_id not in (None, '', 'captura'):
            try:
                tercero = Tercero.objects.filter(pk=int(tercero_id), empresa_id=empresa_id).first()
            except (ValueError, TypeError):
                tercero = None
            if not tercero:
                raise ValidationError({'tercero': 'Proveedor no encontrado en esta empresa.'})
        elif captura_id:
            from apps.documentos.models import DocumentoCaptura
            from apps.inventario.homologacion import proveedor_de_captura
            try:
                captura = DocumentoCaptura.objects.filter(pk=int(captura_id), empresa_id=empresa_id).first()
            except (ValueError, TypeError):
                captura = None
            if not captura:
                raise ValidationError({'captura': 'Captura no encontrada para esta empresa.'})
            tercero = proveedor_de_captura(captura, crear=True)
            if not tercero:
                raise ValidationError({'captura': 'No se pudo determinar el proveedor emisor desde el comprobante.'})
        else:
            raise ValidationError({'tercero': 'Debe especificar el proveedor o el ID de la captura activa.'})

        # 2. Resolver Código Interno
        codigo_interno = (datos.get('codigo_interno') or '').strip().upper()
        if not codigo_interno:
            codigo_interno = autogenerar_codigo_producto(empresa_id)
        else:
            if Producto.objects.filter(empresa_id=empresa_id, codigo_interno=codigo_interno).exists():
                raise ValidationError({
                    'codigo_interno': f'Ya existe un producto con el código {codigo_interno} en esta empresa.'
                })

        # 3. Resolver Descripción
        descripcion = (datos.get('descripcion') or datos.get('descripcion_externa') or '').strip()
        if not descripcion:
            raise ValidationError({'descripcion': 'La descripción del producto es obligatoria.'})
        descripcion = descripcion[:250]

        # 4. Resolver Tipo de Existencia (Tabla 5 SUNAT, default '01')
        tipo_existencia_cod = (datos.get('tipo_existencia_codigo') or '01').strip()
        tipo_existencia = TipoExistencia.objects.filter(codigo=tipo_existencia_cod).first()
        if not tipo_existencia:
            raise ValidationError({
                'tipo_existencia_codigo': f'El tipo de existencia {tipo_existencia_cod} no existe en catálogo SUNAT.'
            })

        # 5. Resolver Unidad Base (Tabla 6 SUNAT, default unidad_externa_codigo o 'NIU')
        unidad_base_cod = (datos.get('unidad_base_codigo') or '').strip().upper()
        if not unidad_base_cod:
            und_ext = (datos.get('unidad_externa_codigo') or '').strip().upper()
            if und_ext and UnidadMedida.objects.filter(codigo=und_ext).exists():
                unidad_base_cod = und_ext
            else:
                unidad_base_cod = 'NIU'
        unidad_base = UnidadMedida.objects.filter(codigo=unidad_base_cod).first()
        if not unidad_base:
            raise ValidationError({
                'unidad_base_codigo': f'La unidad de medida {unidad_base_cod} no existe en catálogo SUNAT.'
            })

        # 6. Resolver Afectación IGV por defecto
        afectacion_raw = (datos.get('afectacion_igv_defecto') or 'GRAVADO').strip().upper()
        opciones_afectacion = dict(AFECTACIONES)
        if afectacion_raw in opciones_afectacion:
            afectacion_igv = afectacion_raw
        elif afectacion_raw in ('10', '18%', 'GRAVADA'):
            afectacion_igv = 'GRAVADO'
        elif afectacion_raw in ('20', 'EXONERADA'):
            afectacion_igv = 'EXONERADO'
        elif afectacion_raw in ('30', '40', 'INAFECTA'):
            afectacion_igv = 'INAFECTO'
        else:
            afectacion_igv = 'GRAVADO'

        # 7. Resolver Precio Venta Sugerido
        precio_sugerido_raw = datos.get('precio_venta_sugerido')
        precio_venta_sugerido = None
        if precio_sugerido_raw not in (None, ''):
            try:
                precio_venta_sugerido = Decimal(str(precio_sugerido_raw))
                if precio_venta_sugerido < 0:
                    raise ValidationError({'precio_venta_sugerido': 'El precio de venta sugerido no puede ser negativo.'})
            except (InvalidOperation, TypeError):
                raise ValidationError({'precio_venta_sugerido': 'Precio de venta sugerido numérico inválido.'})

        # 8. Resolver Factor de Conversión
        factor_raw = datos.get('factor_conversion')
        if factor_raw not in (None, ''):
            try:
                factor_conversion = Decimal(str(factor_raw))
                if factor_conversion <= 0:
                    raise ValidationError({'factor_conversion': 'El factor de conversión debe ser mayor a 0.'})
            except (InvalidOperation, TypeError):
                raise ValidationError({'factor_conversion': 'Factor de conversión numérico inválido.'})
        else:
            factor_conversion = Decimal('1.00000000')

        # 9. Crear Producto
        producto = Producto.objects.create(
            empresa_id=empresa_id,
            codigo_interno=codigo_interno,
            descripcion=descripcion,
            tipo_existencia_codigo=tipo_existencia,
            estado='ACTIVO',
            precio_venta_sugerido=precio_venta_sugerido,
            afectacion_igv_defecto=afectacion_igv,
        )

        # 10. Crear ProductoUnidad (Base)
        producto_unidad = ProductoUnidad.objects.create(
            producto=producto,
            unidad_codigo=unidad_base,
            factor_a_base=Decimal('1.00000000'),
            es_base=True,
        )

        # 11. Crear / Desactivar anterior ProductoEquivalencia
        codigo_externo = (datos.get('codigo_externo') or '').strip() or None
        descripcion_externa = (datos.get('descripcion_externa') or '').strip() or None
        unidad_externa_codigo_raw = (datos.get('unidad_externa_codigo') or '').strip().upper() or None
        unidad_externa = None
        if unidad_externa_codigo_raw:
            unidad_externa = UnidadMedida.objects.filter(codigo=unidad_externa_codigo_raw).first()

        if codigo_externo:
            ProductoEquivalencia.objects.filter(
                empresa_id=empresa_id,
                tercero=tercero,
                codigo_externo=codigo_externo,
                activa=True,
            ).update(activa=False)

        equivalencia = ProductoEquivalencia.objects.create(
            empresa_id=empresa_id,
            tercero=tercero,
            codigo_externo=codigo_externo,
            descripcion_externa=descripcion_externa,
            unidad_externa_codigo=unidad_externa,
            producto_unidad=producto_unidad,
            factor_conversion=factor_conversion,
            confirmado_por=usuario,
            confirmado_en=timezone.now(),
            activa=True,
        )

        return {
            'mensaje': f'Producto {producto.codigo_interno} creado y homologado exitosamente.',
            'producto': ProductoSerializer(producto).data,
            'producto_unidad': {
                'id': producto_unidad.id,
                'unidad_codigo': producto_unidad.unidad_codigo_id,
                'factor_a_base': format(producto_unidad.factor_a_base, '.8f'),
                'es_base': True,
            },
            'equivalencia': ProductoEquivalenciaSerializer(equivalencia).data,
        }

