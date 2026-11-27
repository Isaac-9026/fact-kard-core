#!/bin/sh
# Tareas automáticas de Fact-Kard Core (servicio "tareas" de compose.yaml).
#
# Ejecuta de forma concurrente y sin bloquearse entre sí:
#   1. Worker continuo de cola de importaciones y anulaciones (`manage.py procesar_trabajos_importacion`).
#   2. Respaldo completo diario (base de datos + media) a las FK_RESPALDO_HORA (04:00 America/Lima por defecto)
#      con `manage.py respaldo crear`.
# Un fallo no detiene el servicio: se registra y se reintenta.
set -eu

HORA="${FK_RESPALDO_HORA:-04:00}"
case "$HORA" in
    [01][0-9]:[0-5][0-9]|2[0-3]:[0-5][0-9]) ;;
    *) echo "[tareas] FK_RESPALDO_HORA inválida: '$HORA' (use HH:MM)" >&2; exit 1 ;;
esac

INTERVALO="${FK_IMPORTACION_INTERVALO:-2}"
VIVO=/tmp/fk-tareas.vivo
RESPALDO_PID=""
WORKER_PID=""
WAIT_PID=""

apagar() {
    rm -f "$VIVO"
    [ -n "$WAIT_PID" ] && kill "$WAIT_PID" 2>/dev/null || true
    [ -n "$WORKER_PID" ] && kill "$WORKER_PID" 2>/dev/null || true
    [ -n "$RESPALDO_PID" ] && kill "$RESPALDO_PID" 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}
trap apagar TERM INT

date '+%F %T' > "$VIVO"
echo "[tareas] Respaldo diario programado a las $HORA (America/Lima)."
echo "[tareas] Worker de importaciones iniciado (intervalo=${INTERVALO}s)."

segundos_hasta() {
    ahora=$(date +%s)
    objetivo=$(date -d "today $1" +%s)
    if [ "$objetivo" -le "$ahora" ]; then
        objetivo=$(date -d "tomorrow $1" +%s)
    fi
    echo $((objetivo - ahora))
}

ciclo_respaldo() {
    SLEEP_PID=""
    trap '[ -n "$SLEEP_PID" ] && kill "$SLEEP_PID" 2>/dev/null || true; exit 0' TERM INT
    while :; do
        espera=$(segundos_hasta "$HORA")
        sleep "$espera" &
        SLEEP_PID=$!
        wait "$SLEEP_PID" || true
        SLEEP_PID=""
        date '+%F %T' > "$VIVO"
        echo "[tareas] $(date '+%F %T') Iniciando respaldo completo."
        if python manage.py respaldo crear; then
            echo "[tareas] $(date '+%F %T') Respaldo terminado."
        else
            echo "[tareas] $(date '+%F %T') ERROR: el respaldo falló; se reintentará mañana. Revise los logs." >&2
        fi
        sleep 61 &
        SLEEP_PID=$!
        wait "$SLEEP_PID" || true
        SLEEP_PID=""
    done
}

ciclo_respaldo &
RESPALDO_PID=$!

while :; do
    python manage.py procesar_trabajos_importacion --intervalo "$INTERVALO" --archivo-vivo "$VIVO" &
    WORKER_PID=$!
    wait "$WORKER_PID" || true
    WORKER_PID=""
    sleep 3 &
    WAIT_PID=$!
    wait "$WAIT_PID" || true
    WAIT_PID=""
done
