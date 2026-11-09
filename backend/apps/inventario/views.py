from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.auditoria.services import registrar_auditoria
from apps.catalogos.models import TipoExistencia, UnidadMedida
from apps.inventario.models import (
    Almacen,
    NotaInterna,
    Producto,
    ProductoEquivalencia,
    ProductoUnidad,
    SaldoInicial,
    Tercero,
    Transferencia,
)
from apps.inventario.serializers import (
    AlmacenSerializer,
    NotaInternaSerializer,
    ProductoEquivalenciaSerializer,
    ProductoSerializer,
    ProductoUnidadSerializer,
    SaldoInicialSerializer,
    TerceroSerializer,
    TipoExistenciaSerializer,
    TransferenciaSerializer,
    UnidadMedidaSerializer,
)
from apps.inventario.services import (
    confirmar_nota_interna,
    confirmar_saldo_inicial,
    confirmar_transferencia,
)
from apps.usuarios.authentication import UsuarioTokenAuthentication
from apps.usuarios.permissions import EsAdminEmpresa, TieneEmpresaActiva


class EmpresaActivaMixin:
    authentication_classes = (UsuarioTokenAuthentication,)
    permission_classes = (TieneEmpresaActiva,)
    http_method_names = ('get', 'post', 'patch', 'delete', 'head', 'options')
    admin_write_required = True

    def get_permissions(self):
        permisos = [TieneEmpresaActiva()]
        if self.admin_write_required and self.request.method in ('POST', 'PATCH', 'DELETE'):
            permisos.append(EsAdminEmpresa())
        return permisos

    # Bloque 24: la regla de empresa INACTIVA (solo lectura) vive en TieneEmpresaActiva.

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['empresa_id'] = self.request.empresa_id
        return context


class AuditoriaMixin:
    entidad_auditoria = ''

    def _registrar(self, accion, instance, anterior, nuevo):
        registrar_auditoria(
            empresa_id=self.request.empresa_id,
            usuario_id=self.request.user.id,
            accion=accion,
            entidad=self.entidad_auditoria,
            registro_id=instance.id,
            valor_anterior=anterior,
            valor_nuevo=nuevo,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            self.perform_create(serializer)
            nuevo = dict(serializer.data)
            self._registrar(f'CREAR_{self.entidad_auditoria}', serializer.instance, None, nuevo)
        return Response(nuevo, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        anterior = dict(self.get_serializer(instance).data)
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            self.perform_update(serializer)
            nuevo = dict(serializer.data)
            self._registrar(
                f'ACTUALIZAR_{self.entidad_auditoria}',
                serializer.instance,
                anterior,
                nuevo,
            )
        return Response(nuevo)


class AlmacenListCreateView(AuditoriaMixin, EmpresaActivaMixin, generics.ListCreateAPIView):
    serializer_class = AlmacenSerializer
    entidad_auditoria = 'ALMACEN'

    def get_queryset(self):
        return (
            Almacen.objects.filter(empresa_id=self.request.empresa_id)
            .select_related('establecimiento')
            .order_by('codigo')
        )

    def perform_create(self, serializer):
        serializer.save(empresa_id=self.request.empresa_id)


class AlmacenDetailView(AuditoriaMixin, EmpresaActivaMixin, generics.UpdateAPIView):
    serializer_class = AlmacenSerializer
    entidad_auditoria = 'ALMACEN'

    def get_queryset(self):
        return Almacen.objects.filter(
            empresa_id=self.request.empresa_id,
        ).select_related('establecimiento')


class TerceroListCreateView(AuditoriaMixin, EmpresaActivaMixin, generics.ListCreateAPIView):
    serializer_class = TerceroSerializer
    entidad_auditoria = 'TERCERO'

    def get_queryset(self):
        queryset = Tercero.objects.filter(empresa_id=self.request.empresa_id)
        tipo = self.request.query_params.get('tipo', '').lower()
        if tipo == 'cliente':
            queryset = queryset.filter(es_cliente=True)
        elif tipo == 'proveedor':
            queryset = queryset.filter(es_proveedor=True)

        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(numero_documento__icontains=search)
                | Q(razon_social__icontains=search)
                | Q(nombre_comercial__icontains=search)
            )
        return queryset.order_by('razon_social', 'numero_documento')

    def perform_create(self, serializer):
        serializer.save(empresa_id=self.request.empresa_id)


class TerceroDetailView(AuditoriaMixin, EmpresaActivaMixin, generics.UpdateAPIView):
    serializer_class = TerceroSerializer
    entidad_auditoria = 'TERCERO'

    def get_queryset(self):
        return Tercero.objects.filter(empresa_id=self.request.empresa_id)


class ProductoListCreateView(AuditoriaMixin, EmpresaActivaMixin, generics.ListCreateAPIView):
    serializer_class = ProductoSerializer
    entidad_auditoria = 'PRODUCTO'

    def get_queryset(self):
        return (
            Producto.objects.filter(empresa_id=self.request.empresa_id)
            .select_related('tipo_existencia_codigo')
            .prefetch_related('unidades__unidad_codigo')
            .order_by('codigo_interno')
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            producto = serializer.save()
            producto = self.get_queryset().get(pk=producto.pk)
            serializer = self.get_serializer(producto)
            nuevo = dict(serializer.data)
            self._registrar('CREAR_PRODUCTO', producto, None, nuevo)
            unidad_base = producto.unidades.get(es_base=True)
            registrar_auditoria(
                empresa_id=request.empresa_id,
                usuario_id=request.user.id,
                accion='CREAR_PRODUCTO_UNIDAD',
                entidad='PRODUCTO_UNIDAD',
                registro_id=unidad_base.id,
                valor_anterior=None,
                valor_nuevo={
                    'producto': producto.id,
                    'unidad_codigo': unidad_base.unidad_codigo_id,
                    'factor_a_base': format(unidad_base.factor_a_base, '.8f'),
                    'es_base': True,
                },
                motivo='Creación automática de la unidad base del producto.',
            )
        return Response(nuevo, status=status.HTTP_201_CREATED)


class ProductoDetailView(AuditoriaMixin, EmpresaActivaMixin, generics.UpdateAPIView):
    serializer_class = ProductoSerializer
    entidad_auditoria = 'PRODUCTO'

    def get_queryset(self):
        return (
            Producto.objects.filter(empresa_id=self.request.empresa_id)
            .select_related('tipo_existencia_codigo')
            .prefetch_related('unidades__unidad_codigo')
        )


class ProductoScopedMixin(EmpresaActivaMixin):
    producto = None

    def get_producto(self):
        if self.producto is None:
            self.producto = get_object_or_404(
                Producto.objects.filter(empresa_id=self.request.empresa_id),
                pk=self.kwargs['producto_id'],
            )
        return self.producto

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['producto'] = self.get_producto()
        return context


class ProductoUnidadListCreateView(AuditoriaMixin, ProductoScopedMixin, generics.ListCreateAPIView):
    serializer_class = ProductoUnidadSerializer
    entidad_auditoria = 'PRODUCTO_UNIDAD'

    def get_queryset(self):
        return (
            ProductoUnidad.objects.filter(producto=self.get_producto())
            .select_related('unidad_codigo')
            .order_by('-es_base', 'unidad_codigo_id')
        )


class ProductoUnidadDetailView(AuditoriaMixin, ProductoScopedMixin, generics.UpdateAPIView):
    serializer_class = ProductoUnidadSerializer
    entidad_auditoria = 'PRODUCTO_UNIDAD'
    lookup_url_kwarg = 'unidad_id'

    def get_queryset(self):
        return ProductoUnidad.objects.filter(
            producto=self.get_producto(),
        ).select_related('unidad_codigo')


class TipoExistenciaListView(EmpresaActivaMixin, generics.ListAPIView):
    serializer_class = TipoExistenciaSerializer
    queryset = TipoExistencia.objects.all().order_by('codigo')


class UnidadMedidaListView(EmpresaActivaMixin, generics.ListAPIView):
    serializer_class = UnidadMedidaSerializer
    queryset = UnidadMedida.objects.all().order_by('codigo')


def _filtrar_id(queryset, request, parametro, campo):
    valor = request.query_params.get(parametro)
    if not valor:
        return queryset
    try:
        return queryset.filter(**{campo: int(valor)})
    except (TypeError, ValueError):
        raise ValidationError({parametro: 'Debe ser un identificador numérico válido.'})


class SaldoInicialListCreateView(
    AuditoriaMixin, EmpresaActivaMixin, generics.ListCreateAPIView,
):
    serializer_class = SaldoInicialSerializer
    entidad_auditoria = 'SALDO_INICIAL'

    def get_queryset(self):
        queryset = (
            SaldoInicial.objects.filter(empresa_id=self.request.empresa_id)
            .select_related('periodo', 'almacen', 'producto')
            .prefetch_related('producto__unidades')
        )
        queryset = _filtrar_id(queryset, self.request, 'periodo_id', 'periodo_id')
        queryset = _filtrar_id(queryset, self.request, 'almacen_id', 'almacen_id')
        queryset = _filtrar_id(queryset, self.request, 'producto_id', 'producto_id')
        estado = self.request.query_params.get('estado')
        if estado:
            estado_normalizado = estado.strip().upper()
            if estado_normalizado in ('ACTIVO', 'ACTIVOS'):
                queryset = queryset.filter(estado__in=['BORRADOR', 'CONFIRMADO'])
            elif estado_normalizado not in ('TODOS', 'ALL'):
                queryset = queryset.filter(estado=estado_normalizado)
        return queryset.order_by('-periodo__orden', 'almacen__codigo', 'producto__codigo_interno')

    def perform_create(self, serializer):
        serializer.save(
            empresa_id=self.request.empresa_id,
            creado_por=self.request.user,
        )


class SaldoInicialDetailView(
    AuditoriaMixin, EmpresaActivaMixin, generics.RetrieveUpdateDestroyAPIView,
):
    serializer_class = SaldoInicialSerializer
    entidad_auditoria = 'SALDO_INICIAL'

    def get_queryset(self):
        return (
            SaldoInicial.objects.filter(empresa_id=self.request.empresa_id)
            .select_related('periodo', 'almacen', 'producto')
            .prefetch_related('producto__unidades')
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.estado != 'BORRADOR':
            raise ValidationError({
                'estado': 'No se puede eliminar físicamente un saldo inicial confirmado.'
            })
        anterior = dict(self.get_serializer(instance).data)
        with transaction.atomic():
            instance_id = instance.id
            instance.delete()
            self._registrar('ELIMINAR_SALDO_INICIAL', type('Obj', (), {'id': instance_id})(), anterior, None)
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotaInternaMixin(AuditoriaMixin, EmpresaActivaMixin):
    serializer_class = NotaInternaSerializer
    entidad_auditoria = 'NOTA_INTERNA'
    admin_write_required = False

    def get_queryset(self):
        return (
            NotaInterna.objects.filter(empresa_id=self.request.empresa_id)
            .select_related('periodo', 'almacen', 'tipo_operacion')
            .prefetch_related('detalles__producto__unidades')
        )

    def exigir_admin_si_corresponde(self, serializer):
        if serializer.requiere_admin():
            EsAdminEmpresa().has_permission(self.request, self)


class NotaInternaListCreateView(NotaInternaMixin, generics.ListCreateAPIView):
    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = _filtrar_id(queryset, self.request, 'periodo_id', 'periodo_id')
        queryset = _filtrar_id(queryset, self.request, 'almacen_id', 'almacen_id')
        tipo_operacion = self.request.query_params.get('tipo_operacion')
        if tipo_operacion:
            queryset = queryset.filter(tipo_operacion__codigo_interno=tipo_operacion)
        estado = self.request.query_params.get('estado')
        if estado:
            estado_normalizado = estado.strip().upper()
            if estado_normalizado in ('ACTIVO', 'ACTIVOS'):
                queryset = queryset.filter(estado__in=['BORRADOR', 'CONFIRMADO'])
            elif estado_normalizado not in ('TODOS', 'ALL'):
                queryset = queryset.filter(estado=estado_normalizado)
        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(motivo__icontains=search) | Q(responsable__icontains=search)
            )
        return queryset.order_by('-fecha', '-id')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.exigir_admin_si_corresponde(serializer)
        with transaction.atomic():
            nota = serializer.save(
                empresa_id=request.empresa_id,
                creado_por=request.user,
            )
            nota = self.get_queryset().get(pk=nota.pk)
            nuevo = dict(self.get_serializer(nota).data)
            self._registrar('CREAR_NOTA_INTERNA', nota, None, nuevo)
        return Response(nuevo, status=status.HTTP_201_CREATED)


class NotaInternaDetailView(NotaInternaMixin, generics.RetrieveUpdateDestroyAPIView):
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        anterior = dict(self.get_serializer(instance).data)
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.exigir_admin_si_corresponde(serializer)
        with transaction.atomic():
            nota = serializer.save()
            nota = self.get_queryset().get(pk=nota.pk)
            nuevo = dict(self.get_serializer(nota).data)
            self._registrar('ACTUALIZAR_NOTA_INTERNA', nota, anterior, nuevo)
        return Response(nuevo)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.estado != 'BORRADOR':
            raise ValidationError({
                'estado': 'No se puede eliminar físicamente una operación confirmada o anulada; utilice la anulación con extorno.'
            })
        serializer_permiso = self.get_serializer(instance)
        self.exigir_admin_si_corresponde(serializer_permiso)
        anterior = dict(self.get_serializer(instance).data)
        with transaction.atomic():
            instance_id = instance.id
            instance.delete()
            self._registrar('ELIMINAR_NOTA_INTERNA', type('Obj', (), {'id': instance_id})(), anterior, None)
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotaInternaAnularView(NotaInternaMixin, generics.GenericAPIView):
    def post(self, request, *args, **kwargs):
        motivo = request.data.get('motivo') or request.data.get('observacion') or ''
        with transaction.atomic():
            nota = get_object_or_404(
                self.get_queryset().select_for_update(),
                pk=self.kwargs['pk'],
            )
            serializer_permiso = self.get_serializer(nota)
            self.exigir_admin_si_corresponde(serializer_permiso)
            from apps.inventario.services import anular_nota_interna_servicio
            nota = anular_nota_interna_servicio(
                nota_id=nota.pk,
                empresa_id=request.empresa_id,
                usuario=request.user,
                motivo=motivo,
            )
            return Response(self.get_serializer(nota).data)


class SaldoInicialConfirmarView(EmpresaActivaMixin, generics.GenericAPIView):
    serializer_class = SaldoInicialSerializer

    def post(self, request, *args, **kwargs):
        saldo = confirmar_saldo_inicial(
            saldo_id=self.kwargs['pk'], empresa_id=request.empresa_id, usuario=request.user,
        )
        return Response(self.get_serializer(saldo).data)


class NotaInternaConfirmarView(NotaInternaMixin, generics.GenericAPIView):
    def post(self, request, *args, **kwargs):
        nota = get_object_or_404(self.get_queryset(), pk=self.kwargs['pk'])
        self.exigir_admin_si_corresponde(self.get_serializer(nota))
        nota = confirmar_nota_interna(
            nota_id=nota.pk, empresa_id=request.empresa_id, usuario=request.user,
        )
        return Response(self.get_serializer(nota).data)


class TransferenciaMixin(AuditoriaMixin, EmpresaActivaMixin):
    serializer_class = TransferenciaSerializer
    entidad_auditoria = 'TRANSFERENCIA'

    def get_queryset(self):
        return (
            Transferencia.objects.filter(empresa_id=self.request.empresa_id)
            .select_related('almacen_origen', 'almacen_destino')
            .prefetch_related('detalles__producto')
        )


class TransferenciaListCreateView(TransferenciaMixin, generics.ListCreateAPIView):
    def get_queryset(self):
        return super().get_queryset().order_by('-fecha', '-id')

    def perform_create(self, serializer):
        serializer.save(empresa_id=self.request.empresa_id, creado_por=self.request.user)


class TransferenciaDetailView(TransferenciaMixin, generics.RetrieveUpdateAPIView):
    pass


class TransferenciaConfirmarView(TransferenciaMixin, generics.GenericAPIView):
    def post(self, request, *args, **kwargs):
        transferencia = confirmar_transferencia(
            transferencia_id=self.kwargs['pk'], empresa_id=request.empresa_id,
            usuario=request.user,
        )
        transferencia = self.get_queryset().get(pk=transferencia.pk)
        return Response(self.get_serializer(transferencia).data)


class ProductoEquivalenciaMixin(AuditoriaMixin, EmpresaActivaMixin):
    serializer_class = ProductoEquivalenciaSerializer
    entidad_auditoria = 'PRODUCTO_EQUIVALENCIA'
    admin_write_required = True

    def get_queryset(self):
        empresa_id = self.request.empresa_id
        qs = ProductoEquivalencia.objects.filter(empresa_id=empresa_id).select_related(
            'tercero',
            'unidad_externa_codigo',
            'producto_unidad__producto',
            'producto_unidad__unidad_codigo',
            'confirmado_por',
        )
        tercero_id = self.request.query_params.get('tercero_id')
        if tercero_id:
            qs = qs.filter(tercero_id=tercero_id)
        codigo_ext = self.request.query_params.get('codigo_externo')
        if codigo_ext:
            qs = qs.filter(codigo_externo__icontains=codigo_ext.strip())
        activa = self.request.query_params.get('activa')
        if activa is not None:
            qs = qs.filter(activa=activa.lower() in ('true', '1', 't'))
        return qs.order_by('-id')


class ProductoEquivalenciaListCreateView(ProductoEquivalenciaMixin, generics.ListCreateAPIView):
    def perform_create(self, serializer):
        from django.utils import timezone
        serializer.save(
            empresa_id=self.request.empresa_id,
            confirmado_por=self.request.user,
            confirmado_en=timezone.now(),
        )


class ProductoEquivalenciaDetailView(ProductoEquivalenciaMixin, generics.RetrieveUpdateDestroyAPIView):
    def perform_update(self, serializer):
        from django.utils import timezone
        serializer.save(
            confirmado_por=self.request.user,
            confirmado_en=timezone.now(),
        )


class ProductoEquivalenciaSugerirView(EmpresaActivaMixin, generics.GenericAPIView):
    admin_write_required = False

    def get(self, request, *args, **kwargs):
        tercero_id = request.query_params.get('tercero_id')
        codigo_externo = (request.query_params.get('codigo_externo') or '').strip()
        descripcion = (request.query_params.get('descripcion') or '').strip()

        if not tercero_id:
            return Response(
                {'detail': 'El parámetro tercero_id es obligatorio.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # QA2-001: la regla canónica (apps.inventario.homologacion) y ninguna otra: empresa +
        # proveedor + código (descripción solo si no hay código) + unidad.
        from apps.inventario.homologacion import buscar_equivalencia
        tercero = Tercero.objects.filter(pk=tercero_id, empresa_id=request.empresa_id).first()
        equivalencia, _ = buscar_equivalencia(
            empresa_id=request.empresa_id, tercero=tercero, codigo=codigo_externo, descripcion=descripcion,
            unidad=(request.query_params.get('unidad') or '').strip(),
        )

        if equivalencia:
            serializer = ProductoEquivalenciaSerializer(equivalencia, context={'empresa_id': request.empresa_id})
            return Response({
                'encontrado': True,
                'sugerencia': serializer.data,
                'mensaje': 'Equivalencia encontrada y propuesta automáticamente.',
            })

        return Response({
            'encontrado': False,
            'sugerencia': None,
            'estado': 'PRODUCTO_SIN_HOMOLOGAR',
            'mensaje': 'Producto pendiente de homologación.',
        })


CAMPOS_RESUMEN = ('total_original', 'total_notas_credito', 'total_notas_debito', 'total_ajustado', 'pagado',
                  'saldo_pendiente')


class TerceroHistorialView(EmpresaActivaMixin, generics.GenericAPIView):
    """
    Bloque 16: historial comercial del tercero, calculado desde `documento` (sin tabla propia):
    ventas si es cliente, compras si es proveedor (o `?clase=`).

    B16-QA-001: cada comprobante trae los importes ya conciliados por `finanzas` (los mismos de
    CxC/CxP): total original, NC y ND confirmadas, total ajustado, pagado y saldo. Así
    total_ajustado − pagado = saldo en cada fila y en el resumen; el frontend no recalcula.
    """
    admin_write_required = False

    def get(self, request, pk):
        from decimal import Decimal
        from apps.documentos.finanzas import CERO, anotar_finanzas, texto, valores_financieros_texto
        from apps.documentos.models import Documento
        tercero = Tercero.objects.filter(pk=pk, empresa_id=request.empresa_id).first()
        if tercero is None:
            raise NotFound('Tercero no encontrado en la empresa activa.')
        clase = (request.query_params.get('clase') or '').upper()
        clases = [c for c, ok in (('VENTA', tercero.es_cliente), ('COMPRA', tercero.es_proveedor)) if ok]
        if clase in ('VENTA', 'COMPRA'):
            clases = [clase]
        qs = anotar_finanzas(
            Documento.objects.filter(empresa_id=request.empresa_id, tercero=tercero, clase__in=clases)
            .select_related('tipo_comprobante', 'periodo')
        ).order_by('-fecha_emision', '-id')
        filas, resumen = [], {}
        for d in qs[:1000]:
            es_nota = d.tipo_comprobante.es_nota
            financiero = d.estado == 'CONFIRMADO' and not es_nota
            v = valores_financieros_texto(d) if financiero else {}
            fila = {
                'id': d.id, 'clase': d.clase, 'fecha_emision': d.fecha_emision,
                'tipo_comprobante_codigo': d.tipo_comprobante.codigo_sunat, 'es_nota': es_nota,
                'serie': d.serie_normalizada, 'numero': d.numero, 'moneda_codigo': d.moneda_codigo_id,
                # Importe del propio comprobante (en una nota: el importe de la nota).
                'total_original': texto(d.total or CERO),
                'total_notas_credito': v.get('total_notas_credito'), 'total_notas_debito': v.get('total_notas_debito'),
                'total_ajustado': v.get('total_ajustado'),
                'pagado': v.get('pagado'), 'saldo_pendiente': v.get('saldo_pendiente'),
                'condicion_pago': d.condicion_pago, 'fecha_vencimiento': d.fecha_vencimiento, 'estado': d.estado,
                'estado_financiero': d.estado_financiero if financiero else None,
            }
            filas.append(fila)
            if financiero:
                r = resumen.setdefault(f'{d.clase}:{d.moneda_codigo_id}', {
                    'clase': d.clase, 'moneda_codigo': d.moneda_codigo_id, 'comprobantes': 0,
                    **{k: CERO for k in CAMPOS_RESUMEN}})
                r['comprobantes'] += 1
                for k in CAMPOS_RESUMEN:
                    r[k] += Decimal(v['total' if k == 'total_original' else k])
        return Response({
            'tercero': {'id': tercero.id, 'tipo_documento': tercero.tipo_documento,
                        'numero_documento': tercero.numero_documento, 'razon_social': tercero.razon_social,
                        'es_cliente': tercero.es_cliente, 'es_proveedor': tercero.es_proveedor},
            'clases': clases, 'comprobantes': filas,
            'resumen': [{**r, **{k: texto(r[k]) for k in CAMPOS_RESUMEN}} for r in resumen.values()],
        })
