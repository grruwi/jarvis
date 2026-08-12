#!/usr/bin/env bash
# tts-ctl.sh — guzik na CAŁY stack głosu (silnik F5 + dispatcher).
#   on      ładuje tts-f5.py --warm (F5 v0 do VRAM) ORAZ wstaje dispatcher (kibelek.sock)
#   off     ubija dispatcher I silnik -> zwalnia VRAM+RAM, sprząta oba sockety
#   status  stan obu warstw
# Stack = 2 usługi:  tts-f5 (tts.sock, VRAM)  <-  dispatcher (kibelek.sock, router).
# TUI (kibelek-tui.py) to OSOBNE okno — odpalasz je w terminalu, łączy się per-Enter.
set -u
JV="$HOME/Dokumenty/jarvis"
CFG="$HOME/.config/jarvis"
SOCK="$CFG/tts.sock"          # gniazdo silnika
DSOCK="$CFG/kibelek.sock"     # gniazdo dispatchera
LOG="$CFG/tts-f5.log"
DLOG="$CFG/dispatcher.log"
PY="$JV/.venv-f5/bin/python"  # silnik: własny venv (torch/rocm)

epid() { pgrep -f 'venv-f5/bin/python.*tts-f5'; }   # silnik (engine)
dpid() { pgrep -f 'python3? .*dispatcher\.py'; }     # dispatcher

start_engine() {
  if epid >/dev/null; then echo "  silnik: już żyje (PID $(epid))"; return; fi
  cd "$JV" || return 1
  echo "===== start tts-f5 $(date +%H:%M:%S) =====" >> "$LOG"
  setsid taskset -c 0-15 "$PY" tts-f5.py --warm >>"$LOG" 2>&1 &
  echo "  silnik: ładuję F5 v0 (--warm, kompilacja kerneli)... log: $LOG"
}
start_dispatcher() {
  if dpid >/dev/null; then echo "  dispatcher: już żyje (PID $(dpid))"; return; fi
  cd "$JV" || return 1
  echo "===== start dispatcher $(date +%H:%M:%S) =====" >> "$DLOG"
  setsid taskset -c 6,7,14,15 python3 dispatcher.py >>"$DLOG" 2>&1 &   # śmietnik, lekki router
  echo "  dispatcher: wstaje (kibelek.sock)... log: $DLOG"
}
kill_pid() {  # $1=pid $2=nazwa — SIGTERM, po 3s dobij
  local p="$1" n="$2"
  kill "$p" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$p" 2>/dev/null || break; sleep 0.3; done
  kill -0 "$p" 2>/dev/null && { echo "  $n: nie ustąpił, dobijam -9"; kill -9 "$p" 2>/dev/null; }
}

case "${1:-status}" in
  off|stop|zwolnij|rozladuj)
    d=$(dpid); if [ -n "$d" ]; then kill_pid "$d" dispatcher; echo "  dispatcher: ubity"; else echo "  dispatcher: już nie żył"; fi
    rm -f "$DSOCK"
    e=$(epid); if [ -n "$e" ]; then kill_pid "$e" silnik; echo "  silnik: ROZŁADOWANY (VRAM+RAM wolne)"; else echo "  silnik: już nie żył"; fi
    rm -f "$SOCK"
    echo "stack OFF — wszystko zwolnione"
    ;;
  on|start|zaladuj|laduj)
    echo "stack ON:"
    start_engine
    start_dispatcher
    echo "gotowe — okno: python3 $JV/kibelek-tui.py"
    ;;
  status|"")
    e=$(epid); d=$(dpid)
    if [ -n "$e" ]; then
      rss=$(awk '/VmRSS/{printf "%.1f GB", $2/1048576}' /proc/"$e"/status 2>/dev/null)
      echo "silnik F5 : ZAŁADOWANY (PID $e, RAM $rss, w VRAM)"
    else
      echo "silnik F5 : rozładowany (VRAM czysty)"
    fi
    if [ -n "$d" ] && ss -xl 2>/dev/null | grep -q "$DSOCK"; then
      echo "dispatcher: ŻYJE (PID $d, słucha na kibelek.sock)"
    elif [ -n "$d" ]; then
      echo "dispatcher: proces żyje (PID $d) ale NIE słucha — restart: tts off && tts on"
    else
      echo "dispatcher: martwy (kibelek → errno 111)"
    fi
    ;;
  *) echo "użycie: tts {on|off|status}"; exit 1;;
esac
