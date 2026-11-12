from decimal import Decimal

from django.conf import settings
from django.db.models import Q, Count
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.api import PaginacionOpcional, entero_param
from apps.documentos.models import Documento, DocumentoCaptura
from apps.documentos.serializers import (
    DocumentoListSerializer,
    DocumentoDetailSerializer,
    DocumentoCreateSerializer,
    DocumentoRevisarSerializer,
    DocumentoAnularSerializer,
    CapturaCampoSerializer,
    DocumentoCapturaListSerializer,
    DocumentoCapturaDetailSerializer,
    DocumentoCapturaSubirSerializer,
    CapturaCampoCorregirSerializer,
    GenerarBorradorSerializer,
)
from apps.documentos.services import (
    revisar_documento,
    confirmar_documento_validacion,
    anular_documento,
)
from apps.documentos.captura_services import (
    procesar_subida_captura,
    corregir_campo_captura,
    generar_borrador_desde_captura,
)
from apps.usuarios.permissions import EsAdminEmpresa, TieneEmpresaActiva


class DocumentoListCreateView(generics.ListCreateAPIView):
    """
    Lista y crea comprobantes comerciales (Compras, Ventas, NC, ND).
    Aislamiento estricto por empresa_id (X-Empresa-Id).
    """
    permission_classes = [TieneEmpresaActiva]
    pagination_class = PaginacionOpcional

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return DocumentoCreateSerializer
        return DocumentoListSerializer

    def get_queryset(self):
        empresa_id = getattr(self.request, 'empresa_id', None)
        if not empresa_id:
            return Documento.objects.none()

        # Bloque 6: el número de líneas se anota en SQL (antes un COUNT por documento).
        campos_select = ['periodo', 'tercero', 'tipo_comprobante', 'moneda_codigo', 'revisado_por']
        if 'apps.emision_electronica' in settings.INSTALLED_APPS:
            campos_select.append('emision_electronica')
        qs = Documento.objects.filter(empresa_id=empresa_id).select_related(
            *campos_select
        ).annotate(num_detalles=Count('detalles'))

        clase = self.request.query_params.get('clase')
        if clase:
            qs = qs.filter(clase=clase.upper())

        periodo_id = entero_param(self.request.query_params, 'periodo')  # Bloque 6: 400 si no es id
        if periodo_id:
            qs = qs.filter(periodo_id=periodo_id)

        estado = self.request.query_params.get('estado')
        if estado:
            qs = qs.filter(estado=estado.upper())

        estado_revision = self.request.query_params.get('estado_revision')
        if estado_revision:
            qs = qs.filter(estado_revision=estado_revision.upper())

        # Navegación: vistas separadas de Compras/Ventas (sin notas) y de Notas de Crédito/Débito.
        es_nota = self.request.query_params.get('es_nota')
        if es_nota not in (None, ''):
            valor = str(es_nota).strip().lower()
            if valor not in ('true', 'false', '1', '0'):
                raise ValidationError({'es_nota': "Valor no permitido. Use 'true' o 'false'."})
            qs = qs.filter(tipo_comprobante__es_nota=valor in ('true', '1'))

        search = self.request.query_params.get('search')
        if search:
            search = search.strip()
            condicion = (
                Q(serie_normalizada__icontains=search) |
                Q(numero_normalizado__icontains=search) |
                Q(ruc_emisor__icontains=search) |
                Q(tercero__razon_social__icontains=search) |
                Q(tercero__numero_documento__icontains=search)  # QA-004: RUC/DNI del cliente o proveedor
            )
            # Bloque 7: el buscador del frontend admite "SERIE-NUMERO" (antes se filtraba
            # en el navegador sobre "F001-123"); ahora la búsqueda se hace aquí.
            if '-' in search:
                serie, _, numero = search.partition('-')
                if serie and numero:
                    condicion |= Q(serie_normalizada__iendswith=serie, numero_normalizado__istartswith=numero)
                elif serie:
                    condicion |= Q(serie_normalizada__iendswith=serie)
                elif numero:
                    condicion |= Q(numero_normalizado__istartswith=numero)
            qs = qs.filter(condicion)

        return qs.order_by('-fecha_emision', '-id')

    @extend_schema(
        summary="Listar documentos comerciales",
        description="Obtiene el listado de comprobantes filtrados por empresa activa y filtros opcionales.",
        parameters=[
            OpenApiParameter(name='clase', description='COMPRA o VENTA', required=False, type=str),
            OpenApiParameter(name='periodo', description='ID del período', required=False, type=int),
            OpenApiParameter(name='estado', description='BORRADOR, CONFIRMADO, ANULADO', required=False, type=str),
            OpenApiParameter(name='estado_revision', description='PENDIENTE, EN_REVISION, REVISADO, OBSERVADO', required=False, type=str),
            OpenApiParameter(name='search', description='Búsqueda por comprobante, RUC o tercero', required=False, type=str),
        ],
        responses={200: DocumentoListSerializer(many=True)}
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Crear documento comercial con detalles",
        description="Registra un comprobante con validaciones de duplicados, cálculo de cantidad base y costo unitario en PEN.",
        request=DocumentoCreateSerializer,
        responses={201: DocumentoDetailSerializer}
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        documento = serializer.save()
        output_serializer = DocumentoDetailSerializer(documento)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


class DocumentoDetailView(generics.RetrieveDestroyAPIView):
    """
    Consulta el detalle completo o elimina un comprobante en estado BORRADOR.
    """
    permission_classes = [TieneEmpresaActiva]
    serializer_class = DocumentoDetailSerializer

    def get_queryset(self):
        empresa_id = getattr(self.request, 'empresa_id', None)
        return Documento.objects.filter(empresa_id=empresa_id).prefetch_related(
            'detalles__producto',
            'detalles__producto_unidad',
            'detalles__almacen',
            'detalles__tipo_operacion'
        )

    def perform_destroy(self, instance):
        if instance.estado != 'BORRADOR':
            raise ValidationError({'detail': 'Solo se pueden eliminar documentos en estado BORRADOR.'})
        if instance.serie_comprobante_id:
            # Bloque 16: el número ya se asignó de la serie; eliminarlo dejaría un hueco.
            raise ValidationError({'detail': 'El comprobante tiene número asignado por la serie: anúlelo en lugar de eliminarlo.'})
        instance.delete()


class DocumentoRevisarView(APIView):
    """
    Cambia el estado de revisión de un comprobante (EN_REVISION, REVISADO, OBSERVADO)
    registrando la traza inmutable en Auditoría.
    """
    permission_classes = [TieneEmpresaActiva]

    @extend_schema(
        summary="Revisar documento",
        description="Actualiza el estado de revisión del comprobante con registro de auditoría.",
        request=DocumentoRevisarSerializer,
        responses={200: DocumentoDetailSerializer}
    )
    def post(self, request, pk):
        serializer = DocumentoRevisarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        nuevo_estado = serializer.validated_data['estado_revision']
        motivo = serializer.validated_data.get('motivo')

        doc = revisar_documento(
            documento_id=pk,
            empresa_id=request.empresa_id,
            usuario_id=request.user.id,
            nuevo_estado_revision=nuevo_estado,
            motivo=motivo
        )

        return Response(DocumentoDetailSerializer(doc).data, status=status.HTTP_200_OK)


class DocumentoConfirmarView(APIView):
    """
    Valida y confirma un documento comercial.
    Exige que el comprobante esté en estado de revisión REVISADO y en período ABIERTO.
    """
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]

    @extend_schema(
        summary="Confirmar documento",
        description="Pasa el documento a CONFIRMADO tras verificar que esté REVISADO y el período ABIERTO.",
        responses={200: DocumentoDetailSerializer}
    )
    def post(self, request, pk):
        doc = confirmar_documento_validacion(
            documento_id=pk,
            empresa_id=request.empresa_id,
            usuario_id=request.user.id
        )
        return Response(DocumentoDetailSerializer(doc).data, status=status.HTTP_200_OK)


class DocumentoAnularView(APIView):
    """
    Anula un documento comercial con motivo obligatorio y registro en Auditoría.
    """
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]

    @extend_schema(
        summary="Anular documento",
        description="Marca el documento como ANULADO con motivo obligatorio.",
        request=DocumentoAnularSerializer,
        responses={200: DocumentoDetailSerializer}
    )
    def post(self, request, pk):
        serializer = DocumentoAnularSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        doc = anular_documento(
            documento_id=pk,
            empresa_id=request.empresa_id,
            usuario_id=request.user.id,
            motivo=serializer.validated_data['motivo']
        )
        return Response(DocumentoDetailSerializer(doc).data, status=status.HTTP_200_OK)


class DocumentoCapturaSubirView(APIView):
    """
    Sube un archivo XML, PDF o Imagen para captura electrónica u OCR.
    Calcula SHA-256 para evitar duplicados y extrae campos automáticamente.
    """
    permission_classes = [TieneEmpresaActiva]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        serializer = DocumentoCapturaSubirSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        archivo = serializer.validated_data['archivo']
        tipo = serializer.validated_data['tipo']
        texto_ocr = serializer.validated_data.get('texto_ocr', '')

        captura, fue_creado = procesar_subida_captura(
            empresa_id=request.empresa_id,
            usuario=request.user,
            archivo=archivo,
            tipo=tipo,
            texto_ocr=texto_ocr,
            nombre_archivo=serializer.validated_data['nombre_seguro'],
        )

        data = DocumentoCapturaDetailSerializer(captura).data
        data['fue_creado_nuevo'] = fue_creado
        data['mensaje'] = (
            'Archivo procesado exitosamente.'
            if fue_creado
            else 'Archivo idéntico detectado (hash SHA-256 ya existente), reutilizando captura.'
        )

        st = status.HTTP_201_CREATED if fue_creado else status.HTTP_200_OK
        return Response(data, status=st)


class DocumentoCapturaListView(generics.ListAPIView):
    """Lista las capturas realizadas por la empresa activa."""
    permission_classes = [TieneEmpresaActiva]
    serializer_class = DocumentoCapturaListSerializer
    pagination_class = PaginacionOpcional

    def get_queryset(self):
        empresa_id = getattr(self.request, 'empresa_id', None)
        if not empresa_id:
            return DocumentoCaptura.objects.none()
        qs = DocumentoCaptura.objects.filter(empresa_id=empresa_id).select_related('subido_por').prefetch_related('campos')
        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo.upper())
        estado = self.request.query_params.get('estado')
        if estado:
            qs = qs.filter(estado_proceso=estado.upper())
        return qs.order_by('-id')


class DocumentoCapturaDetailView(generics.RetrieveDestroyAPIView):
    """
    Detalle completo de una captura con todos sus campos extraídos.
    DELETE: Descarta una captura de prueba o errónea que aún no tenga comprobante generado.
    """
    permission_classes = [TieneEmpresaActiva]
    serializer_class = DocumentoCapturaDetailSerializer

    def get_queryset(self):
        empresa_id = getattr(self.request, 'empresa_id', None)
        if not empresa_id:
            return DocumentoCaptura.objects.none()
        return DocumentoCaptura.objects.filter(empresa_id=empresa_id).select_related('subido_por', 'documento').prefetch_related('campos')

    def delete(self, request, *args, **kwargs):
        captura = self.get_object()
        if captura.documento_id is not None or captura.estado_proceso == 'BORRADOR_GENERADO':
            return Response(
                {"detail": "No se puede descartar una captura que ya generó un comprobante en borrador o confirmado."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        captura.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CapturaCampoCorregirView(APIView):
    """Permite al usuario corregir el valor de un campo extraído en CapturaCampo."""
    permission_classes = [TieneEmpresaActiva]

    def patch(self, request, pk):
        serializer = CapturaCampoCorregirSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        campo = corregir_campo_captura(
            captura_id=pk,
            campo_id=serializer.validated_data['campo_id'],
            valor_corregido=serializer.validated_data['valor_corregido'],
            empresa_id=request.empresa_id,
            usuario=request.user,
        )
        return Response(CapturaCampoSerializer(campo).data, status=status.HTTP_200_OK)


class DocumentoCapturaGenerarBorradorView(APIView):
    """
    Convierte la captura en un Documento comercial estrictamente en BORRADOR y PENDIENTE.
    Crea Incidencia tipo 'PRODUCTO_SIN_HOMOLOGAR' para cada ítem sin ProductoEquivalencia.
    """
    permission_classes = [TieneEmpresaActiva]

    def post(self, request, pk):
        serializer = GenerarBorradorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        res = generar_borrador_desde_captura(
            captura_id=pk,
            empresa_id=request.empresa_id,
            usuario=request.user,
            almacen_id=serializer.validated_data.get('almacen_id'),
        )
        return Response(res, status=status.HTTP_201_CREATED)


# ==== Bloque 16: series, condición de pago, pagos y cuentas por cobrar/pagar =================

from apps.auditoria.services import registrar_auditoria  # noqa: E402
from apps.documentos import finanzas  # noqa: E402
from apps.documentos.models import PagoDocumento, SerieComprobante  # noqa: E402
from apps.documentos.serializers import (  # noqa: E402
    CondicionPagoSerializer, MotivoSerializer, PagoDocumentoSerializer, PagoEntradaSerializer,
    SerieComprobanteSerializer,
)


class SoloLecturaOAdmin:
    """Lectura para cualquier usuario de la empresa; escritura solo ADMIN."""

    def get_permissions(self):
        if self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return [TieneEmpresaActiva()]
        return [TieneEmpresaActiva(), EsAdminEmpresa()]


def _serie_auditoria(serie):
    return {'serie': serie.serie, 'tipo_comprobante': serie.tipo_comprobante.codigo_sunat,
            'establecimiento': serie.establecimiento.codigo_sunat, 'ultimo_correlativo': serie.ultimo_correlativo,
            'activo': serie.activo}


class SerieComprobanteListCreateView(SoloLecturaOAdmin, generics.ListCreateAPIView):
    serializer_class = SerieComprobanteSerializer
    pagination_class = None

    def get_queryset(self):
        qs = SerieComprobante.objects.filter(empresa_id=self.request.empresa_id).select_related(
            'establecimiento', 'tipo_comprobante')
        tipo = entero_param(self.request.query_params, 'tipo_comprobante')
        if tipo:
            qs = qs.filter(tipo_comprobante_id=tipo)
        if self.request.query_params.get('activo') in ('1', 'true', 'True'):
            qs = qs.filter(activo=True)
        return qs.order_by('tipo_comprobante__codigo_sunat', 'serie')

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'empresa_id': getattr(self.request, 'empresa_id', None)}

    def perform_create(self, serializer):
        serie = serializer.save(empresa_id=self.request.empresa_id)
        registrar_auditoria(empresa_id=self.request.empresa_id, usuario_id=self.request.user.id, accion='CREAR',
                            entidad='SERIE_COMPROBANTE', registro_id=serie.id, valor_nuevo=_serie_auditoria(serie),
                            motivo='Creación de serie de comprobantes')


class SerieComprobanteDetailView(SoloLecturaOAdmin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SerieComprobanteSerializer
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return SerieComprobante.objects.filter(empresa_id=self.request.empresa_id).select_related(
            'establecimiento', 'tipo_comprobante')

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'empresa_id': getattr(self.request, 'empresa_id', None)}

    def perform_update(self, serializer):
        antes = _serie_auditoria(serializer.instance)
        serie = serializer.save(actualizado_en=timezone.now())
        registrar_auditoria(empresa_id=self.request.empresa_id, usuario_id=self.request.user.id, accion='ACTUALIZAR',
                            entidad='SERIE_COMPROBANTE', registro_id=serie.id, valor_anterior=antes,
                            valor_nuevo=_serie_auditoria(serie), motivo='Modificación de serie de comprobantes')

    def perform_destroy(self, instance):
        if instance.documentos.exists() or instance.ultimo_correlativo:
            raise ValidationError({'detail': 'La serie ya emitió números: desactívela en lugar de eliminarla.'})
        registrar_auditoria(empresa_id=self.request.empresa_id, usuario_id=self.request.user.id, accion='ELIMINAR',
                            entidad='SERIE_COMPROBANTE', registro_id=instance.id,
                            valor_anterior=_serie_auditoria(instance), motivo='Eliminación de serie sin uso')
        instance.delete()


class DocumentoCondicionPagoView(APIView):
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]

    def put(self, request, pk):
        datos = CondicionPagoSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        doc = finanzas.cambiar_condicion_pago(
            documento_id=pk, empresa_id=request.empresa_id, usuario_id=request.user.id,
            condicion=v['condicion_pago'], fecha_vencimiento=v.get('fecha_vencimiento'),
            cuotas=[dict(c) for c in v.get('cuotas') or []], motivo=v.get('motivo'),
        )
        return Response(DocumentoDetailSerializer(doc).data)


class PagoDocumentoListCreateView(SoloLecturaOAdmin, APIView):
    def get(self, request):
        qs = PagoDocumento.objects.filter(empresa_id=request.empresa_id).select_related(
            'metodo_pago', 'registrado_por', 'anulado_por')
        documento = entero_param(request.query_params, 'documento')
        if documento:
            qs = qs.filter(documento_id=documento)
        return Response(PagoDocumentoSerializer(qs.order_by('-fecha', '-id')[:500], many=True).data)

    def post(self, request):
        datos = PagoEntradaSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        pago = finanzas.registrar_pago(
            empresa_id=request.empresa_id, usuario_id=request.user.id, documento_id=v['documento'],
            fecha=v['fecha'], monto=v['monto'], metodo_pago=v['metodo_pago'], referencia=v.get('referencia'),
            moneda=v.get('moneda_codigo') or None,
        )
        return Response(PagoDocumentoSerializer(pago).data, status=status.HTTP_201_CREATED)


class PagoDocumentoAnularView(APIView):
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]

    def post(self, request, pk):
        datos = MotivoSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        pago = finanzas.anular_pago(empresa_id=request.empresa_id, usuario_id=request.user.id, pago_id=pk,
                                    motivo=datos.validated_data['motivo'])
        return Response(PagoDocumentoSerializer(pago).data)


ESTADOS_CUENTA = ('PENDIENTE', 'PARCIAL', 'PAGADO', 'VENCIDO', 'ABIERTOS')


def fila_cuenta(d):
    return {
        'id': d.id, 'clase': d.clase, 'tercero': d.tercero_id,
        'tercero_razon_social': d.tercero.razon_social if d.tercero else None,
        'tercero_numero_documento': d.tercero.numero_documento if d.tercero else None,
        'tipo_comprobante_codigo': d.tipo_comprobante.codigo_sunat,
        'serie': d.serie_normalizada, 'numero': d.numero, 'numero_normalizado': d.numero_normalizado,
        'fecha_emision': d.fecha_emision, 'fecha_vencimiento': d.fecha_vencimiento,
        'condicion_pago': d.condicion_pago, 'moneda_codigo': d.moneda_codigo_id, 'periodo': d.periodo_id,
        **finanzas.valores_financieros_texto(d), 'estado_financiero': d.estado_financiero,
        'estado': d.estado,
    }


class CuentasView(APIView):
    """Cuentas por cobrar (VENTA) o por pagar (COMPRA), calculadas en cada consulta."""
    permission_classes = [TieneEmpresaActiva]
    clase = None

    def get(self, request):
        params = request.query_params
        estado = (params.get('estado') or '').upper() or None
        if estado and estado not in ESTADOS_CUENTA:
            raise ValidationError({'estado': f'Estado no válido. Use {", ".join(ESTADOS_CUENTA)}.'})
        condicion = (params.get('condicion') or 'CREDITO').upper()
        if condicion not in ('CREDITO', 'CONTADO', 'TODAS'):
            raise ValidationError({'condicion': 'Use CREDITO, CONTADO o TODAS.'})
        tercero = entero_param(params, 'tercero')
        periodo = entero_param(params, 'periodo')
        qs = finanzas.cuentas(empresa_id=request.empresa_id, clase=self.clase, tercero_id=tercero, periodo_id=periodo,
                              estado=estado, condicion=condicion)
        filas = [fila_cuenta(d) for d in qs[:2000]]
        totales = {}
        for f in filas:
            t = totales.setdefault(f['moneda_codigo'], {'total_ajustado': finanzas.CERO, 'pagado': finanzas.CERO,
                                                       'saldo_pendiente': finanzas.CERO, 'monto_vencido': finanzas.CERO})
            for k in t:
                t[k] += Decimal(f[k])
        return Response({
            'clase': self.clase, 'fecha_corte': finanzas.hoy(), 'cantidad': len(filas), 'resultados': filas,
            'totales': {m: {k: finanzas.texto(v) for k, v in t.items()} for m, t in totales.items()},
        })


class CuentasPorCobrarView(CuentasView):
    clase = 'VENTA'


class CuentasPorPagarView(CuentasView):
    clase = 'COMPRA'


# ---- Bloque 17A: preparación tributaria (sin XML, firma ni envío) ---------------------------
from django.db import transaction  # noqa: E402
from rest_framework.exceptions import NotFound  # noqa: E402

from apps.documentos import reglas_tributarias  # noqa: E402


def documento_para_validacion(pk, empresa_id, *, bloquear=False):
    qs = Documento.objects.filter(pk=pk, empresa_id=empresa_id).select_related(
        'empresa__configuracion', 'tipo_comprobante', 'tercero', 'serie_comprobante__establecimiento__empresa__configuracion',
        'documento_origen__tipo_comprobante', 'motivo_nota', 'moneda_codigo',
    )
    if bloquear:
        qs = qs.select_for_update(of=('self',))
    doc = qs.first()
    if doc is None:
        raise NotFound('El documento no existe o no pertenece a la empresa activa.')
    return doc


class DocumentoValidacionElectronicaView(APIView):
    """
    GET: ¿el comprobante cumple los requisitos previos a la emisión electrónica?
    Solo lectura. Las claves de 17A no cambian ({listo, estado LISTO_PARA_EMISION / NO_PREPARADO,
    errores, advertencias}: siempre del DOCUMENTO). Bloque 18 agrega, por separado: identidad_sunat,
    estado_electronico y preparacion {servidor, empresa, documento}; el detalle de servidor/empresa
    solo para ADMIN.
    """
    permission_classes = [TieneEmpresaActiva]

    def get(self, request, pk):
        from django.conf import settings
        doc = documento_para_validacion(pk, request.empresa_id)
        if 'apps.emision_electronica' in settings.INSTALLED_APPS:
            from apps.emision_electronica.preparacion import preparacion_documento
            admin = bool(getattr(request.user, 'es_admin_global', False) or getattr(request, 'rol_empresa', None) == 'ADMIN')
            return Response(preparacion_documento(doc, incluir_detalle_infraestructura=admin))
        return Response(reglas_tributarias.validar_para_emision_electronica(doc))


class DocumentoMotivoNotaView(APIView):
    """PUT {motivo_nota: '07'}: registra o corrige el motivo tributario de una nota (auditado)."""
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]

    def put(self, request, pk):
        codigo = (request.data.get('motivo_nota') or '').strip() if isinstance(request.data, dict) else ''
        if not codigo:
            raise ValidationError({'motivo_nota': 'Seleccione el motivo de la nota.'})
        with transaction.atomic():
            doc = documento_para_validacion(pk, request.empresa_id, bloquear=True)
            if not doc.tipo_comprobante.es_nota:
                raise ValidationError({'motivo_nota': 'Solo las notas de crédito o débito llevan motivo.'})
            if doc.estado == 'ANULADO':
                raise ValidationError({'motivo_nota': 'La nota está anulada.'})
            motivo = reglas_tributarias.resolver_motivo_nota(codigo, doc.tipo_comprobante)
            anterior = doc.motivo_nota
            if anterior is None or anterior.pk != motivo.pk:
                doc.motivo_nota = motivo
                doc.save(update_fields=['motivo_nota'])
                registrar_auditoria(
                    empresa_id=request.empresa_id, usuario_id=request.user.id, accion='CAMBIAR_MOTIVO_NOTA',
                    entidad='documento', registro_id=doc.id,
                    valor_anterior={'motivo_nota': f'{anterior.catalogo}-{anterior.codigo}' if anterior else None},
                    valor_nuevo={'motivo_nota': f'{motivo.catalogo}-{motivo.codigo}'},
                    motivo='Motivo tributario de la nota',
                )
        return Response(DocumentoDetailSerializer(Documento.objects.get(pk=doc.pk)).data)


class DetalleCodigoAfectacionView(APIView):
    """
    B17A-QA-001: PUT {codigo_afectacion_igv: '15'} registra o corrige el código del Catálogo 07
    de una línea GRATUITA ya guardada (auditado). Solo información tributaria: no cambia precio,
    IGV, totales, costo, Kardex ni movimientos.
    """
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]

    def put(self, request, pk, detalle_id):
        from apps.documentos.afectacion_igv import GRATUITO, validar_codigo_gratuito
        from apps.documentos.models import DocumentoDetalle
        codigo = (request.data.get('codigo_afectacion_igv') or '').strip() if isinstance(request.data, dict) else ''
        if not codigo:
            raise ValidationError({'codigo_afectacion_igv': 'Seleccione el código del Catálogo 07.'})
        with transaction.atomic():
            doc = documento_para_validacion(pk, request.empresa_id, bloquear=True)
            if doc.estado == 'ANULADO':
                raise ValidationError({'codigo_afectacion_igv': 'El comprobante está anulado.'})
            linea = DocumentoDetalle.objects.select_for_update().filter(pk=detalle_id, documento_id=doc.id).first()
            if linea is None:
                raise NotFound('La línea no existe en este comprobante.')
            if linea.afectacion_igv != GRATUITO:
                raise ValidationError({'codigo_afectacion_igv': (
                    f'La línea {linea.linea} es {linea.afectacion_igv or "GRAVADO"}: el código específico solo se '
                    'registra en líneas gratuitas.')})
            error = validar_codigo_gratuito(codigo)
            if error:
                raise ValidationError({'codigo_afectacion_igv': error})
            anterior = linea.codigo_afectacion_igv
            if anterior != codigo:
                linea.codigo_afectacion_igv = codigo
                linea.save(update_fields=['codigo_afectacion_igv'])
                registrar_auditoria(
                    empresa_id=request.empresa_id, usuario_id=request.user.id, accion='CAMBIAR_CODIGO_AFECTACION',
                    entidad='documento_detalle', registro_id=linea.id,
                    valor_anterior={'documento_id': doc.id, 'linea': linea.linea, 'codigo_afectacion_igv': anterior},
                    valor_nuevo={'documento_id': doc.id, 'linea': linea.linea, 'codigo_afectacion_igv': codigo},
                    motivo='Código del Catálogo 07 de una línea gratuita',
                )
        return Response(DocumentoDetailSerializer(Documento.objects.get(pk=doc.pk)).data)
