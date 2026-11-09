# Fact-Kard Core

Sistema ERP de Gestion Comercial, Control de Inventarios y Motor de Kardex Valorizado Multiempresa (Costo Promedio Ponderado - Formato 13.1 SUNAT).

Fact-Kard Core es una plataforma integral de codigo abierto orientada a resolver las necesidades de trazabilidad de existencias, gestion de comprobantes comerciales y cumplimiento tributario-contable bajo normativa peruana (Resolucion de Superintendencia N° 234-2006/SUNAT y normas conexas).

---

## Principios de Diseno y Arquitectura

1. **Aislamiento Multiempresa Estricto:** Toda entidad operativa, consulta (`QuerySet`), vista y serializer filtra obligatoriamente por `empresa_id`, garantizando segregacion total de datos entre empresas y sus anexos o establecimientos.
2. **Precision Decimal Operativa (Cero Float):** Prohibido el uso de tipos de coma flotante (`float`) en calculos financieros, de inventario o factores de conversion. Toda la logica matematica utiliza `Decimal` con redondeo `ROUND_HALF_UP` (6 decimales operativos y 8 en base de datos).
3. **Inmutabilidad Contable y Auditoria:** Las tablas `movimiento` (Kardex) y `auditoria` son de solo insercion (`INSERT`). Prohibidas las operaciones de actualizacion (`UPDATE`) o eliminacion (`DELETE`) directa sobre registros historicos.
4. **Control Estricto de Concurrencia:** Toda operacion que altera inventario o saldos valorizados se ejecuta dentro de transacciones atomicas (`transaction.atomic()`) aplicando bloqueos pesimistas de fila (`select_for_update()`) sobre el registro de saldo actual (`saldo_cpp_actual`).
5. **Fidelidad al Esquema SQL Fisico:** Compatibilidad e integridad total con el esquema relacional en PostgreSQL 16+, con restricciones de clave unica, verificacion (`CHECK`) e indices de cobertura para alta transaccionalidad.

---

## Modulos del Sistema

### Gestion Multiempresa y Fiscal (`apps.empresas`)
- Administracion de empresas matrices, anexos y establecimientos (codigo de domicilio fiscal SUNAT, ubigeo INEI, direccion).
- Apertura, control y cierre formal de periodos contables mensuales.
- Historico y configuracion de alicuotas de IGV (18%, 10%, etc.) aplicables a cada periodo.
- Cierres de periodo con congelamiento de saldos finales de inventario y saldos comerciales.

### Catalogos Oficiales y Maestros (`apps.catalogos`, `apps.inventario`)
- **Tabla 5 SUNAT:** Tipos de existencia (Mercaderias, Materias Primas, Productos Terminados, Envases, etc.).
- **Tabla 6 SUNAT:** Unidades de medida oficiales (NIU, KGM, LTR, etc.) con soporte para unidades base y compuestas mediante factores de conversion exactos.
- **Tabla 10 SUNAT:** Tipos de comprobante de pago (Factura, Boleta de Venta, Nota de Credito, Nota de Debito, Guia de Remision).
- **Tabla 12 SUNAT:** Tipos de operacion tributaria (Venta, Compra, Saldo Inicial, Devolucion, Consignacion, Muestras, Transferencias).
- **Tipo de Cambio SBS:** Registro y consulta diaria de cotizaciones oficiales de compra y venta interbancaria (PEN, USD, EUR).
- **Terceros:** Clientes y proveedores con validacion algoritmica estricta de digito verificador para RUC (modulo 11) y formato DNI.

### Comprobantes Comerciales (`apps.documentos`)
- Ciclo de vida completo para comprobantes de compra y venta: Borrador -> En Revision -> Confirmado -> Anulado.
- Desglose y clasificacion tributaria de lineas segun afectacion de IGV (Gravado oneroso, Exonerado, Inafecto, Gratuito con catalogo 07).
- Notas de Credito y Notas de Debito con vinculacion al comprobante de origen, aplicacion del catalogo oficial de motivos (catalogo 09 y 10 SUNAT) y ajuste financiero y fisico.
- Generacion automatica de correlativos por serie autorizada (F001, B001, etc.).

### Finanzas y Cuentas por Cobrar / Pagar (`apps.documentos`)
- Modulo financiero de cuentas comerciales por cobrar (ventas) y cuentas por pagar (compras).
- Control de saldos remanentes, fechas de vencimiento y amortizaciones parciales o totales.
- Trazabilidad de pagos y cancelaciones con auditoria de usuario y fecha.

### Motor de Kardex Valorizado CPP (`apps.kardex`, `apps.reportes`)
- Metodo de valuacion: Costo Promedio Ponderado continuo.
- Entradas: Adquisicion valorizada que actualiza el costo unitario promedio ponderado.
- Salidas: Consumos y ventas valorizadas estrictamente al costo promedio ponderado vigente al momento de la operacion.
- Deteccion preventiva y bloqueo de stock negativo en cualquier almacen.
- Mecanismo de recalculo cronologico en cadena: ante la confirmacion de extornos, anulaciones o movimientos retroactivos, el motor recalcula de forma determinista todos los saldos y costos posteriores dentro de una misma transaccion.
- Reporte oficial del Formato 13.1 SUNAT: "Registro de Inventario Permanente Valorizado - Detalle del Inventario Valorizado".

### Seguridad y Auditoria (`apps.usuarios`, `apps.auditoria`)
- Autenticacion robusta mediante tokens criptograficos con identificador unico (`jti`) revocables en servidor.
- Control de acceso basado en roles por empresa (Administrador Global, Administrador de Empresa, Operador, Consultor).
- Registro exhaustivo e inmutable de eventos de auditoria: direccion IP, usuario, accion, entidad, valor anterior y valor nuevo en formato JSONB.

---

## Arquitectura del Flujo Operativo

```
[ Comprobante Comercial ]
           |
           v
[ Validacion de Reglas de Negocio e IGV ]
           |
           v
[ Transaccion Atomica (transaction.atomic) ]
           |
           +--> Bloqueo pesimista de fila: select_for_update() sobre SaldoCPP
           |
           +--> Determinacion de Costo Promedio Ponderado (CPP)
           |
           +--> Insercion inmutable en tabla 'movimiento'
           |
           +--> Actualizacion de 'saldo_cpp_actual'
           |
           +--> Insercion inmutable en tabla 'auditoria'
           |
           v
[ Kardex Valorizado Formato 13.1 SUNAT ]
```

---

## Estructura del Proyecto

```
fact-kard-core/
├── backend/
│   ├── apps/
│   │   ├── auditoria/          # Registro inmutable de eventos
│   │   ├── catalogos/          # Catalogos oficiales SUNAT y tipo de cambio SBS
│   │   ├── consulta_ruc/       # Consulta y validacion de padron RUC
│   │   ├── documentos/         # Comprobantes, finanzas y cuentas por cobrar/pagar
│   │   ├── empresas/           # Multiempresa, establecimientos y periodos
│   │   ├── inventario/         # Productos, almacenes y terceros
│   │   ├── kardex/             # Motor de valuacion CPP y movimientos
│   │   ├── reportes/           # Generador de Formato 13.1 SUNAT
│   │   └── usuarios/           # Autenticacion, permisos y asignaciones
│   ├── config/                 # Configuracion Django, URLs, seguridad y logging
│   ├── manage.py
│   └── requirements.txt
├── docs/
│   ├── FACT_KARD_BD_COMPLETA_SQL.md    # Esquema fisico oficial PostgreSQL
│   ├── INDICES_BLOQUE7.md              # Indices de rendimiento y cobertura
│   └── PRECISION_DECIMAL_BLOQUE9.md    # Reglas de precision y redondeo
├── frontend/
│   ├── src/
│   │   ├── api/                # Clientes Axios tipados
│   │   ├── components/         # Componentes UI reutilizables
│   │   ├── context/            # Estado global de autenticacion y empresa
│   │   ├── layouts/            # Diseno principal y barra lateral
│   │   ├── pages/              # Vistas principales del sistema
│   │   └── utils/              # Logica pura y validaciones
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
└── README.md
```

---

## Requisitos de Infraestructura

- **Lenguaje Backend:** Python 3.12 o superior.
- **Base de Datos:** PostgreSQL 16 o superior.
- **Entorno Frontend:** Node.js 22 LTS o superior (npm 10+).
- **Sistema Operativo:** Compatible con distribuciones Linux (Ubuntu 22.04 / 24.04 LTS, Debian 12), Windows Server y macOS.

---

## Guia de Instalacion y Despliegue Local

### 1. Clonar el repositorio

```bash
git clone https://github.com/Isaac-9026/fact-kard-core.git
cd fact-kard-core
```

### 2. Configuracion del Backend

1. Crear y activar el entorno virtual de Python:
   ```bash
   cd backend
   python -m venv .venv

   # En Linux / macOS:
   source .venv/bin/activate

   # En Windows:
   .venv\Scripts\activate
   ```

2. Instalar dependencias:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Configurar variables de entorno:
   ```bash
   cp .env.example .env
   ```
   Editar `backend/.env` con los parametros de conexion a la base de datos PostgreSQL (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`).

4. Ejecutar migraciones e inicializar catalogos:
   ```bash
   python manage.py migrate
   python manage.py seed_catalogos_sunat
   ```

5. Iniciar el servidor de desarrollo:
   ```bash
   python manage.py runserver 8000
   ```

### 3. Configuracion del Frontend

1. Instalar modulos de Node.js:
   ```bash
   cd ../frontend
   npm install
   ```

2. Ejecutar el servidor de desarrollo:
   ```bash
   npm run dev
   ```
   La aplicacion web estara disponible en `http://localhost:5173`.

---

## Documentacion de la API (OpenAPI / Swagger)

Con el servidor backend en ejecucion, la documentacion interactiva de endpoints y esquemas esta disponible en:

- **Swagger UI:** `http://localhost:8000/api/docs/`
- **Esquema OpenAPI 3.0:** `http://localhost:8000/api/schema/`

---

## Suite de Pruebas Automatizadas

El proyecto cuenta con una cobertura integral de pruebas unitarias y de integracion:

- **Pruebas del Backend (Django Test Suite):**
  ```bash
  cd backend
  python manage.py test
  ```

- **Pruebas del Frontend (Node.js Test Runner):**
  ```bash
  cd frontend
  npm test
  ```

- **Compilacion y Validacion de Tipos (TypeScript / Vite):**
  ```bash
  cd frontend
  npm run build
  ```

---

## Licencia

Este proyecto se distribuye bajo la licencia **MIT**. Consulte el archivo `LICENSE` para mas detalles.
