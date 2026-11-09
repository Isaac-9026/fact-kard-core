#!/usr/bin/env bash
# FACT-KARD — backup de PostgreSQL (formato custom de pg_dump) con verificación.
#
# LEGADO (Bloque 8): solo respalda la BASE DE DATOS. Desde el Bloque 24 el respaldo oficial es
#   python manage.py respaldo crear   (base + artefactos SUNAT + media, manifest SHA-256)
# Ver docs/RESPALDO_Y_RESTAURACION.md. Este script se conserva para respaldos manuales de emergencia.
#
# Se ejecuta como el usuario `postgres` (autenticación local "peer", sin contraseña en disco):
#   sudo -u postgres bash /srv/fact-kard/app/deploy/scripts/fk-backup.sh
# o automáticamente con systemd (fact-kard-backup.timer).
#
# Variables (con sus valores por defecto):
#   FK_DB_NAME=fact_kard  FK_BACKUP_DIR=/var/backups/fact-kard
#   FK_RETENCION_DIAS=14  FK_RETENCION_MESES=12
#
# Retención: se conservan los diarios de los últimos FK_RETENCION_DIAS días y una copia
# mensual (la del día 1) durante FK_RETENCION_MESES meses. Solo se eliminan archivos
# fact_kard_*.dump/.sha256 dentro de FK_BACKUP_DIR. Nunca toca la base de datos.
set -euo pipefail
umask 077

DB="${FK_DB_NAME:-fact_kard}"
DIR="${FK_BACKUP_DIR:-/var/backups/fact-kard}"
DIAS="${FK_RETENCION_DIAS:-14}"
MESES="${FK_RETENCION_MESES:-12}"
FECHA="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$DIR/diario" "$DIR/mensual"
DESTINO="$DIR/diario/${DB}_${FECHA}.dump"
TEMPORAL="$DESTINO.parcial"

echo "[fk-backup] Respaldando ${DB} → ${DESTINO}"
pg_dump --format=custom --compress=6 --no-owner --no-privileges --file="$TEMPORAL" "$DB"

# Verificación: el archivo debe poder leerse completo por pg_restore.
if ! pg_restore --list "$TEMPORAL" > /dev/null; then
  echo "[fk-backup] ERROR: el backup no es legible; se descarta." >&2
  rm -f -- "$TEMPORAL"
  exit 1
fi
mv -- "$TEMPORAL" "$DESTINO"
( cd "$DIR/diario" && sha256sum "$(basename "$DESTINO")" > "$(basename "$DESTINO").sha256" )
echo "[fk-backup] OK: $(du -h "$DESTINO" | cut -f1), $(pg_restore --list "$DESTINO" | grep -c 'TABLE DATA') tablas con datos."

# Copia mensual el día 1.
if [ "$(date +%d)" = "01" ]; then
  cp -- "$DESTINO" "$DESTINO.sha256" "$DIR/mensual/"
fi

# Retención (solo archivos de backup de esta base).
find "$DIR/diario" -maxdepth 1 -type f \( -name "${DB}_*.dump" -o -name "${DB}_*.dump.sha256" \) -mtime +"$DIAS" -print -delete
find "$DIR/mensual" -maxdepth 1 -type f \( -name "${DB}_*.dump" -o -name "${DB}_*.dump.sha256" \) -mtime +"$((MESES * 31))" -print -delete
