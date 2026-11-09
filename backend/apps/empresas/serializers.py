import re
from decimal import Decimal

from rest_framework import serializers

from apps.catalogos.models import Moneda
from apps.empresas.models import CierrePeriodo, CierrePeriodoDetalle, ConfigEmpresa, ConfigIgvPeriodo, Empresa, Establecimiento, Periodo, TasaIgvVigencia
from apps.empresas.validators import validar_color_tema, validar_logo_archivo


class EmpresaSerializer(serializers.ModelSerializer):
    moneda_base_codigo = serializers.PrimaryKeyRelatedField(
        queryset=Moneda.objects.all()
    )
    rol = serializers.SerializerMethodField()
    logo = serializers.FileField(required=False, allow_null=True)
    color_tema = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=7)

    class Meta:
        model = Empresa
        fields = (
            'id', 'ruc', 'razon_social', 'nombre_comercial', 'direccion',
            'moneda_base_codigo', 'estado', 'creado_en', 'rol', 'logo', 'color_tema',
        )
        read_only_fields = ('id', 'estado', 'creado_en', 'rol')

    def get_rol(self, obj):
        return getattr(obj, 'rol_usuario', None)

    def validate_logo(self, archivo):
        if not archivo or isinstance(archivo, str):
            return archivo
        return validar_logo_archivo(archivo)

    def validate_color_tema(self, valor):
        return validar_color_tema(valor)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if instance.logo:
            try:
                url = instance.logo.url
                request = self.context.get('request')
                if request is not None:
                    ret['logo'] = request.build_absolute_uri(url)
                else:
                    ret['logo'] = url
            except Exception:
                ret['logo'] = str(instance.logo)
        else:
            ret['logo'] = None
        return ret


class EmpresaIdentidadSerializer(serializers.ModelSerializer):
    logo = serializers.FileField(required=False, allow_null=True)
    color_tema = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=7)

    class Meta:
        model = Empresa
        fields = ('logo', 'color_tema', 'nombre_comercial', 'direccion')

    def validate_logo(self, archivo):
        if not archivo or isinstance(archivo, str):
            return archivo
        return validar_logo_archivo(archivo)

    def validate_color_tema(self, valor):
        return validar_color_tema(valor)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if instance.logo:
            try:
                url = instance.logo.url
                request = self.context.get('request')
                if request is not None:
                    ret['logo'] = request.build_absolute_uri(url)
                else:
                    ret['logo'] = url
            except Exception:
                ret['logo'] = str(instance.logo)
        else:
            ret['logo'] = None
        return ret


def _validar_ubigeo(valor):
    from apps.documentos.reglas_tributarias import ubigeo_valido
    valor = (valor or '').strip() or None
    if valor is not None and not ubigeo_valido(valor):
        raise serializers.ValidationError(
            'El ubigeo debe tener 6 dígitos INEI (departamento 01-25, provincia y distrito 01-99).')
    return valor


class EstablecimientoSerializer(serializers.ModelSerializer):
    # Bloque 17A: el principal es ConfigEmpresa.establecimiento_principal (no se duplica).
    es_principal = serializers.SerializerMethodField()

    class Meta:
        model = Establecimiento
        fields = ('id', 'codigo_sunat', 'nombre', 'activo', 'direccion', 'ubigeo', 'es_principal')
        read_only_fields = ('id', 'es_principal')

    def get_es_principal(self, obj):
        from apps.documentos.reglas_tributarias import establecimiento_es_principal
        return establecimiento_es_principal(obj)

    def validate_ubigeo(self, valor):
        return _validar_ubigeo(valor)

    def validate_direccion(self, valor):
        return (valor or '').strip() or None


class DatosFiscalesEmpresaSerializer(serializers.ModelSerializer):
    """
    Bloque 17A: datos del emisor electrónico de la empresa activa. Reutiliza ruc, razon_social,
    nombre_comercial y direccion (= domicilio fiscal); el RUC no se edita aquí.
    """
    class Meta:
        model = Empresa
        fields = ('id', 'ruc', 'razon_social', 'nombre_comercial', 'direccion', 'ubigeo', 'departamento',
                  'provincia', 'distrito', 'codigo_pais')
        read_only_fields = ('id', 'ruc')

    def validate_ubigeo(self, valor):
        return _validar_ubigeo(valor)

    def validate_codigo_pais(self, valor):
        valor = (valor or '').strip().upper()
        if not re.fullmatch(r'[A-Z]{2}', valor):
            raise serializers.ValidationError('Código de país ISO 3166 de 2 letras (PE).')
        return valor

    def validate_razon_social(self, valor):
        valor = (valor or '').strip()
        if not valor:
            raise serializers.ValidationError('La razón social es obligatoria.')
        return valor

    def validate(self, attrs):
        for campo in ('nombre_comercial', 'direccion', 'departamento', 'provincia', 'distrito'):
            if campo in attrs:
                attrs[campo] = (attrs[campo] or '').strip() or None
        return attrs


class ConfigEmpresaSerializer(serializers.ModelSerializer):
    tolerancia_residuo_pen = serializers.DecimalField(
        max_digits=20,
        decimal_places=8,
        coerce_to_string=True,
    )
    # Bloque 4: tasa del IGV en porcentaje (18.00 por defecto). Solo ADMIN puede cambiarla.
    tasa_igv_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, coerce_to_string=True,
        min_value=Decimal('0.01'), max_value=Decimal('100'),
    )
    # Bloque 5: fecha desde la que rige la nueva tasa (hoy si se omite) y su historial.
    tasa_igv_vigente_desde = serializers.DateField(required=False, write_only=True)
    tasas_igv = serializers.SerializerMethodField()
    establecimiento_principal = serializers.PrimaryKeyRelatedField(
        queryset=Establecimiento.objects.none(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = ConfigEmpresa
        fields = (
            'id', 'empresa', 'tolerancia_residuo_pen', 'decimales_calculo',
            'regla_redondeo', 'metodo_valuacion', 'establecimiento_principal', 'tasa_igv_pct',
            'tasa_igv_vigente_desde', 'tasas_igv',
        )
        read_only_fields = ('id', 'empresa', 'regla_redondeo', 'metodo_valuacion')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empresa_id = self.context.get('empresa_id')
        if empresa_id:
            self.fields['establecimiento_principal'].queryset = (
                Establecimiento.objects.filter(empresa_id=empresa_id)
            )

    def validate_tolerancia_residuo_pen(self, value):
        if not isinstance(value, Decimal):
            value = Decimal(value)
        if value < Decimal('0.00000000'):
            raise serializers.ValidationError('La tolerancia no puede ser negativa.')
        return value

    def validate_decimales_calculo(self, value):
        if not 2 <= value <= 8:
            raise serializers.ValidationError('Debe estar entre 2 y 8.')
        return value

    def get_tasas_igv(self, obj):
        return [
            {'vigente_desde': v.vigente_desde.isoformat(), 'tasa_pct': str(v.tasa_pct)}
            for v in TasaIgvVigencia.objects.filter(empresa_id=obj.empresa_id)
        ]

    def update(self, instance, validated_data):
        if 'tasa_igv_pct' in validated_data or 'tasa_igv_vigente_desde' in validated_data:
            from django.utils import timezone

            from apps.empresas.services import registrar_tasa_igv
            nueva = validated_data.get('tasa_igv_pct', instance.tasa_igv_pct)
            desde = validated_data.get('tasa_igv_vigente_desde') or timezone.localdate()
            if nueva != instance.tasa_igv_pct or 'tasa_igv_vigente_desde' in validated_data:
                registrar_tasa_igv(config=instance, tasa_pct=nueva, vigente_desde=desde,
                                   usuario_id=self.context.get('usuario_id'))
        instance.tolerancia_residuo_pen = validated_data.get(
            'tolerancia_residuo_pen', instance.tolerancia_residuo_pen
        )
        instance.decimales_calculo = validated_data.get(
            'decimales_calculo', instance.decimales_calculo
        )
        if 'establecimiento_principal' in validated_data:
            instance.establecimiento_principal = validated_data['establecimiento_principal']
        instance.regla_redondeo = 'ROUND_HALF_UP'
        instance.metodo_valuacion = 'CPP'
        instance.save(update_fields=(
            'tolerancia_residuo_pen', 'decimales_calculo',
            'establecimiento_principal', 'regla_redondeo', 'metodo_valuacion', 'tasa_igv_pct',
        ))
        return instance


class ConfigIgvPeriodoSerializer(serializers.ModelSerializer):
    periodo = serializers.PrimaryKeyRelatedField(
        queryset=Periodo.objects.all(),
        required=False,
    )
    porcentaje_recuperable = serializers.DecimalField(
        max_digits=7,
        decimal_places=4,
        required=False,
        allow_null=True,
        coerce_to_string=True,
    )

    class Meta:
        model = ConfigIgvPeriodo
        fields = (
            'id', 'empresa', 'periodo', 'metodo',
            'porcentaje_recuperable', 'creado_por', 'creado_en',
        )
        read_only_fields = ('id', 'empresa', 'creado_por', 'creado_en')

    def validate_periodo(self, value):
        empresa_id = self.context.get('empresa_id')
        if empresa_id and value.empresa_id != empresa_id:
            raise serializers.ValidationError("El período no pertenece a la empresa activa.")
        if self.instance and self.instance.periodo_id != value.id:
            raise serializers.ValidationError("No se puede cambiar el período asignado a esta configuración.")
        if value.estado != 'ABIERTO':
            raise serializers.ValidationError("No se puede configurar el IGV de un período cerrado.")
        return value

    def validate(self, attrs):
        periodo = attrs.get('periodo') or (self.instance.periodo if self.instance else None)
        if periodo and periodo.estado != 'ABIERTO':
            raise serializers.ValidationError({
                'periodo': 'No se puede configurar ni modificar el IGV de un período cerrado.'
            })

        metodo = attrs.get('metodo')
        if not metodo and self.instance:
            metodo = self.instance.metodo

        if metodo == 'TOTAL':
            attrs['porcentaje_recuperable'] = Decimal('100.0000')
        elif metodo == 'NULO':
            attrs['porcentaje_recuperable'] = Decimal('0.0000')
        elif metodo == 'PRORRATA':
            porcentaje = attrs.get('porcentaje_recuperable')
            if porcentaje is None and self.instance:
                porcentaje = self.instance.porcentaje_recuperable
            if porcentaje is None:
                raise serializers.ValidationError(
                    {'porcentaje_recuperable': 'El porcentaje recuperable es obligatorio para el método PRORRATA.'}
                )
            if not isinstance(porcentaje, Decimal):
                porcentaje = Decimal(str(porcentaje))
            if not (Decimal('0.0000') <= porcentaje <= Decimal('100.0000')):
                raise serializers.ValidationError(
                    {'porcentaje_recuperable': 'El porcentaje recuperable debe estar entre 0.0000 y 100.0000.'}
                )
            attrs['porcentaje_recuperable'] = porcentaje
        elif metodo is not None:
            raise serializers.ValidationError(
                {'metodo': f"Método '{metodo}' no válido. Opciones: TOTAL, NULO, PRORRATA."}
            )

        return attrs


class PeriodoSerializer(serializers.ModelSerializer):
    config_igv = serializers.SerializerMethodField()

    class Meta:
        model = Periodo
        fields = (
            'id', 'empresa', 'anio', 'mes', 'orden',
            'fecha_inicio', 'fecha_fin', 'estado',
            'motivo_desactualizado', 'cerrado_por', 'cerrado_en',
            'reabierto_por', 'reabierto_en', 'motivo_reapertura',
            'config_igv',
        )
        read_only_fields = (
            'id', 'empresa', 'orden', 'estado',
            'motivo_desactualizado', 'cerrado_por', 'cerrado_en',
            'reabierto_por', 'reabierto_en', 'motivo_reapertura',
            'config_igv',
        )

    def get_config_igv(self, obj):
        cfg = obj.configs_igv.first()
        if cfg:
            return {
                'id': cfg.id,
                'metodo': cfg.metodo,
                'porcentaje_recuperable': str(cfg.porcentaje_recuperable),
                'creado_en': cfg.creado_en.isoformat() if cfg.creado_en else None,
            }
        return None


class PeriodoCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Periodo
        fields = ('id', 'anio', 'mes', 'fecha_inicio', 'fecha_fin')
        read_only_fields = ('id',)

    def validate_mes(self, value):
        if not 1 <= value <= 12:
            raise serializers.ValidationError('El mes debe estar comprendido entre 1 y 12.')
        return value

    def validate(self, attrs):
        fecha_inicio = attrs.get('fecha_inicio')
        fecha_fin = attrs.get('fecha_fin')
        if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
            raise serializers.ValidationError(
                {'fecha_fin': 'La fecha de fin debe ser posterior o igual a la fecha de inicio.'}
            )

        empresa_id = self.context.get('empresa_id')
        anio = attrs.get('anio')
        mes = attrs.get('mes')
        if empresa_id and anio and mes:
            if Periodo.objects.filter(empresa_id=empresa_id, anio=anio, mes=mes).exists():
                raise serializers.ValidationError(
                    {'non_field_errors': [f'Ya existe un período registrado para {anio}-{mes:02d}.']}
                )

        return attrs

    def create(self, validated_data):
        empresa_id = self.context['empresa_id']
        validated_data['empresa_id'] = empresa_id
        validated_data['orden'] = validated_data['anio'] * 100 + validated_data['mes']
        validated_data['estado'] = 'ABIERTO'
        return super().create(validated_data)


class ReabrirPeriodoSerializer(serializers.Serializer):
    motivo_reapertura = serializers.CharField(
        min_length=3,
        max_length=500,
        required=True,
        error_messages={'required': 'El motivo de reapertura es obligatorio.'}
    )


class CierrePeriodoDetalleSerializer(serializers.ModelSerializer):
    producto_codigo = serializers.CharField(source='producto.codigo_interno', read_only=True)
    producto_descripcion = serializers.CharField(source='producto.descripcion', read_only=True)
    establecimiento_nombre = serializers.CharField(source='establecimiento.nombre', read_only=True)

    class Meta:
        model = CierrePeriodoDetalle
        fields = ('id', 'producto', 'producto_codigo', 'producto_descripcion', 'establecimiento', 'establecimiento_nombre', 'saldo_cantidad', 'saldo_valor_pen', 'cpp_pen')


class CierrePeriodoSerializer(serializers.ModelSerializer):
    detalles = CierrePeriodoDetalleSerializer(many=True, read_only=True)
    periodo_info = serializers.SerializerMethodField()
    cerrado_por_username = serializers.CharField(source='cerrado_por.username', read_only=True)

    class Meta:
        model = CierrePeriodo
        fields = ('id', 'periodo', 'periodo_info', 'version_calculo', 'cerrado_por', 'cerrado_por_username', 'cerrado_en', 'archivo_excel', 'hash_resultado', 'snapshot_resumen', 'vigente', 'detalles')

    def get_periodo_info(self, obj):
        return {'anio': obj.periodo.anio, 'mes': obj.periodo.mes, 'estado': obj.periodo.estado}
