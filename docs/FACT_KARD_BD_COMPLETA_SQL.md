# FACT-KARD — BASE DE DATOS COMPLETA EN CÓDIGO

> Modelo lógico consolidado para PostgreSQL/Django.  
> Incluye PK, FK, UNIQUE, CHECK e índices principales.

---

## 1. Catálogos globales

```sql
CREATE TABLE moneda (
    codigo CHAR(3) PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL
);

CREATE TABLE tipo_cambio (
    id BIGSERIAL PRIMARY KEY,
    moneda_codigo CHAR(3) NOT NULL REFERENCES moneda(codigo),
    fecha_publicacion DATE NOT NULL,
    venta NUMERIC(20,8),
    compra NUMERIC(20,8),
    fuente VARCHAR(50) NOT NULL,
    UNIQUE (moneda_codigo, fecha_publicacion, fuente)
);

CREATE TABLE tipo_comprobante (
    id BIGSERIAL PRIMARY KEY,
    codigo_sunat VARCHAR(10) NOT NULL UNIQUE,
    descripcion VARCHAR(150) NOT NULL,
    es_nota BOOLEAN NOT NULL DEFAULT FALSE,
    efecto_nota VARCHAR(20) NOT NULL DEFAULT 'NINGUNO',
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (efecto_nota IN ('CREDITO','DEBITO','NINGUNO'))
);

CREATE TABLE tipo_operacion (
    id BIGSERIAL PRIMARY KEY,
    codigo_interno VARCHAR(50) NOT NULL UNIQUE,
    codigo_sunat VARCHAR(10),
    descripcion VARCHAR(150) NOT NULL,
    naturaleza VARCHAR(20) NOT NULL,
    es_interna BOOLEAN NOT NULL DEFAULT FALSE,
    afecta_kardex BOOLEAN NOT NULL DEFAULT TRUE,
    origen_requerido VARCHAR(30) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (naturaleza IN ('ENTRADA','SALIDA','AJUSTE_VALOR')),
    CHECK (origen_requerido IN (
        'DOCUMENTO','NOTA_INTERNA','TRANSFERENCIA',
        'SALDO_INICIAL','MOV_ORIGEN','MOV_EXTORNADO','MOTOR'
    ))
);

CREATE TABLE tipo_existencia (
    codigo VARCHAR(10) PRIMARY KEY,
    descripcion VARCHAR(150) NOT NULL
);

CREATE TABLE unidad_medida (
    codigo VARCHAR(10) PRIMARY KEY,
    descripcion VARCHAR(100) NOT NULL
);

-- Bloque 16: catálogo extensible de métodos de pago/cobro.
-- Carga inicial: EFECTIVO, TRANSFERENCIA, TARJETA, YAPE, PLIN, OTRO.
CREATE TABLE metodo_pago (
    codigo VARCHAR(20) PRIMARY KEY,
    descripcion VARCHAR(100) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE
);

-- Bloque 17A: motivos tributarios de las notas (Anexo 8, R.S. 097-2012/SUNAT y modificatorias).
-- catalogo '09' = tipo de nota de crédito; '10' = tipo de nota de débito. Catálogo controlado:
-- se desactiva, no se borra. Solo describe el motivo; el efecto contable lo deciden las líneas.
CREATE TABLE motivo_nota (
    id BIGSERIAL PRIMARY KEY,
    catalogo VARCHAR(2) NOT NULL,
    codigo VARCHAR(2) NOT NULL,
    descripcion VARCHAR(200) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (catalogo, codigo),
    CHECK (catalogo IN ('09','10'))
);
```

---

## 2. Seguridad y multiempresa

```sql
CREATE TABLE empresa (
    id BIGSERIAL PRIMARY KEY,
    ruc VARCHAR(11) NOT NULL UNIQUE,
    razon_social VARCHAR(200) NOT NULL,
    nombre_comercial VARCHAR(200),
    direccion VARCHAR(300),                -- domicilio fiscal del emisor
    -- Bloque 17A: ubicación del domicilio fiscal (emisor electrónico).
    ubigeo VARCHAR(6),
    departamento VARCHAR(100),
    provincia VARCHAR(100),
    distrito VARCHAR(100),
    codigo_pais VARCHAR(2) NOT NULL DEFAULT 'PE',
    moneda_base_codigo CHAR(3) NOT NULL REFERENCES moneda(codigo),
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVA',
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    logo VARCHAR(255),
    color_tema VARCHAR(7),
    CHECK (estado IN ('ACTIVA','INACTIVA')),
    CHECK (ubigeo IS NULL OR ubigeo ~ '^[0-9]{6}$'),
    CHECK (codigo_pais ~ '^[A-Z]{2}$'),
    CHECK (color_tema IS NULL OR color_tema ~ '^#[0-9A-Fa-f]{6}$')
);

CREATE TABLE usuario (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(150) NOT NULL UNIQUE,
    email VARCHAR(254) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    es_admin_global BOOLEAN NOT NULL DEFAULT FALSE,
    activo BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE usuario_empresa (
    id BIGSERIAL PRIMARY KEY,
    usuario_id BIGINT NOT NULL REFERENCES usuario(id),
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    rol VARCHAR(20) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (usuario_id, empresa_id),
    CHECK (rol IN ('ADMIN','USUARIO'))
);

-- Regularización (Bloque 6, ya existente en el modelo): tokens invalidados por logout.
CREATE TABLE token_revocado (
    id BIGSERIAL PRIMARY KEY,
    jti VARCHAR(64) NOT NULL UNIQUE,
    usuario_id BIGINT NOT NULL REFERENCES usuario(id),
    revocado_en TIMESTAMP NOT NULL,
    expira_en TIMESTAMP NOT NULL
);

CREATE INDEX ix_token_revocado_expira ON token_revocado (expira_en);
```

---

## 3. Maestros por empresa

```sql
CREATE TABLE establecimiento (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    codigo_sunat VARCHAR(20) NOT NULL,     -- código de establecimiento anexo SUNAT (0000 = domicilio fiscal)
    nombre VARCHAR(150) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    -- Bloque 17A: dirección del establecimiento. El principal es config_empresa.establecimiento_principal_id.
    direccion VARCHAR(300),
    ubigeo VARCHAR(6),
    UNIQUE (empresa_id, codigo_sunat),
    CHECK (ubigeo IS NULL OR ubigeo ~ '^[0-9]{6}$')
);

CREATE TABLE almacen (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    establecimiento_id BIGINT NOT NULL REFERENCES establecimiento(id),
    codigo VARCHAR(50) NOT NULL,
    nombre VARCHAR(150) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (empresa_id, codigo)
);

CREATE TABLE config_empresa (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL UNIQUE REFERENCES empresa(id),
    tolerancia_residuo_pen NUMERIC(20,8) NOT NULL DEFAULT 0.05,
    decimales_calculo SMALLINT NOT NULL DEFAULT 6,
    regla_redondeo VARCHAR(30) NOT NULL DEFAULT 'ROUND_HALF_UP',
    metodo_valuacion VARCHAR(20) NOT NULL DEFAULT 'CPP',
    tasa_igv_pct NUMERIC(5,2) NOT NULL DEFAULT 18.00,  -- regularización (Bloque 4)
    establecimiento_principal_id BIGINT REFERENCES establecimiento(id),
    CHECK (decimales_calculo BETWEEN 2 AND 8),
    CHECK (tasa_igv_pct > 0 AND tasa_igv_pct <= 100)
);

CREATE TABLE tercero (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    tipo_documento VARCHAR(20) NOT NULL,
    numero_documento VARCHAR(20) NOT NULL,
    razon_social VARCHAR(200) NOT NULL,
    nombre_comercial VARCHAR(200),
    direccion VARCHAR(300),
    telefono VARCHAR(50),
    correo VARCHAR(254),
    es_cliente BOOLEAN NOT NULL DEFAULT FALSE,
    es_proveedor BOOLEAN NOT NULL DEFAULT FALSE,
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (empresa_id, tipo_documento, numero_documento),
    -- Bloque 16: solo códigos del Catálogo 06 SUNAT (0, 1=DNI, 4=CE, 6=RUC, 7=Pasaporte, A).
    -- DNI = 8 dígitos; RUC = 11 dígitos con dígito verificador (validado en dominio).
    CHECK (tipo_documento IN ('0','1','4','6','7','A')),
    CHECK (es_cliente OR es_proveedor),
    CHECK (estado IN ('ACTIVO','INACTIVO'))
);

CREATE TABLE producto (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    codigo_interno VARCHAR(50) NOT NULL,
    descripcion VARCHAR(250) NOT NULL,
    tipo_existencia_codigo VARCHAR(10) NOT NULL REFERENCES tipo_existencia(codigo),
    estado VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    -- Bloque 16: datos comerciales (solo sugerencias; no intervienen en costo, CPP ni Kardex).
    precio_venta_sugerido NUMERIC(20,8),
    afectacion_igv_defecto VARCHAR(12),  -- GRAVADO / EXONERADO / INAFECTO / EXPORTACION / GRATUITO
    UNIQUE (empresa_id, codigo_interno),
    CHECK (estado IN ('ACTIVO','INACTIVO')),
    CHECK (precio_venta_sugerido IS NULL OR precio_venta_sugerido >= 0)
);

CREATE TABLE producto_unidad (
    id BIGSERIAL PRIMARY KEY,
    producto_id BIGINT NOT NULL REFERENCES producto(id),
    unidad_codigo VARCHAR(10) NOT NULL REFERENCES unidad_medida(codigo),
    factor_a_base NUMERIC(20,8) NOT NULL,
    es_base BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (producto_id, unidad_codigo),
    CHECK (factor_a_base > 0)
);

CREATE UNIQUE INDEX uq_producto_unidad_base
ON producto_unidad(producto_id)
WHERE es_base = TRUE;

CREATE TABLE producto_equivalencia (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    tercero_id BIGINT NOT NULL REFERENCES tercero(id),
    codigo_externo VARCHAR(100),
    descripcion_externa VARCHAR(300),
    unidad_externa_codigo VARCHAR(10) REFERENCES unidad_medida(codigo),
    producto_unidad_id BIGINT NOT NULL REFERENCES producto_unidad(id),
    factor_conversion NUMERIC(20,8) NOT NULL,
    confirmado_por BIGINT REFERENCES usuario(id),
    confirmado_en TIMESTAMP,
    activa BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (factor_conversion > 0)
);
```

---

## 4. Períodos y fiscal

```sql
CREATE TABLE periodo (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    anio SMALLINT NOT NULL,
    mes SMALLINT NOT NULL,
    orden INTEGER NOT NULL,
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'ABIERTO',
    motivo_desactualizado VARCHAR(500),
    cerrado_por BIGINT REFERENCES usuario(id),
    cerrado_en TIMESTAMP,
    reabierto_por BIGINT REFERENCES usuario(id),
    reabierto_en TIMESTAMP,
    motivo_reapertura VARCHAR(500),
    UNIQUE (empresa_id, anio, mes),
    CHECK (mes BETWEEN 1 AND 12),
    CHECK (estado IN ('ABIERTO','CERRADO','DESACTUALIZADO')),
    CHECK (fecha_fin >= fecha_inicio)
);

CREATE TABLE config_igv_periodo (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    periodo_id BIGINT NOT NULL REFERENCES periodo(id),
    metodo VARCHAR(20) NOT NULL,
    porcentaje_recuperable NUMERIC(7,4) NOT NULL,
    creado_por BIGINT REFERENCES usuario(id),
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (empresa_id, periodo_id),
    CHECK (metodo IN ('TOTAL','NULO','PRORRATA')),
    CHECK (porcentaje_recuperable BETWEEN 0 AND 100)
);

-- Regularización (Bloque 5, ya existente en el modelo): tasa del IGV vigente desde una fecha.
CREATE TABLE tasa_igv_vigencia (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    vigente_desde DATE NOT NULL,
    tasa_pct NUMERIC(5,2) NOT NULL,
    creado_en TIMESTAMP NOT NULL,
    UNIQUE (empresa_id, vigente_desde),
    CHECK (tasa_pct > 0 AND tasa_pct <= 100)
);
```

---

## 5. Documentos comerciales

```sql
-- Bloque 16: series de VENTA con correlativo automático (ver reglas en 5.1).
CREATE TABLE serie_comprobante (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    establecimiento_id BIGINT NOT NULL REFERENCES establecimiento(id),
    tipo_comprobante_id BIGINT NOT NULL REFERENCES tipo_comprobante(id),
    serie VARCHAR(4) NOT NULL,
    ultimo_correlativo BIGINT NOT NULL DEFAULT 0,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (empresa_id, tipo_comprobante_id, serie),
    CHECK (ultimo_correlativo BETWEEN 0 AND 99999999),
    CHECK (serie ~ '^[A-Z0-9]{4}$')
);

CREATE TABLE documento (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    clase VARCHAR(20) NOT NULL,
    periodo_id BIGINT NOT NULL REFERENCES periodo(id),
    tercero_id BIGINT REFERENCES tercero(id),
    ruc_emisor VARCHAR(11) NOT NULL,
    tipo_comprobante_id BIGINT NOT NULL REFERENCES tipo_comprobante(id),

    serie VARCHAR(30),
    serie_normalizada VARCHAR(30) NOT NULL,
    numero VARCHAR(50),
    numero_normalizado VARCHAR(50) NOT NULL,

    fecha_emision DATE NOT NULL,

    moneda_codigo CHAR(3) NOT NULL REFERENCES moneda(codigo),
    tipo_cambio_id BIGINT REFERENCES tipo_cambio(id),
    fecha_tc DATE,
    monto_tc NUMERIC(20,8),
    fuente_tc VARCHAR(50),

    subtotal NUMERIC(20,8),
    igv NUMERIC(20,8),
    total NUMERIC(20,8),

    documento_origen_id BIGINT REFERENCES documento(id),

    -- Bloque 16: condición de pago y serie con correlativo automático (solo ventas).
    condicion_pago VARCHAR(10) NOT NULL DEFAULT 'CONTADO',
    fecha_vencimiento DATE,
    serie_comprobante_id BIGINT REFERENCES serie_comprobante(id),

    -- Bloque 17A: motivo tributario de la nota (catálogo 09 para NC, 10 para ND). Solo en notas.
    motivo_nota_id BIGINT REFERENCES motivo_nota(id),

    origen_captura VARCHAR(20) NOT NULL DEFAULT 'MANUAL',
    estado VARCHAR(20) NOT NULL DEFAULT 'BORRADOR',
    estado_revision VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE',

    revisado_por BIGINT REFERENCES usuario(id),
    revisado_en TIMESTAMP,
    creado_por BIGINT REFERENCES usuario(id),
    confirmado_por BIGINT REFERENCES usuario(id),
    confirmado_en TIMESTAMP,

    UNIQUE (
        empresa_id,
        ruc_emisor,
        tipo_comprobante_id,
        serie_normalizada,
        numero_normalizado
    ),

    CHECK (clase IN ('COMPRA','VENTA')),
    CHECK (origen_captura IN ('MANUAL','XML','PDF','IMAGEN','ESCANER')),
    CHECK (estado IN ('BORRADOR','CONFIRMADO','ANULADO')),
    CHECK (estado_revision IN ('PENDIENTE','EN_REVISION','REVISADO','OBSERVADO')),
    CHECK (
        (condicion_pago = 'CONTADO' AND fecha_vencimiento IS NULL)
        OR (condicion_pago = 'CREDITO' AND fecha_vencimiento IS NOT NULL)
    )
);

CREATE TABLE documento_detalle (
    id BIGSERIAL PRIMARY KEY,
    documento_id BIGINT NOT NULL REFERENCES documento(id),
    linea INTEGER NOT NULL,

    producto_id BIGINT REFERENCES producto(id),
    producto_unidad_id BIGINT REFERENCES producto_unidad(id),
    almacen_id BIGINT NOT NULL REFERENCES almacen(id),

    tipo_operacion_id BIGINT NOT NULL REFERENCES tipo_operacion(id),
    afecta_kardex_aplicado BOOLEAN NOT NULL DEFAULT TRUE,
    equivalencia_id BIGINT REFERENCES producto_equivalencia(id),

    descripcion_original VARCHAR(500),
    cantidad_original NUMERIC(20,8),
    factor_conversion NUMERIC(20,8),
    cantidad_base NUMERIC(20,8),

    precio_unitario NUMERIC(20,8),
    igv NUMERIC(20,8),
    porcentaje_credito_fiscal_aplicado NUMERIC(7,4),
    costo_unitario_pen NUMERIC(20,8),

    es_bonificacion BOOLEAN NOT NULL DEFAULT FALSE,
    -- Regularización (Bloque 3): afectación del IGV y código del Catálogo 07.
    afectacion_igv VARCHAR(12),       -- GRAVADO / EXONERADO / INAFECTO / EXPORTACION / GRATUITO
    codigo_afectacion_igv VARCHAR(2),
    detalle_origen_id BIGINT REFERENCES documento_detalle(id),

    UNIQUE (documento_id, linea),
    CHECK (cantidad_original IS NULL OR cantidad_original >= 0),
    CHECK (factor_conversion IS NULL OR factor_conversion > 0),
    CHECK (
        porcentaje_credito_fiscal_aplicado IS NULL
        OR porcentaje_credito_fiscal_aplicado BETWEEN 0 AND 100
    )
);
```

---

## 5.1 Series, condición de pago y pagos (Bloque 16)

Reglas:

- El correlativo de VENTA lo asigna solo el backend: `serie_comprobante` se bloquea con
  `SELECT ... FOR UPDATE` en la transacción que crea el comprobante y `ultimo_correlativo`
  aumenta en 1 (número con 8 dígitos). Las compras conservan la serie y número recibidos.
- `suma(documento_cuota.monto) = documento.total` (8 decimales, ROUND_HALF_UP).
- Pagos solo sobre documentos CONFIRMADOS que no son notas, en la moneda del documento y sin
  superar el saldo. No se borran: se anulan (estado ANULADO + motivo).
- Saldo pendiente = total + notas de débito − notas de crédito (confirmadas) − pagos VIGENTES.
  Es un cálculo: no existe tabla de saldos ni de cuentas por cobrar/pagar.

```sql
-- serie_comprobante: definida al inicio de la sección 5 (documento la referencia).

CREATE TABLE documento_cuota (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    documento_id BIGINT NOT NULL REFERENCES documento(id),
    numero SMALLINT NOT NULL,
    fecha_vencimiento DATE NOT NULL,
    monto NUMERIC(20,8) NOT NULL,
    UNIQUE (documento_id, numero),
    CHECK (numero >= 1),
    CHECK (monto > 0)
);

CREATE TABLE pago_documento (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    documento_id BIGINT NOT NULL REFERENCES documento(id),
    fecha DATE NOT NULL,
    monto NUMERIC(20,8) NOT NULL,
    moneda_codigo CHAR(3) NOT NULL REFERENCES moneda(codigo),
    metodo_pago_codigo VARCHAR(20) NOT NULL REFERENCES metodo_pago(codigo),
    referencia VARCHAR(100),
    estado VARCHAR(10) NOT NULL DEFAULT 'VIGENTE',
    motivo_anulacion TEXT,
    registrado_por BIGINT REFERENCES usuario(id),
    registrado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    anulado_por BIGINT REFERENCES usuario(id),
    anulado_en TIMESTAMP,
    CHECK (monto > 0),
    CHECK (estado IN ('VIGENTE','ANULADO'))
);

CREATE INDEX ix_pago_documento_emp_doc ON pago_documento (empresa_id, documento_id);
```

---

## 6. Captura XML / PDF / OCR

```sql
CREATE TABLE documento_captura (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    documento_id BIGINT REFERENCES documento(id),
    tipo VARCHAR(20) NOT NULL,
    ruta_archivo VARCHAR(500) NOT NULL,
    hash_sha256 VARCHAR(64),
    estado_proceso VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE',
    subido_por BIGINT REFERENCES usuario(id),
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (tipo IN ('XML','PDF','IMAGEN','ESCANER'))
);

CREATE TABLE captura_campo (
    id BIGSERIAL PRIMARY KEY,
    documento_captura_id BIGINT NOT NULL REFERENCES documento_captura(id),
    seccion VARCHAR(20) NOT NULL,
    numero_linea INTEGER,
    nombre_campo VARCHAR(100) NOT NULL,
    valor_extraido TEXT,
    confianza NUMERIC(7,4),
    valor_corregido TEXT,
    corregido_por BIGINT REFERENCES usuario(id),
    CHECK (seccion IN ('CABECERA','DETALLE')),
    CHECK (confianza IS NULL OR confianza BETWEEN 0 AND 100)
);
```

---

## 7. Notas internas

```sql
CREATE TABLE nota_interna (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    almacen_id BIGINT NOT NULL REFERENCES almacen(id),
    periodo_id BIGINT NOT NULL REFERENCES periodo(id),
    tipo_operacion_id BIGINT NOT NULL REFERENCES tipo_operacion(id),
    fecha DATE NOT NULL,
    motivo VARCHAR(500) NOT NULL,
    responsable VARCHAR(200),
    observacion TEXT,
    archivo_sustento VARCHAR(500),
    estado VARCHAR(20) NOT NULL DEFAULT 'BORRADOR',
    creado_por BIGINT REFERENCES usuario(id),
    CHECK (estado IN ('BORRADOR','CONFIRMADO','ANULADO'))
);

CREATE TABLE nota_interna_detalle (
    id BIGSERIAL PRIMARY KEY,
    nota_interna_id BIGINT NOT NULL REFERENCES nota_interna(id),
    producto_id BIGINT NOT NULL REFERENCES producto(id),
    cantidad_base NUMERIC(20,8) NOT NULL DEFAULT 0,
    costo_unitario_pen NUMERIC(20,8),
    valor_ajuste_pen NUMERIC(20,8),
    CHECK (cantidad_base >= 0)
);
```

---

## 8. Transferencias

```sql
CREATE TABLE transferencia (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    almacen_origen_id BIGINT NOT NULL REFERENCES almacen(id),
    almacen_destino_id BIGINT NOT NULL REFERENCES almacen(id),
    fecha DATE NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'BORRADOR',
    creado_por BIGINT REFERENCES usuario(id),

    CHECK (almacen_origen_id <> almacen_destino_id),
    CHECK (estado IN ('BORRADOR','CONFIRMADO','ANULADO'))
);

CREATE TABLE transferencia_detalle (
    id BIGSERIAL PRIMARY KEY,
    transferencia_id BIGINT NOT NULL REFERENCES transferencia(id),
    producto_id BIGINT NOT NULL REFERENCES producto(id),
    cantidad_base NUMERIC(20,8) NOT NULL,
    CHECK (cantidad_base > 0)
);
```

---

## 9. Saldo inicial

```sql
CREATE TABLE saldo_inicial (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    periodo_id BIGINT NOT NULL REFERENCES periodo(id),
    almacen_id BIGINT NOT NULL REFERENCES almacen(id),
    producto_id BIGINT NOT NULL REFERENCES producto(id),

    cantidad NUMERIC(20,8) NOT NULL,
    valor_pen NUMERIC(20,8) NOT NULL,
    cpp_inicial NUMERIC(20,8),

    estado VARCHAR(20) NOT NULL DEFAULT 'BORRADOR',
    creado_por BIGINT REFERENCES usuario(id),

    UNIQUE (empresa_id, periodo_id, almacen_id, producto_id),
    CHECK (estado IN ('BORRADOR','CONFIRMADO')),
    CHECK (cantidad >= 0)
);
```

---

## 10. Motor de movimientos

```sql
CREATE TABLE movimiento (
    id BIGSERIAL PRIMARY KEY,

    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    producto_id BIGINT NOT NULL REFERENCES producto(id),
    almacen_id BIGINT NOT NULL REFERENCES almacen(id),
    periodo_id BIGINT NOT NULL REFERENCES periodo(id),

    documento_detalle_id BIGINT REFERENCES documento_detalle(id),
    nota_interna_detalle_id BIGINT REFERENCES nota_interna_detalle(id),
    transferencia_detalle_id BIGINT REFERENCES transferencia_detalle(id),
    transferencia_id BIGINT REFERENCES transferencia(id),
    saldo_inicial_id BIGINT REFERENCES saldo_inicial(id),

    movimiento_origen_id BIGINT REFERENCES movimiento(id),
    movimiento_extornado_id BIGINT REFERENCES movimiento(id),

    tipo_operacion_id BIGINT NOT NULL REFERENCES tipo_operacion(id),

    fecha_movimiento DATE NOT NULL,
    prioridad_dia SMALLINT NOT NULL,
    secuencia INTEGER NOT NULL DEFAULT 0,

    naturaleza VARCHAR(20) NOT NULL,

    cantidad_base NUMERIC(20,8) NOT NULL DEFAULT 0,
    valor_ajuste_pen NUMERIC(20,8),

    es_extorno BOOLEAN NOT NULL DEFAULT FALSE,
    generado_por_motor BOOLEAN NOT NULL DEFAULT FALSE,

    creado_por BIGINT REFERENCES usuario(id),
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (naturaleza IN ('ENTRADA','SALIDA','AJUSTE_VALOR')),
    CHECK (prioridad_dia BETWEEN 1 AND 4),
    CHECK (cantidad_base >= 0)
);

CREATE INDEX ix_movimiento_orden
ON movimiento (
    empresa_id,
    producto_id,
    fecha_movimiento,
    prioridad_dia,
    secuencia,
    id
);

CREATE INDEX ix_movimiento_almacen
ON movimiento (empresa_id, almacen_id, producto_id);

CREATE INDEX ix_movimiento_periodo
ON movimiento (periodo_id);
```

---

## 11. Recálculo y valorización

```sql
CREATE TABLE recalculo (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    producto_id BIGINT NOT NULL REFERENCES producto(id),
    fecha_desde DATE NOT NULL,
    fecha_hasta DATE,
    motivo VARCHAR(500),
    version INTEGER NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'EN_PROCESO',
    ejecutado_por BIGINT REFERENCES usuario(id),
    ejecutado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (estado IN ('EN_PROCESO','OK','ERROR'))
);

CREATE TABLE valorizacion_movimiento (
    id BIGSERIAL PRIMARY KEY,
    movimiento_id BIGINT NOT NULL UNIQUE REFERENCES movimiento(id),

    costo_unitario_pen NUMERIC(20,8),
    valor_movimiento_pen NUMERIC(20,8),
    saldo_cantidad_empresa NUMERIC(20,8),
    saldo_valor_empresa NUMERIC(20,8),
    cpp_empresa NUMERIC(20,8),

    version_actual INTEGER NOT NULL DEFAULT 1,
    recalculo_id BIGINT REFERENCES recalculo(id),
    calculado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE recalculo_detalle (
    id BIGSERIAL PRIMARY KEY,
    recalculo_id BIGINT NOT NULL REFERENCES recalculo(id),
    movimiento_id BIGINT NOT NULL REFERENCES movimiento(id),

    cpp_anterior NUMERIC(20,8),
    cpp_nuevo NUMERIC(20,8),

    valor_anterior NUMERIC(20,8),
    valor_nuevo NUMERIC(20,8),

    saldo_anterior NUMERIC(20,8),
    saldo_nuevo NUMERIC(20,8)
);
```

---

## 12. Cachés

```sql
CREATE TABLE stock_almacen (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    almacen_id BIGINT NOT NULL REFERENCES almacen(id),
    producto_id BIGINT NOT NULL REFERENCES producto(id),
    cantidad_actual NUMERIC(20,8) NOT NULL DEFAULT 0,
    actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (empresa_id, almacen_id, producto_id)
);

CREATE TABLE saldo_cpp_actual (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    producto_id BIGINT NOT NULL REFERENCES producto(id),

    cantidad_total NUMERIC(20,8) NOT NULL DEFAULT 0,
    valor_total_pen NUMERIC(20,8) NOT NULL DEFAULT 0,
    cpp_pen NUMERIC(20,8),

    ultimo_movimiento_id BIGINT REFERENCES movimiento(id),
    actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (empresa_id, producto_id)
);
```

---

## 13. Incidencias

```sql
CREATE TABLE incidencia (
    id BIGSERIAL PRIMARY KEY,

    empresa_id BIGINT NOT NULL REFERENCES empresa(id),
    periodo_id BIGINT REFERENCES periodo(id),

    documento_id BIGINT REFERENCES documento(id),
    documento_detalle_id BIGINT REFERENCES documento_detalle(id),
    movimiento_id BIGINT REFERENCES movimiento(id),
    producto_id BIGINT REFERENCES producto(id),

    tipo VARCHAR(80) NOT NULL,
    severidad VARCHAR(20) NOT NULL DEFAULT 'ERROR',
    bloquea_cierre BOOLEAN NOT NULL DEFAULT TRUE,
    estado VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE',

    descripcion TEXT NOT NULL,
    detalle JSONB,

    detectado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resuelto_por BIGINT REFERENCES usuario(id),
    resuelto_en TIMESTAMP,

    CHECK (estado IN ('PENDIENTE','RESUELTA','DESCARTADA')),
    CHECK (severidad IN ('INFO','ADVERTENCIA','ERROR','CRITICA'))
);
```

---

## 14. Cierre de período

```sql
CREATE TABLE cierre_periodo (
    id BIGSERIAL PRIMARY KEY,
    periodo_id BIGINT NOT NULL REFERENCES periodo(id),
    version_calculo INTEGER NOT NULL,
    cerrado_por BIGINT NOT NULL REFERENCES usuario(id),
    cerrado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archivo_excel VARCHAR(500),
    hash_resultado VARCHAR(128),
    snapshot_resumen JSONB,
    vigente BOOLEAN NOT NULL DEFAULT TRUE,

    UNIQUE (periodo_id, version_calculo)
);

CREATE TABLE cierre_periodo_detalle (
    id BIGSERIAL PRIMARY KEY,
    cierre_periodo_id BIGINT NOT NULL REFERENCES cierre_periodo(id),
    producto_id BIGINT NOT NULL REFERENCES producto(id),
    establecimiento_id BIGINT NOT NULL REFERENCES establecimiento(id),
    saldo_cantidad NUMERIC(20,8),
    saldo_valor_pen NUMERIC(20,8),
    cpp_pen NUMERIC(20,8)
);
```

---

## 15. Auditoría

```sql
CREATE TABLE auditoria (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT REFERENCES empresa(id),
    usuario_id BIGINT REFERENCES usuario(id),
    accion VARCHAR(80) NOT NULL,
    entidad VARCHAR(100) NOT NULL,
    registro_id BIGINT,
    valor_anterior JSONB,
    valor_nuevo JSONB,
    motivo TEXT,
    fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 16. Índices recomendados

```sql
CREATE INDEX ix_documento_empresa_fecha
ON documento (empresa_id, fecha_emision);

CREATE INDEX ix_documento_periodo
ON documento (periodo_id);

CREATE INDEX ix_documento_tercero
ON documento (tercero_id);

CREATE INDEX ix_documento_origen
ON documento (documento_origen_id);

CREATE INDEX ix_documento_detalle_producto
ON documento_detalle (producto_id);

CREATE INDEX ix_documento_detalle_almacen
ON documento_detalle (almacen_id);

CREATE INDEX ix_documento_detalle_origen
ON documento_detalle (detalle_origen_id);

CREATE INDEX ix_incidencia_empresa_estado
ON incidencia (empresa_id, estado);

CREATE INDEX ix_incidencia_periodo_bloqueo
ON incidencia (periodo_id, bloquea_cierre, estado);

CREATE INDEX ix_recalculo_empresa_producto
ON recalculo (empresa_id, producto_id, fecha_desde);
```

---

## 17. Trigger de inmutabilidad de MOVIMIENTO

```sql
CREATE OR REPLACE FUNCTION bloquear_modificacion_movimiento()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'MOVIMIENTO es inmutable. Use extorno y un nuevo movimiento.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_movimiento_no_update
BEFORE UPDATE ON movimiento
FOR EACH ROW
EXECUTE FUNCTION bloquear_modificacion_movimiento();

CREATE TRIGGER trg_movimiento_no_delete
BEFORE DELETE ON movimiento
FOR EACH ROW
EXECUTE FUNCTION bloquear_modificacion_movimiento();
```

---

## 18. Trigger de inmutabilidad de AUDITORIA

```sql
CREATE OR REPLACE FUNCTION bloquear_modificacion_auditoria()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'AUDITORIA es de solo insercion.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_auditoria_no_update
BEFORE UPDATE ON auditoria
FOR EACH ROW
EXECUTE FUNCTION bloquear_modificacion_auditoria();

CREATE TRIGGER trg_auditoria_no_delete
BEFORE DELETE ON auditoria
FOR EACH ROW
EXECUTE FUNCTION bloquear_modificacion_auditoria();
```

---

## 19. Reglas que deben validarse en Django / capa de dominio

```text
- ALMACEN debe pertenecer a la misma EMPRESA.
- ESTABLECIMIENTO debe pertenecer a la misma EMPRESA.
- PERIODO debe pertenecer a la misma EMPRESA.
- TERCERO debe pertenecer a la misma EMPRESA.
- PRODUCTO debe pertenecer a la misma EMPRESA.
- DOCUMENTO_DETALLE debe usar almacén/producto de la misma empresa.
- TIPO_CAMBIO debe corresponder a la moneda del documento.
- No confirmar documentos en período cerrado.
- No permitir stock negativo.
- No confirmar documento pendiente de revisión.
- No duplicar comprobantes.
- NC/ND debe tener documento origen cuando corresponda.
- detalle_origen_id debe pertenecer al documento origen.
- Transferencia origen y destino deben pertenecer a la misma empresa.
- Ajuste automático puede extornarse/regenerarse.
- Ajuste manual no se modifica automáticamente.
- Bloque 17A: documento.motivo_nota_id solo en notas: catálogo 09 si es NC (07), 10 si es ND (08).
- Bloque 17A: "LISTO_PARA_EMISION" / "NO_PREPARADO" es un estado DERIVADO (no se guarda): lo calcula
  documentos/reglas_tributarias.py (emisor, establecimiento, serie, cliente, motivo, líneas y totales).
  Aún no hay XML, firma, envío ni CDR.
```

---

## 20. Orden del motor

```text
fecha_movimiento
→ prioridad_dia
→ secuencia
→ id
```

Prioridades:

```text
1 = SALDO_INICIAL
2 = ENTRADAS
3 = AJUSTES_VALOR
4 = SALIDAS
```

---

## 21. Fuentes de verdad

```text
HECHOS:
MOVIMIENTO

VALORIZACION VIGENTE:
VALORIZACION_MOVIMIENTO

HISTORIAL:
RECALCULO
RECALCULO_DETALLE

STOCK CACHE:
STOCK_ALMACEN

CPP CACHE:
SALDO_CPP_ACTUAL

SNAPSHOT DE CIERRE:
CIERRE_PERIODO
CIERRE_PERIODO_DETALLE
```

---

## 22. Reglas contables validadas (Fase 0 cerrada)

```text
1. Formato 13.1 por establecimiento:
   - Se mantiene un único CPP global por empresa + producto.
   - Cada establecimiento usa ese CPP global para valorizar sus cantidades físicas.
   - Si existe microdiferencia por redondeo, se asigna a config_empresa.establecimiento_principal_id y se registra en auditoria.

2. NC/ND cuando el documento origen está en un período CERRADO:
   - El ajuste se reparte según la proporción del stock de esa compra que todavía permanece en inventario.
   - Solo la proporción correspondiente al stock restante entra al Kardex (MOVIMIENTO tipo AJUSTE_VALOR) modificando el valor del inventario y el CPP.
   - La proporción correspondiente a mercadería ya vendida queda fuera del Kardex (se informa para tratamiento contable directo al costo de ventas/gasto).

3. NC/ND en moneda extranjera (USD):
   - Se aplica obligatoriamente el Tipo de Cambio (monto_tc, fecha_tc, fuente_tc) del documento original (documento_origen_id), nunca el TC de la fecha de emisión de la nota.
```

Estas reglas contables confirmadas quedan plenamente soportadas por el esquema DDL y la arquitectura de datos definida.
