import logging
from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.middleware.csrf import get_token, rotate_token
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse

from apps.usuarios.models import TokenRevocado, Usuario, UsuarioEmpresa

from apps.usuarios.authentication import (
    LoginRateThrottle, UsuarioTokenAuthentication, borrar_cookie_sesion, cookie_sesion_activa,
    duracion_token, establecer_cookie_sesion, generar_token, leer_token,
)
from apps.usuarios.permissions import TieneEmpresaActiva, EsAdminEmpresa
from apps.usuarios.serializers import (
    LoginRequestSerializer,
    UsuarioResponseSerializer,
    UsuarioEmpresaItemSerializer,
    AsignarUsuarioRequestSerializer,
)
from apps.auditoria.services import registrar_auditoria
from apps.empresas.models import Empresa

# Bloque 8: eventos de autenticación. Nunca se registran contraseñas ni tokens.
logger_auth = logging.getLogger('fact_kard.auth')


def ip_cliente(request) -> str:
    """Misma IP que usa el throttling (respeta NUM_PROXIES detrás de Nginx)."""
    return LoginRateThrottle().get_ident(request) or '-'


def nombre_para_log(valor) -> str:
    return str(valor or '')[:64].replace('\n', ' ').replace('\r', ' ')


def auditar_acceso(request, accion, *, usuario=None, username=None, motivo_fallo=None, **extra):
    """
    Bloque 24: LOGIN_EXITOSO / LOGIN_FALLIDO / LOGOUT en la tabla de auditoría (sin empresa).
    Solo metadatos seguros: usuario (si se conoce), username intentado acotado, IP (la misma del
    throttling y de los logs) y user-agent resumido. NUNCA contraseña, token, Authorization ni cookies.
    El volumen de LOGIN_FALLIDO está acotado por LoginRateThrottle (el throttling corre antes).
    """
    datos = {'resultado': 'EXITOSO' if accion != 'LOGIN_FALLIDO' else 'FALLIDO', 'ip': ip_cliente(request),
             'user_agent': nombre_para_log(request.META.get('HTTP_USER_AGENT'))[:120] or None, **extra}
    if username is not None:
        datos['username'] = nombre_para_log(username)
    if motivo_fallo:
        datos['motivo_fallo'] = motivo_fallo
    try:
        registrar_auditoria(empresa_id=None, usuario_id=getattr(usuario, 'id', None), accion=accion, entidad='usuario',
                            registro_id=getattr(usuario, 'id', None), valor_nuevo=datos)
    except Exception:  # noqa: BLE001 — la auditoría de acceso nunca debe tumbar el login
        logger_auth.exception('No se pudo registrar la auditoría de acceso (%s).', accion)


def obtener_empresas_usuario(usuario: Usuario, request=None):
    """
    Retorna la lista de empresas activas a las que el usuario tiene acceso,
    junto con su rol ('ADMIN' o 'USUARIO') y su identidad visual (logo, color_tema).
    """
    def _serializar_emp(emp, rol):
        logo_url = None
        if getattr(emp, 'logo', None):
            try:
                url = emp.logo.url
                if request is not None:
                    logo_url = request.build_absolute_uri(url)
                else:
                    logo_url = url
            except Exception:
                logo_url = str(emp.logo)
        return {
            'id': emp.id,
            'ruc': emp.ruc,
            'razon_social': emp.razon_social,
            'nombre_comercial': emp.nombre_comercial,
            'rol': rol,
            'activo': True,
            'logo': logo_url,
            'color_tema': getattr(emp, 'color_tema', None),
        }

    if usuario.es_admin_global:
        todas = Empresa.objects.filter(estado='ACTIVA').order_by('razon_social')
        asignaciones = {
            ue.empresa_id: ue.rol
            for ue in UsuarioEmpresa.objects.filter(usuario=usuario, activo=True)
        }
        return [
            _serializar_emp(emp, asignaciones.get(emp.id, 'ADMIN'))
            for emp in todas
        ]

    asignaciones = (
        UsuarioEmpresa.objects.filter(
            usuario=usuario,
            activo=True,
            empresa__estado='ACTIVA'
        )
        .select_related('empresa')
        .order_by('empresa__razon_social')
    )
    return [
        _serializar_emp(ue.empresa, ue.rol)
        for ue in asignaciones
    ]


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginRateThrottle]

    @extend_schema(
        summary="Autenticación de usuario",
        description="Valida username y contraseña contra password_hash y devuelve token, datos de usuario y empresas asociadas.",
        request=LoginRequestSerializer,
        responses={
            200: OpenApiResponse(description="Inicio de sesión exitoso."),
            401: OpenApiResponse(description="Credenciales inválidas."),
            403: OpenApiResponse(description="Usuario inactivo."),
        }
    )
    def post(self, request):
        serializer = LoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        # Bloque 6: mismo mensaje y mismo trabajo de hash exista o no el usuario.
        usuario = Usuario.objects.filter(username=username).first()
        if usuario is None:
            make_password(password)  # equipara el tiempo de respuesta
            logger_auth.warning('Login fallido: usuario=%s existe=no ip=%s', nombre_para_log(username), ip_cliente(request))
            auditar_acceso(request, 'LOGIN_FALLIDO', username=username, motivo_fallo='CREDENCIALES')
            return Response({'detail': 'Credenciales de acceso inválidas.'}, status=status.HTTP_401_UNAUTHORIZED)

        if not usuario.check_password(password):
            logger_auth.warning('Login fallido: usuario=%s existe=si ip=%s', nombre_para_log(username), ip_cliente(request))
            # Mismo motivo que un usuario inexistente: la auditoría no distingue "existe / no existe".
            auditar_acceso(request, 'LOGIN_FALLIDO', username=username, motivo_fallo='CREDENCIALES')
            return Response({'detail': 'Credenciales de acceso inválidas.'}, status=status.HTTP_401_UNAUTHORIZED)

        # Solo con la contraseña correcta se informa que la cuenta está inactiva.
        if not usuario.activo:
            logger_auth.warning('Login rechazado: usuario inactivo id=%s ip=%s', usuario.id, ip_cliente(request))
            auditar_acceso(request, 'LOGIN_FALLIDO', usuario=usuario, username=username, motivo_fallo='USUARIO_INACTIVO')
            return Response(
                {'detail': 'El usuario se encuentra inactivo. Contacte al administrador.'},
                status=status.HTTP_403_FORBIDDEN
            )

        token = generar_token(usuario)
        empresas_data = obtener_empresas_usuario(usuario, request=request)
        logger_auth.info('Login correcto: usuario id=%s (%s) ip=%s', usuario.id, nombre_para_log(usuario.username), ip_cliente(request))
        auditar_acceso(request, 'LOGIN_EXITOSO', usuario=usuario)

        datos = {
            'usuario': UsuarioResponseSerializer(usuario).data,
            'empresas': empresas_data,
        }
        if not cookie_sesion_activa():
            return Response({'token': token, **datos}, status=status.HTTP_200_OK)
        # Bloque 7 (opcional): el token va solo en la cookie HttpOnly, nunca en el cuerpo.
        respuesta = Response(datos, status=status.HTTP_200_OK)
        establecer_cookie_sesion(respuesta, token)
        rotate_token(request)  # nuevo token CSRF tras iniciar sesión
        return respuesta


class CsrfView(APIView):
    """Bloque 7: entrega la cookie/token CSRF que necesita el modo de sesión por cookie."""
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="Token CSRF",
        description="Entrega el token CSRF (y su cookie) para el modo de sesión por cookie HttpOnly.",
        responses={200: OpenApiResponse(description="{'csrfToken': '...'}")},
    )
    def get(self, request):
        return Response({'csrfToken': get_token(request)})


class LogoutView(APIView):
    """Bloque 6: revoca el token usado en la petición (logout efectivo en el servidor)."""
    permission_classes = [IsAuthenticated]
    authentication_classes = [UsuarioTokenAuthentication]

    def post(self, request):
        payload = leer_token(request.auth)
        expira = timezone.now() + timedelta(seconds=duracion_token())
        TokenRevocado.objects.get_or_create(jti=payload['jti'], defaults={'usuario': request.user, 'expira_en': expira})
        # Limpieza oportunista de revocaciones ya expiradas.
        TokenRevocado.objects.filter(expira_en__lt=timezone.now()).delete()
        logger_auth.info('Logout: usuario id=%s ip=%s (sesión revocada)', request.user.id, ip_cliente(request))
        auditar_acceso(request, 'LOGOUT', usuario=request.user, token_revocado=True)
        respuesta = Response(status=status.HTTP_204_NO_CONTENT)
        if cookie_sesion_activa():
            borrar_cookie_sesion(respuesta)
        return respuesta


class MeView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [UsuarioTokenAuthentication]

    @extend_schema(
        summary="Perfil del usuario autenticado",
        description="Retorna la información del usuario autenticado y su lista de empresas activas.",
        responses={200: OpenApiResponse(description="Datos del usuario actual.")}
    )
    def get(self, request):
        usuario = request.user
        if not usuario.activo:
            return Response(
                {'detail': 'El usuario se encuentra inactivo.'},
                status=status.HTTP_403_FORBIDDEN
            )

        empresas_data = obtener_empresas_usuario(usuario, request=request)
        return Response({
            'usuario': UsuarioResponseSerializer(usuario).data,
            'empresas': empresas_data,
        }, status=status.HTTP_200_OK)


class AsignacionesView(APIView):
    permission_classes = [TieneEmpresaActiva, EsAdminEmpresa]
    authentication_classes = [UsuarioTokenAuthentication]

    @extend_schema(
        summary="Listar usuarios asignados a la empresa activa",
        description="Retorna los usuarios vinculados a la empresa especificada en X-Empresa-Id. Requiere rol ADMIN.",
        responses={200: UsuarioEmpresaItemSerializer(many=True)}
    )
    def get(self, request):
        # Aislamiento multiempresa obligatorio por request.empresa_id
        asignaciones = (
            UsuarioEmpresa.objects.filter(empresa_id=request.empresa_id)
            .select_related('usuario', 'empresa')
            .order_by('usuario__username')
        )
        serializer = UsuarioEmpresaItemSerializer(asignaciones, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Asignar o actualizar rol de usuario en empresa activa",
        description="Crea o actualiza la vinculación de un usuario a la empresa activa con rol ADMIN o USUARIO.",
        request=AsignarUsuarioRequestSerializer,
        responses={
            200: UsuarioEmpresaItemSerializer,
            201: UsuarioEmpresaItemSerializer
        }
    )
    def post(self, request):
        serializer = AsignarUsuarioRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        usuario_id = serializer.validated_data['usuario_id']
        rol = serializer.validated_data['rol']
        activo = serializer.validated_data['activo']

        usuario_asignado = Usuario.objects.get(id=usuario_id)

        with transaction.atomic():
            ue, created = UsuarioEmpresa.objects.get_or_create(
                usuario_id=usuario_id,
                empresa_id=request.empresa_id,
                defaults={'rol': rol, 'activo': activo}
            )

            valor_anterior = None
            if not created:
                valor_anterior = {'rol': ue.rol, 'activo': ue.activo}
                ue.rol = rol
                ue.activo = activo
                ue.save()

            valor_nuevo = {'rol': ue.rol, 'activo': ue.activo}

            # Registrar en auditoría
            registrar_auditoria(
                empresa_id=request.empresa_id,
                usuario_id=request.user.id,
                accion='ASIGNAR_USUARIO' if created else 'ACTUALIZAR_ASIGNACION',
                entidad='USUARIO_EMPRESA',
                registro_id=ue.id,
                valor_anterior=valor_anterior,
                valor_nuevo=valor_nuevo,
                motivo=f"{'Creación' if created else 'Modificación'} de rol {rol} para usuario '{usuario_asignado.username}'."
            )

        res_serializer = UsuarioEmpresaItemSerializer(ue)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(res_serializer.data, status=status_code)
