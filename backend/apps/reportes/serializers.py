from rest_framework import serializers


class KardexFilaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    fecha = serializers.DateField()
    documento_referencia = serializers.CharField(allow_blank=True)
    tipo_operacion_codigo = serializers.CharField(allow_blank=True)
    tipo_operacion_descripcion = serializers.CharField(allow_blank=True)
    naturaleza = serializers.CharField()
    almacen_codigo = serializers.CharField(allow_blank=True)
    almacen_nombre = serializers.CharField(allow_blank=True)
    producto_id = serializers.IntegerField()
    producto_codigo = serializers.CharField(allow_blank=True)
    producto_descripcion = serializers.CharField(allow_blank=True)

    # Bloque Entradas
    entrada_cantidad = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)
    entrada_costo_unitario = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)
    entrada_valor = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)

    # Bloque Salidas
    salida_cantidad = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)
    salida_costo_unitario = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)
    salida_valor = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)

    # Bloque Saldo Final
    saldo_cantidad = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)
    cpp = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)
    saldo_valor = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)

    # Metadatos del motor
    prioridad_dia = serializers.IntegerField()
    secuencia = serializers.IntegerField()
    es_extorno = serializers.BooleanField()
    # BE-005: trazabilidad del extorno hacia el movimiento y la operación originales.
    movimiento_extornado_id = serializers.IntegerField(allow_null=True, required=False)
    operacion_extornada_codigo = serializers.CharField(allow_null=True, required=False)
    generado_por_motor = serializers.BooleanField()
    creado_en = serializers.DateTimeField()


class KardexResumenSerializer(serializers.Serializer):
    total_entradas_cantidad = serializers.DecimalField(max_digits=20, decimal_places=8)
    total_entradas_valor = serializers.DecimalField(max_digits=20, decimal_places=8)
    total_salidas_cantidad = serializers.DecimalField(max_digits=20, decimal_places=8)
    total_salidas_valor = serializers.DecimalField(max_digits=20, decimal_places=8)
    # CON-014: saldo de arranque del filtro (estado anterior a la fecha inicial).
    saldo_inicial_cantidad = serializers.DecimalField(max_digits=20, decimal_places=8)
    saldo_inicial_valor = serializers.DecimalField(max_digits=20, decimal_places=8)
    saldo_final_cantidad = serializers.DecimalField(max_digits=20, decimal_places=8)
    cpp_final = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)
    saldo_final_valor = serializers.DecimalField(max_digits=20, decimal_places=8)
    total_registros = serializers.IntegerField()
    # EMPRESA: saldo contable real del motor. ALMACEN: stock del almacén × CPP global.
    ambito_saldo = serializers.CharField()


class KardexSaldoInicialSerializer(serializers.Serializer):
    producto_id = serializers.IntegerField()
    producto_codigo = serializers.CharField(allow_blank=True)
    cantidad = serializers.DecimalField(max_digits=20, decimal_places=8)
    cpp = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)
    valor = serializers.DecimalField(max_digits=20, decimal_places=8)


class KardexReporteResponseSerializer(serializers.Serializer):
    empresa_id = serializers.IntegerField()
    filtros = serializers.DictField()
    resumen = KardexResumenSerializer()
    saldos_iniciales = KardexSaldoInicialSerializer(many=True)
    movimientos = KardexFilaSerializer(many=True)


class PilotoComparacionSerializer(serializers.Serializer):
    periodo_id = serializers.IntegerField(min_value=1)
    producto_id = serializers.IntegerField(min_value=1)
    cantidad_esperada = serializers.DecimalField(max_digits=20, decimal_places=8)
    cpp_esperado = serializers.DecimalField(max_digits=20, decimal_places=8)
    valor_esperado = serializers.DecimalField(max_digits=20, decimal_places=8)
    tiempo_manual_segundos = serializers.DecimalField(max_digits=20, decimal_places=8)
    tiempo_factkard_segundos = serializers.DecimalField(max_digits=20, decimal_places=8)
