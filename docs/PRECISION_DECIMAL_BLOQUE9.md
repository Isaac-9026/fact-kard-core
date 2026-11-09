# Precisión decimal y correcciones preproducción (Bloque 9)

## Causa raíz del hallazgo `0.00004875`

El formulario de comprobantes sugería el IGV de cada línea con aritmética IEEE-754 y **sin
redondear a céntimos**:

```ts
// antes (utils/afectacionIgv.ts)
return (parseFloat(cantidad) * parseFloat(precio) * tasa).toFixed(8);
```

El backend calcula el IGV esperado como `base × tasa` redondeado a `0.01` con `ROUND_HALF_UP`
y acepta el IGV recibido con una tolerancia de ±0.01 (`afectacion_igv.validar_igv_linea`),
pero **guarda el valor que envía el frontend**. Con cantidad `2.5`, precio `0.066775` e
IGV 18 %:

| | IGV de la línea | Total guardado |
| --- | --- | --- |
| Antes (float, 8 decimales) | `0.03004875` | `0.19698625` |
| Correcto (Decimal, HALF_UP) | `0.03000000` | `0.19693750` |
| Diferencia | `0.00004875` | `0.00004875` |

Problemas relacionados, corregidos en el mismo bloque:

1. Los totales del formulario se sumaban en float y se mostraban con `toFixed(2)`:
   `(1.005).toFixed(2)` da `"1.00"`, mientras que `ROUND_HALF_UP` da `1.01`.
2. Backend: `subtotal`, `igv` y `total` del documento se redondeaban con
   `quantize(Decimal('0.00000001'))` **sin** `rounding`, es decir con el modo por defecto de
   Python, `ROUND_HALF_EVEN`. Ante un empate en el 9.º decimal
   (`1.267345665`) guardaba `1.26734566`; con `ROUND_HALF_UP`, como el resto del sistema, es
   `1.26734567`. Ahora el redondeo es explícito.
3. Otras pantallas mostraban importes del backend convirtiéndolos a `Number`, con lo que se
   arrastraba el mismo error de redondeo en la presentación.

## Estrategia

- **Librería:** `big.js` 7.0.1 (≈6 KB, sin dependencias), aislada en
  `frontend/src/utils/decimal.ts` con un constructor propio (`RM = ROUND_HALF_UP`). Nadie más
  importa `big.js`.
- **Entradas y salidas como texto** (como en la API): nunca Decimal → float → Decimal.
- **Cálculos del formulario = reglas del backend** en `frontend/src/utils/documentoCalculo.ts`:
  base imponible (ajuste de valor sin cantidad = precio), IGV esperado (a céntimos, HALF_UP),
  cantidad base (6 decimales, HALF_UP), subtotal/IGV/total (8 decimales, HALF_UP, total
  redondeado una sola vez).
- **Autoridad:** el backend sigue validando y guardando; los costos en PEN con tipo de cambio
  y el CPP siguen siendo exclusivos del backend. El frontend solo previsualiza, valida y
  muestra.
- **Presentación:** `formatearDecimal(valor, {min, max})` primero redondea en decimal
  (HALF_UP) y después da formato es-PE.

## Operaciones migradas

| Dónde | Antes | Ahora |
| --- | --- | --- |
| `utils/afectacionIgv.ts` `igvSugerido` | `parseFloat × parseFloat × tasa` `.toFixed(8)` | `igvEsperado(baseImponible(…), tasa)` |
| `DocumentosPage` totales del formulario | suma float + `toFixed(2)` | `totalesDocumento()` + `formatearDecimal` |
| `DocumentosPage` cantidad base | `(cant × factor).toFixed(2)`; factor con `parseFloat` | `cantidadBase()`; factor como texto de la API |
| `DocumentosPage` importe de línea (detalle) | `Number × Number` `.toFixed(2)` | `importeLinea()` |
| `DocumentosPage` validación de cantidad | `parseFloat(x) <= 0` | `esMayorQueCero(x)` |
| `DocumentosPage` subtotal/IGV/total/TC en listas y detalle | `Number().toLocaleString` / `toFixed` | `formatearDecimal` |
| `DocumentosPage` IGV al cambiar la fecha | no se recalculaba (tasa histórica) | se vuelve a sugerir con la tasa vigente |
| `DocumentosPage` símbolo de moneda del resumen | siempre `S/` | `S/` o `US$` según la moneda |
| `IncidenciasPage` Δ saldo de recálculo | `Number − Number` `.toFixed(4)` | `restar()` + `formatearDecimal` |
| Kardex, Dashboard, Inventario, Cierres, Saldos iniciales, Captura | `Number().toLocaleString` / `toFixed` | `formatearDecimal` |
| Backend `documentos/services.py` totales | `quantize` sin `rounding` (HALF_EVEN) | `rounding=ROUND_HALF_UP` |

## Usos de `Number` que permanecen (seguros)

| Uso | Por qué es seguro |
| --- | --- |
| `Number(e.target.value)` / `Number(form.x)` de selects | identificadores enteros (ids, año, mes, decimales de configuración) |
| `paginacion.ts` `Number(data.count)` | conteo entero |
| `kardexVista.ts`, `stockActual.ts`, `CierresPage` (`!== 0`) | solo deciden si un valor del backend es cero (para mostrar/colorear); un decimal distinto de cero no se vuelve 0 en float |
| Captura: confianza OCR `toFixed(1)`, tamaño `KB` | no son importes |
| Captura: `Number(a) - Number(b)` | ordena números de línea |
| Transferencias `parseFloat(cantidad_base) > 0` | solo valida el signo; la cantidad se envía como texto y la valida el backend |
| Fechas `toLocaleString` | no son números |

`frontend/src/utils/sinFloatMonetario.test.ts` falla si aparece `parseFloat`, `.toFixed`,
`Number(...).toLocaleString` u operaciones con `Number(...)` fuera de esta lista blanca.

## Casos de oro compartidos frontend ↔ backend

`qa/precision/casos_documentos.json` (generado por `qa/precision/generar_casos.py` con
`decimal.Decimal` + `ROUND_HALF_UP`, sin usar código de la aplicación):

| Caso | Qué cubre |
| --- | --- |
| `auditoria_0_00004875` | el caso exacto de la auditoría |
| `suma_0_1_mas_0_2` | 0.1 + 0.2 |
| `compra_fraccionaria_precios_6_dec` | cantidades fraccionarias, precios de 4–6 decimales, factores de conversión, gravado/exonerado/inafecto |
| `redondeo_mitad_hacia_arriba` | empates: IGV 0.045 → 0.05; subtotal 1.267345665 → 1.26734567 |
| `compra_usd_tc` | USD con TC 3.751 (los totales se guardan en USD; el costo PEN lo calcula el backend) |
| `tasa_historica_16` | tasa histórica configurada (16 %), no 18 % fijo |
| `venta_exportacion_gratuito` | venta con gravado, exportación y bonificación gratuita |
| `nc_descuento_compra` | NC de compra (ajuste de valor) |
| `nd_cargo_venta` | ND de venta (ajuste de valor) |

- Frontend: `src/utils/precisionDocumentos.test.ts` calcula cada caso como el formulario.
- Backend: `apps/documentos/tests_b9_precision.py` crea cada caso por la API, compara lo
  guardado (líneas y cabecera), lo revisa y lo confirma.
- Los descuentos comerciales del sistema son NC de ajuste de valor (no hay descuento por línea).

## Responsive

Causa: la columna de contenido era un hijo flex sin `min-w-0`, así que cualquier tabla ancha
estiraba toda la página; además la barra lateral fija de 256 px ocupaba dos tercios de un móvil.

- `MainLayout`: en móvil (< 768 px) la barra lateral es un panel desplegable (botón ☰, se
  cierra al elegir una opción); `min-w-0` en la columna de contenido; cabecera compacta.
- `Card` con `min-w-0`; `TabsList` con desplazamiento horizontal propio; filas de botones y
  hashes que se ajustan (Cierres, Captura); pie del modal de comprobantes apilable.
- Las tablas se desplazan dentro de su contenedor; las acciones siguen accesibles.

Medición (ancho del documento = ancho de la ventana en las 19 pantallas):

| | 390 | 768 | 1024 | 1440 |
| --- | --- | --- | --- | --- |
| Antes | 19/19 desbordan (máx. 1484 px) | 19/19 | 19/19 | 1/19 (Kardex 1500) |
| Después | 0 | 0 | 0 | 0 |

## Cookie HttpOnly

Ver `SEGURIDAD_TOKEN_LOCALSTORAGE.md` §Bloque 9 y `DESPLIEGUE_VPS.md` §Cookie HttpOnly.
