# REGLAS OBLIGATORIAS DEL AGENTE — PROYECTO FACT-KARD

Antes de proponer o modificar código, consulta siempre los archivos en `/docs/`:
1. `docs/FACT_KARD_BD_COMPLETA_SQL.md` (Esquema físico oficial e inalterable).
2. `docs/CONTEXTO_COMPLETO_FACT_KARD_ACTUALIZADO.md` (Reglas contables y de negocio).
3. `docs/MANUAL_COMPLETO_CONSTRUCCION_FACT_KARD.md` (Orden de fases y migraciones).
4. `docs/PLAN_MAESTRO_EJECUCION_DUPLA.md` (Flujo de trabajo del equipo).

## Reglas Técnicas Estrictas (Cero Excepciones)
1. **Fidelidad SQL 1:1:** Todo modelo de Django debe usar exactamente los mismos nombres de tabla (`db_table`), columnas, tipos `NUMERIC(20,8)` / `NUMERIC(7,4)`, `UniqueConstraint`, `CheckConstraint` e índices definidos en `FACT_KARD_BD_COMPLETA_SQL.md`. Prohibido inventar o eliminar campos.
2. **Prohibido `float`:** Todo cálculo monetario, de stock o factor de conversión debe usar `decimal.Decimal` con `ROUND_HALF_UP` (6 decimales operativos, 8 en base de datos).
3. **Aislamiento Multiempresa:** Toda consulta (`QuerySet`), serializer y vista debe filtrar obligatoriamente por `empresa_id`.
4. **Inmutabilidad:** Las tablas `movimiento` y `auditoria` son de solo inserción (`INSERT`). Prohibido usar `.update()` o `.delete()` sobre ellas.
5. **Concurrencia en Kardex:** Toda confirmación de movimiento o recálculo debe ejecutarse dentro de `with transaction.atomic():` aplicando `.select_for_update()` sobre `saldo_cpp_actual`.
6. **Commits:** Usar siempre Conventional Commits (`feat(modulo): ...`, `fix(modulo): ...`, `test(modulo): ...`).