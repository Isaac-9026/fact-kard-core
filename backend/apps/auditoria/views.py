from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.auditoria.models import Auditoria
from config.api import PaginacionOpcional
from apps.auditoria.serializers import AuditoriaSerializer
from apps.usuarios.authentication import UsuarioTokenAuthentication
from apps.usuarios.permissions import EsAdminGlobal, TieneEmpresaActiva, EsAdminEmpresa


class AuditoriaListView(APIView):
    """
    Endpoint de consulta de auditoría.
    Protegido con TieneEmpresaActiva y EsAdminEmpresa.
    Aislamiento estricto: solo devuelve registros de request.empresa_id.
    Permite filtrar por 'entidad' y 'accion'.
    """
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]
    authentication_classes = [UsuarioTokenAuthentication]

    @extend_schema(
        summary="Consultar registros de auditoría",
        description="Retorna el log inmutable de auditoría de la empresa activa. Permite filtros por entidad y acción.",
        parameters=[
            OpenApiParameter(name='entidad', description='Filtrar por nombre de entidad (ej: USUARIO_EMPRESA, DOCUMENTO)', required=False, type=str),
            OpenApiParameter(name='accion', description='Filtrar por tipo de acción (ej: ASIGNAR_USUARIO, CREAR)', required=False, type=str),
        ],
        responses={200: AuditoriaSerializer(many=True)}
    )
    def get(self, request):
        # Aislamiento multiempresa estricto
        qs = (
            Auditoria.objects.filter(empresa_id=request.empresa_id)
            .select_related('usuario', 'empresa')
            .order_by('-fecha', '-id')
        )

        entidad = request.query_params.get('entidad')
        if entidad:
            qs = qs.filter(entidad__iexact=entidad.strip())

        accion = request.query_params.get('accion')
        if accion:
            qs = qs.filter(accion__iexact=accion.strip())

        # Bloque 6: paginación opcional (?page=&page_size=).
        paginador = PaginacionOpcional()
        pagina = paginador.paginate_queryset(qs, request, self)
        if pagina is not None:
            return paginador.get_paginated_response(AuditoriaSerializer(pagina, many=True).data)
        serializer = AuditoriaSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AuditoriaGlobalListView(APIView):
    """
    Bloque 24 (corrección): eventos de auditoría SIN empresa (empresa_id NULL), como LOGIN_EXITOSO,
    LOGIN_FALLIDO y LOGOUT. Solo administrador global. Nunca se mezclan con la auditoría de una
    empresa (esa vista sigue filtrando por request.empresa_id) y esta no devuelve eventos de empresas.
    Filtros opcionales: accion, entidad, usuario (id). Paginación opcional (?page=&page_size=).
    """
    permission_classes = [EsAdminGlobal]
    authentication_classes = [UsuarioTokenAuthentication]

    @extend_schema(
        summary="Auditoría global (solo administrador global)",
        description="Eventos sin empresa: accesos (LOGIN_EXITOSO, LOGIN_FALLIDO, LOGOUT) y catálogos globales.",
        parameters=[
            OpenApiParameter(name='accion', description='Filtrar por acción (ej: LOGIN_FALLIDO)', required=False, type=str),
            OpenApiParameter(name='entidad', description='Filtrar por entidad (ej: usuario)', required=False, type=str),
            OpenApiParameter(name='usuario', description='Filtrar por id de usuario', required=False, type=int),
        ],
        responses={200: AuditoriaSerializer(many=True)}
    )
    def get(self, request):
        qs = Auditoria.objects.filter(empresa__isnull=True).select_related('usuario').order_by('-fecha', '-id')
        accion = request.query_params.get('accion')
        if accion:
            qs = qs.filter(accion__iexact=accion.strip())
        entidad = request.query_params.get('entidad')
        if entidad:
            qs = qs.filter(entidad__iexact=entidad.strip())
        usuario = request.query_params.get('usuario')
        if usuario:
            if not usuario.strip().isdigit():
                return Response({'usuario': 'Debe ser un id numérico.'}, status=status.HTTP_400_BAD_REQUEST)
            qs = qs.filter(usuario_id=int(usuario))
        paginador = PaginacionOpcional()
        pagina = paginador.paginate_queryset(qs, request, self)
        if pagina is not None:
            return paginador.get_paginated_response(AuditoriaSerializer(pagina, many=True).data)
        return Response(AuditoriaSerializer(qs[:500], many=True).data)
