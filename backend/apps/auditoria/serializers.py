from rest_framework import serializers
from apps.auditoria.models import Auditoria


class AuditoriaSerializer(serializers.ModelSerializer):
    usuario_username = serializers.CharField(source='usuario.username', read_only=True, default=None)
    empresa_razon_social = serializers.CharField(source='empresa.razon_social', read_only=True, default=None)

    class Meta:
        model = Auditoria
        fields = [
            'id',
            'empresa_id',
            'empresa_razon_social',
            'usuario_id',
            'usuario_username',
            'accion',
            'entidad',
            'registro_id',
            'valor_anterior',
            'valor_nuevo',
            'motivo',
            'fecha',
        ]
        read_only_fields = fields
