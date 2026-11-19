from rest_framework import serializers
from apps.usuarios.models import ROLES_EMPRESA, Usuario, UsuarioEmpresa


def validar_password_segura(value, *, username=None, email=None):
    """
    Contraseña segura (mismas reglas para crear, resetear y cambiar):
    mínimo 10 caracteres, no común, no solo números y no parecida al usuario o correo.
    """
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError
    try:
        validate_password(value, user=Usuario(username=username or '', email=email or ''))  # sin guardar
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages))
    return value


class LoginRequestSerializer(serializers.Serializer):
    username = serializers.CharField(required=True, trim_whitespace=True)
    password = serializers.CharField(required=True, write_only=True)


class UsuarioResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ['id', 'username', 'email', 'es_admin_global', 'activo']


class EmpresaAsociadaResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    ruc = serializers.CharField()
    razon_social = serializers.CharField()
    nombre_comercial = serializers.CharField(allow_null=True)
    rol = serializers.CharField()
    activo = serializers.BooleanField()
    logo = serializers.CharField(allow_null=True, required=False)
    color_tema = serializers.CharField(allow_null=True, required=False)


class UsuarioEmpresaItemSerializer(serializers.ModelSerializer):
    usuario_id = serializers.IntegerField(source='usuario.id', read_only=True)
    username = serializers.CharField(source='usuario.username', read_only=True)
    email = serializers.CharField(source='usuario.email', read_only=True)
    empresa_id = serializers.IntegerField(source='empresa.id', read_only=True)
    empresa_razon_social = serializers.CharField(source='empresa.razon_social', read_only=True)

    class Meta:
        model = UsuarioEmpresa
        fields = [
            'id',
            'usuario_id',
            'username',
            'email',
            'empresa_id',
            'empresa_razon_social',
            'rol',
            'activo',
        ]


class AsignarUsuarioRequestSerializer(serializers.Serializer):
    usuario_id = serializers.IntegerField(required=True)
    rol = serializers.ChoiceField(choices=ROLES_EMPRESA, default='USUARIO')
    activo = serializers.BooleanField(default=True)

    def validate_usuario_id(self, value):
        if not Usuario.objects.filter(id=value, activo=True).exists():
            raise serializers.ValidationError("El usuario especificado no existe o no se encuentra activo.")
        return value


class UsuarioAsignacionItemSerializer(serializers.ModelSerializer):
    empresa_id = serializers.IntegerField(source='empresa.id', read_only=True)
    empresa_ruc = serializers.CharField(source='empresa.ruc', read_only=True)
    empresa_razon_social = serializers.CharField(source='empresa.razon_social', read_only=True)

    class Meta:
        model = UsuarioEmpresa
        fields = [
            'id',
            'empresa_id',
            'empresa_ruc',
            'empresa_razon_social',
            'rol',
            'activo',
        ]


class UsuarioEstudioListSerializer(serializers.ModelSerializer):
    asignaciones = UsuarioAsignacionItemSerializer(source='empresas_asignadas', many=True, read_only=True)
    is_active = serializers.BooleanField(source='activo', read_only=True)
    is_staff = serializers.BooleanField(source='es_admin_global', read_only=True)
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    last_login = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = [
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'activo',
            'is_active',
            'es_admin_global',
            'is_staff',
            'last_login',
            'asignaciones',
        ]

    def get_first_name(self, obj):
        return getattr(obj, 'first_name', '')

    def get_last_name(self, obj):
        return getattr(obj, 'last_name', '')

    def get_last_login(self, obj):
        return getattr(obj, 'last_login', None)


class AsignacionEmpresaInputSerializer(serializers.Serializer):
    empresa_id = serializers.IntegerField(required=True)
    rol = serializers.ChoiceField(choices=ROLES_EMPRESA, default='USUARIO')
    activo = serializers.BooleanField(default=True)


class UsuarioCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=True, trim_whitespace=True)
    email = serializers.EmailField(max_length=254, required=True, trim_whitespace=True)
    password_inicial = serializers.CharField(min_length=8, required=True, write_only=True)
    asignaciones = AsignacionEmpresaInputSerializer(many=True, required=False, default=list)

    def validate_username(self, value):
        if Usuario.objects.filter(username=value).exists():
            raise serializers.ValidationError("Ya existe un usuario con este nombre de usuario.")
        return value

    def validate_email(self, value):
        if Usuario.objects.filter(email=value).exists():
            raise serializers.ValidationError("Ya existe un usuario con este correo electrónico.")
        return value

    def validate_password_inicial(self, value):
        return validar_password_segura(value, username=self.initial_data.get('username'),
                                       email=self.initial_data.get('email'))


class UsuarioUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254, required=False)
    is_active = serializers.BooleanField(required=False)
    activo = serializers.BooleanField(required=False)
    asignaciones = AsignacionEmpresaInputSerializer(many=True, required=False)

    def validate_email(self, value):
        usuario_id = self.context.get('usuario_id')
        if Usuario.objects.filter(email=value).exclude(id=usuario_id).exists():
            raise serializers.ValidationError("Ya existe un usuario con este correo electrónico.")
        return value


class ResetPasswordAdminSerializer(serializers.Serializer):
    password_nuevo = serializers.CharField(required=True, write_only=True)

    def validate_password_nuevo(self, value):
        usuario = self.context.get('usuario')
        return validar_password_segura(value, username=getattr(usuario, 'username', None),
                                       email=getattr(usuario, 'email', None))


class CambiarPasswordSerializer(serializers.Serializer):
    password_actual = serializers.CharField(required=True, write_only=True)
    password_nuevo = serializers.CharField(required=True, write_only=True)

    def validate_password_nuevo(self, value):
        usuario = self.context.get('usuario')
        return validar_password_segura(value, username=getattr(usuario, 'username', None),
                                       email=getattr(usuario, 'email', None))

    def validate(self, attrs):
        if attrs['password_actual'] == attrs['password_nuevo']:
            raise serializers.ValidationError({"password_nuevo": "La nueva contraseña debe ser diferente de la actual."})
        return attrs

