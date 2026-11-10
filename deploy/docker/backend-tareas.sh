#!/bin/sh
# Tareas automáticas de Fact-Kard Core (servicio "tareas" de compose.yaml).
#
# Respaldo completo diario (base de datos + media) con `manage.py respaldo crear`,
# que además aplica la retención (diarios / semanales / mensuales). Hora: FK_RESPALDO_HORA (HH:MM,
# hora de Lima; 04:00 por defecto, después del respaldo de FACT-KARD (03:30)).
# Un fallo no detiene el servicio: se registra y se reintenta al día siguiente.
set -eu

HORA="${FK_RESPALDO_HORA:-04:00}"
case "$HORA" in
    [01][0-9]:[0-5][0-9]|2[0-3]:[0-5][0-9]) ;;
    *) echo "[tareas] FK_RESPALDO_HORA inválida: '$HORA' (use HH:MM)" >&2; exit 1 ;;
esac

# Señal de vida para el healthcheck y salida limpia al detener el contenedor.
VIVO=/tmp/fk-tareas.vivo
trap 'rm -f "$VIVO"; exit 0' TERM INT
date '+%F %T' > "$VIVO"
echo "[tareas] Respaldo diario programado a las $HORA (America/Lima)."

segundos_hasta() {
    ahora=$(date +%s)
    objetivo=$(date -d "today $1" +%s)
    if [ "$objetivo" -le "$ahora" ]; then
        objetivo=$(date -d "tomorrow $1" +%s)
    fi
    echo $((objetivo - ahora))
}

while :; do
    espera=$(segundos_hasta "$HORA")
    sleep "$espera" &
    wait $! || true
    date '+%F %T' > "$VIVO"
    echo "[tareas] $(date '+%F %T') Iniciando respaldo completo."
    if python manage.py respaldo crear; then
        echo "[tareas] $(date '+%F %T') Respaldo terminado."
    else
        echo "[tareas] $(date '+%F %T') ERROR: el respaldo falló; se reintentará mañana. Revise los logs." >&2
    fi
    sleep 61 &
    wait $! || true
done
