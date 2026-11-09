from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied, NotAuthenticated
from apps.usuarios.models import UsuarioEmpresa

# ---- Bloque 24: empresa INACTIVA = solo lectura (regla central) -----------------------------------
METODOS_LECTURA = ('GET', 'HEAD', 'OPTIONS')
MENSAJE_EMPRESA_INACTIVA = ('La empresa está INACTIVA: solo se puede consultar su información. '
                            'Un administrador global debe reactivarla para registrar o modificar operaciones.')


class EmpresaInactiva(PermissionDenied):
    default_detail = MENSAJE_EMPRESA_INACTIVA
    default_code = 'empresa_inactiva'


def exigir_empresa_operativa(request, empresa_id, *, view=None):
    """
    Única regla para todo el API: con la empresa INACTIVA solo se permiten lecturas. Bloquea
    documentos, pagos, Kardex, inventario, cierres, emisión electrónica y configuración operativa.
    Una vista puede excluirse con `permitir_empresa_inactiva = True` (p. ej. el cambio de estado
    que la reactiva). Una empresa inexistente se rechaza (403) aunque el usuario sea admin global.
    Guarda el estado en request.empresa_estado.
    """
    from apps.empresas.models import Empresa
    estado = Empresa.objects.filter(pk=empresa_id).values_list('estado', flat=True).first()
    if estado is None:
        raise PermissionDenied('La empresa solicitada no existe.')
    request.empresa_estado = estado
    if (estado != 'ACTIVA' and request.method not in METODOS_LECTURA
            and not getattr(view, 'permitir_empresa_inactiva', False)):
        raise EmpresaInactiva()
    return estado


class TieneEmpresaActiva(BasePermission):
    """
    Permiso reusable de DRF para control multiempresa estricto.
    1. Lee el encabezado 'X-Empresa-Id'.
    2. Valida que el usuario autenticado esté activo.
    3. Valida que tenga una fila activa en 'usuario_empresa' para esa empresa
       (o que sea 'es_admin_global=True').
    4. Inyecta 'request.empresa_id' y 'request.rol_empresa'.
    5. Si intenta acceder a otra empresa o no tiene asignación activa, retorna 403 Forbidden.
    """
    message = "Acceso denegado a la empresa solicitada."

    def has_permission(self, request, view):
        usuario = getattr(request, 'user', None)
        if not usuario or not getattr(usuario, 'is_authenticated', False) or not getattr(usuario, 'activo', False):
            raise NotAuthenticated("Se requiere autenticación para acceder a este recurso.")

        empresa_id_raw = (
            request.headers.get('X-Empresa-Id') or
            request.META.get('HTTP_X_EMPRESA_ID')
        )
        if not empresa_id_raw:
            raise PermissionDenied("El encabezado 'X-Empresa-Id' es obligatorio para operar en el sistema.")

        try:
            empresa_id = int(empresa_id_raw)
        except (ValueError, TypeError):
            raise PermissionDenied("El encabezado 'X-Empresa-Id' debe ser un identificador numérico válido.")

        # Si es Administrador Global, tiene acceso total a cualquier empresa con rol ADMIN
        if getattr(usuario, 'es_admin_global', False):
            request.empresa_id = empresa_id
            ue = UsuarioEmpresa.objects.filter(
                usuario=usuario,
                empresa_id=empresa_id,
                activo=True
            ).first()
            request.rol_empresa = ue.rol if ue else 'ADMIN'
            exigir_empresa_operativa(request, empresa_id, view=view)
            return True

        # Validar membresía activa en usuario_empresa
        ue = UsuarioEmpresa.objects.filter(
            usuario=usuario,
            empresa_id=empresa_id,
            activo=True
        ).first()

        if not ue:
            raise PermissionDenied(
                f"El usuario no tiene asignación activa en la empresa con ID {empresa_id}."
            )

        # Inyectar contexto multiempresa en la request
        request.empresa_id = empresa_id
        request.rol_empresa = ue.rol
        exigir_empresa_operativa(request, empresa_id, view=view)
        return True


class EsAdminEmpresa(BasePermission):
    """
    Permiso reusable de DRF que exige rol 'ADMIN' en la empresa activa
    o privilegios globales de superadministrador ('es_admin_global=True').
    """
    message = "Operación restringida: se requieren privilegios de Administrador en la empresa activa."

    def has_permission(self, request, view):
        usuario = getattr(request, 'user', None)
        if not usuario or not getattr(usuario, 'is_authenticated', False) or not getattr(usuario, 'activo', False):
            raise NotAuthenticated("Se requiere autenticación para acceder a este recurso.")

        if getattr(usuario, 'es_admin_global', False):
            return True

        rol = getattr(request, 'rol_empresa', None)
        if rol == 'ADMIN':
            return True

        raise PermissionDenied(self.message)


class EsAdminGlobal(BasePermission):
    """
    Permiso reusable de DRF que exige privilegios globales de superadministrador ('es_admin_global=True').
    """
    message = "Operación restringida: se requieren privilegios de Administrador Global del sistema."

    def has_permission(self, request, view):
        usuario = getattr(request, 'user', None)
        if not usuario or not getattr(usuario, 'is_authenticated', False) or not getattr(usuario, 'activo', False):
            raise NotAuthenticated("Se requiere autenticación para acceder a este recurso.")

        if getattr(usuario, 'es_admin_global', False):
            return True

        raise PermissionDenied(self.message)


class EsAdminOEsAdminGlobal(BasePermission):
    """
    Permiso reusable de DRF que exige que el usuario sea Administrador Global
    o Administrador de al menos una empresa ACTIVA.

    Bloque 24 (corrección): el catálogo es global, pero un ADMIN de empresa solo puede escribirlo
    desde una empresa operativa. Con el header X-Empresa-Id de una empresa INACTIVA donde es ADMIN
    recibe 403 (empresa inactiva); sin header, necesita rol ADMIN en alguna empresa ACTIVA. El
    administrador global mantiene la excepción explícita (catálogo global del sistema).
    """
    message = "Operación restringida: se requieren privilegios de Administrador para registrar tipos de cambio."

    def has_permission(self, request, view):
        usuario = getattr(request, 'user', None)
        if not usuario or not getattr(usuario, 'is_authenticated', False) or not getattr(usuario, 'activo', False):
            raise NotAuthenticated("Se requiere autenticación para acceder a este recurso.")

        if getattr(usuario, 'es_admin_global', False):
            return True

        # Verificar si tiene rol ADMIN en la empresa del header (que debe estar operativa)
        empresa_id_raw = request.headers.get('X-Empresa-Id') or request.META.get('HTTP_X_EMPRESA_ID')
        if empresa_id_raw:
            try:
                empresa_id = int(empresa_id_raw)
            except (ValueError, TypeError):
                empresa_id = None
            if empresa_id is not None:
                ue = UsuarioEmpresa.objects.filter(usuario=usuario, empresa_id=empresa_id, activo=True).first()
                if ue and ue.rol == 'ADMIN':
                    exigir_empresa_operativa(request, empresa_id, view=view)  # INACTIVA → 403
                    return True

        # Verificar si tiene rol ADMIN en alguna empresa ACTIVA
        if UsuarioEmpresa.objects.filter(usuario=usuario, rol='ADMIN', activo=True, empresa__estado='ACTIVA').exists():
            return True

        raise PermissionDenied(self.message)
