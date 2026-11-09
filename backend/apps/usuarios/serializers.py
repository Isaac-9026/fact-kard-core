from rest_framework import serializers
from apps.usuarios.models import Usuario, UsuarioEmpresa


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
    rol = serializers.ChoiceField(choices=['ADMIN', 'USUARIO'], default='USUARIO')
    activo = serializers.BooleanField(default=True)

    def validate_usuario_id(self, value):
        if not Usuario.objects.filter(id=value, activo=True).exists():
            raise serializers.ValidationError("El usuario especificado no existe o no se encuentra activo.")
        return value
