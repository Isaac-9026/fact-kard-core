"""
Bloque 16 — flujo comercial y financiero sobre `documento` (sin módulos paralelos).

- Series y correlativos de VENTA: el número lo asigna el backend con la fila de la serie
  bloqueada (select_for_update) en la misma transacción que crea el comprobante.
- Condición de pago: CONTADO o CREDITO (vencimiento obligatorio y cuotas opcionales cuya suma
  es exactamente el total).
- Pagos/cobros: sobre comprobantes CONFIRMADOS (no notas), en su moneda, sin superar el saldo.
- Cuentas por cobrar/pagar: SIEMPRE calculadas (total ± notas − pagos vigentes); no se guarda
  ningún saldo.

Todo en Decimal con 8 decimales y ROUND_HALF_UP. Nada de esto toca Kardex, CPP ni stock.
"""
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import (
    Case, CharField, DecimalField, Exists, F, OuterRef, Q, Subquery, Sum, Value, When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import registrar_auditoria

OCHO = Decimal('0.00000001')
CERO = Decimal('0')
CONDICIONES_PAGO = ('CONTADO', 'CREDITO')
MAX_CORRELATIVO = 99999999
DIGITOS_CORRELATIVO = 8
DEC = DecimalField(max_digits=20, decimal_places=8)


def q8(valor):
    return Decimal(valor).quantize(OCHO, rounding=ROUND_HALF_UP)


def texto(valor):
    """Importe como texto de 8 decimales ('0.00000000', nunca '0E-8')."""
    return format(q8(valor), 'f')


def hoy():
    return timezone.localdate()


# ---- Series --------------------------------------------------------------------------------

def validar_formato_serie(serie, tipo_comprobante):
    """Serie de 4 caracteres; factura con F, boleta con B, notas con F o B."""
    serie = (serie or '').strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{4}', serie):
        raise ValidationError({'serie': 'La serie debe tener exactamente 4 caracteres (letras mayúsculas o dígitos).'})
    codigo = tipo_comprobante.codigo_sunat
    prefijos = {'01': ('F',), '03': ('B',), '07': ('F', 'B'), '08': ('F', 'B')}.get(codigo)
    if prefijos and not serie.startswith(prefijos):
        raise ValidationError({'serie': f"La serie de {tipo_comprobante.descripcion.lower()} debe empezar con {' o '.join(prefijos)}."})
    return serie


def formato_correlativo(numero):
    return str(numero).zfill(DIGITOS_CORRELATIVO)


def asignar_correlativo(*, empresa_id, usuario_id, serie_id, tipo_comprobante, almacen_ids):
    """
    Bloquea la serie, valida que sea de la empresa (IDOR), activa, del mismo tipo de
    comprobante y del establecimiento de los almacenes de las líneas; incrementa y devuelve
    (serie, numero_texto). Debe llamarse dentro de la transacción que crea el documento:
    si la creación falla, el incremento se revierte con ella (sin huecos).
    """
    from apps.documentos.models import SerieComprobante
    from apps.inventario.models import Almacen

    serie = (SerieComprobante.objects.select_for_update().select_related('establecimiento', 'tipo_comprobante')
             .filter(pk=serie_id, empresa_id=empresa_id).first())
    if serie is None:
        raise ValidationError({'serie_comprobante': 'La serie no existe o no pertenece a la empresa activa.'})
    if not serie.activo:
        raise ValidationError({'serie_comprobante': f'La serie {serie.serie} está inactiva.'})
    if serie.tipo_comprobante_id != tipo_comprobante.id:
        raise ValidationError({'serie_comprobante': (
            f'La serie {serie.serie} es de {serie.tipo_comprobante.descripcion.lower()}, no de '
            f'{tipo_comprobante.descripcion.lower()}.'
        )})
    otros = set(Almacen.objects.filter(pk__in=almacen_ids, empresa_id=empresa_id)
                .exclude(establecimiento_id=serie.establecimiento_id).values_list('codigo', flat=True))
    if otros:
        raise ValidationError({'serie_comprobante': (
            f'La serie {serie.serie} es del establecimiento {serie.establecimiento.codigo_sunat}; '
            f"los almacenes {', '.join(sorted(otros))} son de otro establecimiento."
        )})
    if serie.ultimo_correlativo >= MAX_CORRELATIVO:
        raise ValidationError({'serie_comprobante': f'La serie {serie.serie} llegó a su número máximo.'})
    anterior = serie.ultimo_correlativo
    serie.ultimo_correlativo = anterior + 1
    serie.actualizado_en = timezone.now()
    serie.save(update_fields=['ultimo_correlativo', 'actualizado_en'])
    numero = formato_correlativo(serie.ultimo_correlativo)
    registrar_auditoria(
        empresa_id=empresa_id, usuario_id=usuario_id, accion='ASIGNAR_CORRELATIVO', entidad='SERIE_COMPROBANTE',
        registro_id=serie.id, valor_anterior={'ultimo_correlativo': anterior},
        valor_nuevo={'ultimo_correlativo': serie.ultimo_correlativo, 'comprobante': f'{serie.serie}-{numero}'},
        motivo='Correlativo asignado a un comprobante de venta',
    )
    return serie, numero


def validar_serie_manual(*, empresa_id, clase, tipo_comprobante, serie_normalizada, origen_captura):
    """
    Una venta registrada a mano no puede escribir el número de una serie con correlativo
    automático (chocaría con el siguiente número que asigne el sistema).
    """
    from apps.documentos.models import SerieComprobante
    if clase != 'VENTA' or (origen_captura or 'MANUAL') != 'MANUAL':
        return
    if SerieComprobante.objects.filter(empresa_id=empresa_id, tipo_comprobante=tipo_comprobante,
                                       serie=serie_normalizada).exists():
        raise ValidationError({'serie': (
            f'La serie {serie_normalizada} tiene correlativo automático: elíjala en "Serie" y el número '
            'lo asigna el sistema.'
        )})


# ---- Condición de pago y cuotas ------------------------------------------------------------

def _fecha(valor, campo):
    if valor in (None, ''):
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ValidationError({campo: 'Fecha inválida (use AAAA-MM-DD).'})


def _decimal(valor, campo):
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({campo: 'Monto inválido.'})
    if not numero.is_finite():
        raise ValidationError({campo: 'Monto inválido.'})
    return q8(numero)


def normalizar_condicion_pago(*, condicion, fecha_vencimiento, cuotas, total, fecha_emision, es_nota):
    """
    (condicion, fecha_vencimiento, [(numero, fecha, monto)]). Reglas:
    - CONTADO: sin vencimiento ni cuotas.
    - CREDITO: vencimiento obligatorio, no anterior a la emisión. Cuotas opcionales: montos > 0,
      fechas entre la emisión y el vencimiento, la última cae en el vencimiento y
      suma(cuotas) == total (8 decimales, ROUND_HALF_UP).
    - Notas de crédito/débito: siempre CONTADO (ajustan el saldo de su comprobante de origen).
    """
    condicion = (condicion or 'CONTADO').strip().upper()
    if condicion not in CONDICIONES_PAGO:
        raise ValidationError({'condicion_pago': 'La condición de pago debe ser CONTADO o CREDITO.'})
    fecha_vencimiento = _fecha(fecha_vencimiento, 'fecha_vencimiento')
    cuotas = list(cuotas or [])
    if es_nota and (condicion != 'CONTADO' or cuotas):
        raise ValidationError({'condicion_pago': (
            'Una nota de crédito/débito no tiene condición de pago propia: ajusta el saldo de su comprobante de origen.'
        )})
    if condicion == 'CONTADO':
        if fecha_vencimiento or cuotas:
            raise ValidationError({'condicion_pago': 'Un comprobante al CONTADO no lleva vencimiento ni cuotas.'})
        return 'CONTADO', None, []
    if fecha_vencimiento is None:
        raise ValidationError({'fecha_vencimiento': 'La fecha de vencimiento es obligatoria para un comprobante a CRÉDITO.'})
    if fecha_emision and fecha_vencimiento < fecha_emision:
        raise ValidationError({'fecha_vencimiento': 'El vencimiento no puede ser anterior a la fecha de emisión.'})
    normalizadas = []
    for i, cuota in enumerate(cuotas, start=1):
        fecha = _fecha(cuota.get('fecha_vencimiento'), f'cuotas[{i}].fecha_vencimiento')
        if fecha is None:
            raise ValidationError({'cuotas': f'Cuota {i}: la fecha de vencimiento es obligatoria.'})
        monto = _decimal(cuota.get('monto'), f'cuotas[{i}].monto')
        if monto <= CERO:
            raise ValidationError({'cuotas': f'Cuota {i}: el monto debe ser mayor a 0.'})
        if fecha_emision and fecha < fecha_emision:
            raise ValidationError({'cuotas': f'Cuota {i}: vence antes de la fecha de emisión.'})
        if fecha > fecha_vencimiento:
            raise ValidationError({'cuotas': f'Cuota {i}: vence después del vencimiento del comprobante.'})
        if normalizadas and fecha < normalizadas[-1][1]:
            raise ValidationError({'cuotas': 'Las cuotas deben estar en orden de vencimiento.'})
        normalizadas.append((i, fecha, monto))
    if normalizadas:
        suma = q8(sum((m for _, _, m in normalizadas), CERO))
        if suma != q8(total):
            raise ValidationError({'cuotas': (
                f'La suma de las cuotas ({suma.normalize():f}) debe ser igual al total del comprobante '
                f'({q8(total).normalize():f}).'
            )})
        if normalizadas[-1][1] != fecha_vencimiento:
            raise ValidationError({'cuotas': 'La última cuota debe vencer en la fecha de vencimiento del comprobante.'})
    return 'CREDITO', fecha_vencimiento, normalizadas


def guardar_condicion_pago(documento, condicion, fecha_vencimiento, cuotas):
    from apps.documentos.models import DocumentoCuota
    documento.condicion_pago = condicion
    documento.fecha_vencimiento = fecha_vencimiento
    documento.save(update_fields=['condicion_pago', 'fecha_vencimiento'])
    documento.cuotas.all().delete()
    DocumentoCuota.objects.bulk_create([
        DocumentoCuota(empresa_id=documento.empresa_id, documento=documento, numero=n, fecha_vencimiento=f, monto=m)
        for n, f, m in cuotas
    ])


@transaction.atomic
def cambiar_condicion_pago(*, documento_id, empresa_id, usuario_id, condicion, fecha_vencimiento, cuotas, motivo=''):
    from apps.documentos.models import Documento
    doc = (Documento.objects.select_for_update().select_related('tipo_comprobante')
           .filter(pk=documento_id, empresa_id=empresa_id).first())
    if doc is None:
        raise ValidationError({'detail': 'El documento no existe o no pertenece a la empresa activa.'})
    if doc.estado == 'ANULADO':
        raise ValidationError({'detail': 'No se cambia la condición de pago de un comprobante ANULADO.'})
    if doc.pagos.filter(estado='VIGENTE').exists():
        raise ValidationError({'detail': 'El comprobante tiene pagos registrados: anúlelos antes de cambiar la condición de pago.'})
    antes = {'condicion_pago': doc.condicion_pago, 'fecha_vencimiento': str(doc.fecha_vencimiento) if doc.fecha_vencimiento else None,
             'cuotas': [[c.numero, str(c.fecha_vencimiento), str(c.monto)] for c in doc.cuotas.all()]}
    condicion, venc, normalizadas = normalizar_condicion_pago(
        condicion=condicion, fecha_vencimiento=fecha_vencimiento, cuotas=cuotas, total=doc.total or CERO,
        fecha_emision=doc.fecha_emision, es_nota=doc.tipo_comprobante.es_nota,
    )
    guardar_condicion_pago(doc, condicion, venc, normalizadas)
    registrar_auditoria(
        empresa_id=empresa_id, usuario_id=usuario_id, accion='CAMBIAR_CONDICION_PAGO', entidad='DOCUMENTO',
        registro_id=doc.id, valor_anterior=antes,
        valor_nuevo={'condicion_pago': condicion, 'fecha_vencimiento': str(venc) if venc else None,
                     'cuotas': [[n, str(f), str(m)] for n, f, m in normalizadas]},
        motivo=motivo or 'Cambio de condición de pago',
    )
    return doc


# ---- Saldos (siempre calculados) -----------------------------------------------------------

def anotar_finanzas(qs, fecha_corte=None):
    """
    Anota en un queryset de `Documento` (no notas): total_notas_credito, total_notas_debito,
    total_ajustado, pagado, saldo_pendiente, monto_vencido y estado_financiero.

    - Notas: solo las CONFIRMADAS cuyo origen es el documento.
    - Vencido: con cuotas, lo exigible a la fecha es la suma de cuotas vencidas y está vencido
      si (pagado + NC − ND) no la cubre; sin cuotas, vence en fecha_vencimiento (o la emisión
      si es al contado).
    """
    from apps.documentos.models import Documento, DocumentoCuota, PagoDocumento
    fecha_corte = fecha_corte or hoy()

    def suma_notas(efecto):
        return Coalesce(Subquery(
            Documento.objects.filter(documento_origen=OuterRef('pk'), estado='CONFIRMADO',
                                     tipo_comprobante__efecto_nota=efecto)
            .order_by().values('documento_origen').annotate(s=Sum('total')).values('s')[:1],
            output_field=DEC), Value(CERO), output_field=DEC)

    pagado = Coalesce(Subquery(
        PagoDocumento.objects.filter(documento=OuterRef('pk'), estado='VIGENTE')
        .order_by().values('documento').annotate(s=Sum('monto')).values('s')[:1], output_field=DEC),
        Value(CERO), output_field=DEC)
    cuotas_vencidas = Coalesce(Subquery(
        DocumentoCuota.objects.filter(documento=OuterRef('pk'), fecha_vencimiento__lt=fecha_corte)
        .order_by().values('documento').annotate(s=Sum('monto')).values('s')[:1], output_field=DEC),
        Value(CERO), output_field=DEC)
    qs = qs.annotate(
        total_notas_credito=suma_notas('CREDITO'),
        total_notas_debito=suma_notas('DEBITO'),
        pagado=pagado,
        tiene_cuotas=Exists(DocumentoCuota.objects.filter(documento=OuterRef('pk'))),
        cuotas_vencidas=cuotas_vencidas,
    ).annotate(
        total_ajustado=Coalesce(F('total'), Value(CERO), output_field=DEC) + F('total_notas_debito') - F('total_notas_credito'),
    ).annotate(
        saldo_pendiente=F('total_ajustado') - F('pagado'),
    ).annotate(
        monto_vencido=Case(
            When(saldo_pendiente__lte=0, then=Value(CERO)),
            When(tiene_cuotas=True,
                 then=F('cuotas_vencidas') - F('pagado') - F('total_notas_credito') + F('total_notas_debito')),
            When(Q(fecha_vencimiento__lt=fecha_corte) | Q(fecha_vencimiento__isnull=True, fecha_emision__lt=fecha_corte),
                 then=F('saldo_pendiente')),
            default=Value(CERO), output_field=DEC,
        ),
    ).annotate(
        estado_financiero=Case(
            When(saldo_pendiente__lte=0, then=Value('PAGADO')),
            When(monto_vencido__gt=0, then=Value('VENCIDO')),
            When(pagado__gt=0, then=Value('PARCIAL')),
            default=Value('PENDIENTE'), output_field=CharField(),
        ),
    )
    return qs


def valores_financieros(d):
    """
    Importes conciliados de un `Documento` anotado con `anotar_finanzas` (Decimal, 8 dec.).
    Única conversión que usan el detalle, CxC/CxP y el historial del tercero:
    total (original) + ND − NC = total_ajustado; total_ajustado − pagado = saldo_pendiente.
    """
    return {
        'total': q8(d.total or CERO), 'total_notas_credito': q8(d.total_notas_credito),
        'total_notas_debito': q8(d.total_notas_debito), 'total_ajustado': q8(d.total_ajustado),
        'pagado': q8(d.pagado), 'saldo_pendiente': q8(max(d.saldo_pendiente, CERO)),
        'monto_vencido': q8(max(d.monto_vencido, CERO)),
    }


def valores_financieros_texto(d):
    """`valores_financieros` como texto de 8 decimales (para la API)."""
    return {k: texto(v) for k, v in valores_financieros(d).items()}


def resumen_financiero(documento):
    """Totales financieros de un documento (el mismo cálculo que los listados)."""
    from apps.documentos.models import Documento
    if documento.tipo_comprobante.es_nota:
        return None
    d = anotar_finanzas(Documento.objects.filter(pk=documento.pk)).first()
    return {
        **valores_financieros(d),
        'estado_financiero': d.estado_financiero if documento.estado == 'CONFIRMADO' else None,
    }


def cuentas(*, empresa_id, clase, tercero_id=None, periodo_id=None, estado=None, condicion='CREDITO', fecha_corte=None):
    """Cuentas por cobrar (VENTA) o por pagar (COMPRA): comprobantes confirmados, sin notas."""
    from apps.documentos.models import Documento
    qs = Documento.objects.filter(empresa_id=empresa_id, clase=clase, estado='CONFIRMADO', tipo_comprobante__es_nota=False)
    if tercero_id:
        qs = qs.filter(tercero_id=tercero_id)
    if periodo_id:
        qs = qs.filter(periodo_id=periodo_id)
    if condicion in CONDICIONES_PAGO:
        qs = qs.filter(condicion_pago=condicion)
    qs = anotar_finanzas(qs.select_related('tercero', 'tipo_comprobante', 'moneda_codigo', 'periodo'), fecha_corte)
    if estado == 'ABIERTOS':
        qs = qs.exclude(estado_financiero='PAGADO')
    elif estado:
        qs = qs.filter(estado_financiero=estado)
    return qs.order_by('fecha_vencimiento', 'fecha_emision', 'id')


# ---- Pagos ---------------------------------------------------------------------------------

@transaction.atomic
def registrar_pago(*, empresa_id, usuario_id, documento_id, fecha, monto, metodo_pago, referencia='', moneda=None):
    from apps.catalogos.models import MetodoPago
    from apps.documentos.models import Documento, PagoDocumento
    # El documento queda bloqueado: dos pagos simultáneos no pueden superar el saldo.
    doc = (Documento.objects.select_for_update().select_related('tipo_comprobante')
           .filter(pk=documento_id, empresa_id=empresa_id).first())
    if doc is None:
        raise ValidationError({'documento': 'El documento no existe o no pertenece a la empresa activa.'})
    if doc.tipo_comprobante.es_nota:
        raise ValidationError({'documento': (
            'Las notas de crédito/débito no se pagan por separado: ajustan el saldo de su comprobante de origen.'
        )})
    if doc.estado == 'BORRADOR':
        raise ValidationError({'documento': 'El comprobante está en BORRADOR: confírmelo antes de registrar pagos.'})
    if doc.estado == 'ANULADO':
        raise ValidationError({'documento': 'El comprobante está ANULADO: no admite pagos.'})
    fecha = _fecha(fecha, 'fecha')
    if fecha is None:
        raise ValidationError({'fecha': 'La fecha del pago es obligatoria.'})
    if fecha < doc.fecha_emision:
        raise ValidationError({'fecha': 'El pago no puede ser anterior a la emisión del comprobante.'})
    if fecha > hoy():
        raise ValidationError({'fecha': 'El pago no puede tener fecha futura.'})
    monto = _decimal(monto, 'monto')
    if monto <= CERO:
        raise ValidationError({'monto': 'El monto debe ser mayor a 0.'})
    moneda = (moneda or doc.moneda_codigo_id or '').upper()
    if moneda != doc.moneda_codigo_id:
        raise ValidationError({'moneda_codigo': f'El pago debe registrarse en la moneda del comprobante ({doc.moneda_codigo_id}).'})
    metodo = MetodoPago.objects.filter(pk=(metodo_pago or '').strip().upper(), activo=True).first()
    if metodo is None:
        raise ValidationError({'metodo_pago': 'Método de pago no válido.'})
    saldo = resumen_financiero(doc)['saldo_pendiente']
    if monto > saldo:
        raise ValidationError({'monto': (
            f'El pago ({monto.normalize():f}) supera el saldo pendiente ({saldo.normalize():f} {doc.moneda_codigo_id}).'
        )})
    pago = PagoDocumento.objects.create(
        empresa_id=empresa_id, documento=doc, fecha=fecha, monto=monto, moneda_codigo_id=moneda,
        metodo_pago=metodo, referencia=(referencia or '').strip() or None, registrado_por_id=usuario_id,
    )
    registrar_auditoria(
        empresa_id=empresa_id, usuario_id=usuario_id, accion='REGISTRAR_PAGO', entidad='PAGO_DOCUMENTO',
        registro_id=pago.id,
        valor_nuevo={'documento_id': doc.id, 'comprobante': f'{doc.serie_normalizada}-{doc.numero_normalizado}',
                     'fecha': str(fecha), 'monto': str(monto), 'moneda': moneda, 'metodo': metodo.codigo,
                     'saldo_anterior': str(saldo), 'saldo_nuevo': texto(saldo - monto)},
        motivo='Cobro de venta' if doc.clase == 'VENTA' else 'Pago de compra',
    )
    return pago


@transaction.atomic
def anular_pago(*, empresa_id, usuario_id, pago_id, motivo):
    from apps.documentos.models import Documento, PagoDocumento
    motivo = (motivo or '').strip()
    if not motivo:
        raise ValidationError({'motivo': 'El motivo de la anulación es obligatorio.'})
    pago = PagoDocumento.objects.filter(pk=pago_id, empresa_id=empresa_id).first()
    if pago is None:
        raise ValidationError({'detail': 'El pago no existe o no pertenece a la empresa activa.'})
    Documento.objects.select_for_update().filter(pk=pago.documento_id).first()
    pago = PagoDocumento.objects.select_for_update().get(pk=pago.pk)
    if pago.estado == 'ANULADO':
        raise ValidationError({'detail': 'El pago ya está anulado.'})
    pago.estado = 'ANULADO'
    pago.motivo_anulacion = motivo
    pago.anulado_por_id = usuario_id
    pago.anulado_en = timezone.now()
    pago.save(update_fields=['estado', 'motivo_anulacion', 'anulado_por', 'anulado_en'])
    registrar_auditoria(
        empresa_id=empresa_id, usuario_id=usuario_id, accion='ANULAR_PAGO', entidad='PAGO_DOCUMENTO',
        registro_id=pago.id, valor_anterior={'estado': 'VIGENTE', 'monto': str(pago.monto)},
        valor_nuevo={'estado': 'ANULADO', 'documento_id': pago.documento_id}, motivo=motivo,
    )
    return pago


def validar_anulacion_sin_pagos(documento_id, empresa_id):
    """Un comprobante con pagos vigentes no se anula: primero se anulan los pagos."""
    from apps.documentos.models import PagoDocumento
    vigentes = PagoDocumento.objects.filter(documento_id=documento_id, empresa_id=empresa_id, estado='VIGENTE').count()
    if vigentes:
        raise ValidationError({'detail': (
            f'El comprobante tiene {vigentes} pago(s) vigente(s). Anule primero los pagos y luego el comprobante.'
        )})
