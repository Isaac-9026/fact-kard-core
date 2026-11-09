# Índices de base de datos — Bloque 7

Se revisaron los índices existentes (`pg_indexes`) y las consultas de los listados
paginados de los Bloques 6–7. Solo se agregaron los que faltaban; no se duplicó ninguno.

| Índice | Tabla / migración | Consulta que mejora |
| --- | --- | --- |
| `ix_movimiento_empresa_fecha` (empresa, fecha_movimiento, prioridad_dia, secuencia, id) | `kardex.0002` | Kardex de toda la empresa (sin producto) y `/api/kardex/movimientos/` paginado: `WHERE empresa_id=? ORDER BY fecha, prioridad, secuencia, id LIMIT n`. `ix_movimiento_orden` empieza por producto y no sirve sin ese filtro. |
| `ix_documento_emp_estado_fecha` (empresa, estado, -fecha_emision, -id) | `documentos.0004` | `/api/documentos/?estado=…&page=…` (bandeja de borradores, anulados). Sin filtro de estado ya bastaba `idx_documento_empresa_fecha`. |
| `ix_auditoria_empresa_fecha` (empresa, -fecha, -id) | `auditoria.0002` | `/api/auditoria/?page=…`: la tabla solo crece (es inmutable) y antes solo tenía índice por empresa. |
| `ix_token_revocado_expira` (expira_en) | `usuarios.0003` | Limpieza de revocaciones expiradas en cada logout. La búsqueda por `jti` ya usa el índice único. |

Ya existían y se mantienen: movimientos por empresa/producto/fecha (`ix_movimiento_orden`),
por empresa/almacén/producto y por período; documentos por empresa/fecha, período, tercero
y origen; incidencias por empresa/estado y período/bloqueo; `token_revocado.jti` único.

## Medición

`EXPLAIN ANALYZE` en PostgreSQL 16 con datos sintéticos dentro de una transacción
revertida (auditoría 300 000 filas, token_revocado 100 000, documento 100 000,
movimiento 300 000):

| Consulta | Antes | Después |
| --- | --- | --- |
| Auditoría, primera página (50) | 90.8 ms, Seq Scan + sort | 0.06 ms, Index Scan `ix_auditoria_empresa_fecha` |
| Limpieza de tokens expirados | 41.6 ms, Seq Scan | 0.8 ms, Bitmap Index Scan `ix_token_revocado_expira` |
| Documentos `estado=BORRADOR`, primera página | 9.3 ms, recorre `idx_documento_empresa_fecha` filtrando | 0.09 ms, Index Scan `ix_documento_emp_estado_fecha` |
| Movimientos de toda la empresa, primera página | 51.7 ms, Seq Scan + sort | 0.08 ms, Index Scan `ix_movimiento_empresa_fecha` |

Nota: se crean con `CREATE INDEX` normal (bloquea escrituras de la tabla mientras se crea).
Con las tablas actuales tarda segundos; con millones de filas conviene aplicar la migración
fuera de horario.
