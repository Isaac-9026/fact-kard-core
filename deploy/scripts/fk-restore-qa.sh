#!/usr/bin/env bash
# FACT-KARD — PRUEBA de restauración en una base TEMPORAL (nunca en la base real).
#
#   sudo -u postgres bash /srv/fact-kard/app/deploy/scripts/fk-restore-qa.sh /var/backups/fact-kard/diario/fact_kard_XXXX.dump
#
# Crea fact_kard_restore_qa_<fecha>, restaura, compara conteos de tablas clave con la base
# real (solo lectura) y BORRA la base temporal al terminar (salvo FK_CONSERVAR_QA=1).
set -euo pipefail
ARCHIVO="${1:?Uso: fk-restore-qa.sh <archivo.dump>}"
REAL="${FK_DB_NAME:-fact_kard}"
QA="fact_kard_restore_qa_$(date +%Y%m%d%H%M%S)"

case "$QA" in fact_kard_restore_qa_*) ;; *) echo "Nombre de base QA inesperado" >&2; exit 1;; esac
[ "$QA" != "$REAL" ] || { echo "La base QA no puede ser la real" >&2; exit 1; }

if [ -f "$ARCHIVO.sha256" ]; then
  ( cd "$(dirname "$ARCHIVO")" && sha256sum --check --quiet "$(basename "$ARCHIVO").sha256" )
  echo "[restore-qa] Checksum correcto."
fi

limpiar() {
  if [ "${FK_CONSERVAR_QA:-0}" != "1" ]; then dropdb --if-exists "$QA"; echo "[restore-qa] Base temporal $QA eliminada."; fi
}
trap limpiar EXIT

createdb "$QA"
pg_restore --no-owner --no-privileges --exit-on-error --dbname="$QA" "$ARCHIVO"
echo "[restore-qa] Restaurado en $QA. Comparando con $REAL (el backup puede ser anterior):"
for t in empresa usuario periodo documento movimiento valorizacion_movimiento cierre_periodo auditoria; do
  r=$(psql -XAtqd "$REAL" -c "select count(*) from $t" 2>/dev/null || echo '?')
  q=$(psql -XAtqd "$QA" -c "select count(*) from $t" 2>/dev/null || echo '?')
  printf '  %-26s real=%-8s backup=%s\n' "$t" "$r" "$q"
done
psql -XAtqd "$QA" -c "select 'migraciones aplicadas: ' || count(*) from django_migrations"
