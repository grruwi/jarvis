#!/usr/bin/env bash
# jarvis.sh — magistrala. Jedna komenda na cały bus.
#
#   jarvis          POSTAW infrastrukturę (dispatcher + kibelek + ptt)
#   jarvis down     zdejmij ją
#   jarvis status   co żyje
#   jarvis log      ostatnie linie z panelu dispatchera
#
# Agenci (Claude, Gienia) stoją OSOBNO — `agent claude`. To celowe rozdzielenie:
# bus jest infrastrukturą i ma żyć bez nikogo, agent to sesja z tokenami i pamięcią,
# którą podnosi się świadomie.
set -uo pipefail

SERWIS=jarvis-dispatcher.service
CFG="$HOME/.config/jarvis"

# Istnienie PLIKU socketa niczego nie dowodzi — zostaje po ubitym dispatcherze.
# Dowodem jest udane połączenie: ktoś po drugiej stronie faktycznie odbiera.
kibelek_zyje() {
    python3 - "$CFG/kibelek.sock" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(socket.AF_UNIX); s.settimeout(1)
try:
    s.connect(sys.argv[1]); s.close()
except Exception:
    sys.exit(1)
PY
}

case "${1:-up}" in

up)
    # 1. DISPATCHER — serwis systemd. On posiada socket, więc kibelek wstaje z nim.
    printf 'dispatcher : '
    systemctl --user start "$SERWIS" 2>/dev/null
    # Czekamy na ODBIÓR, nie na plik: plik socketa powstaje przy bind(),
    # czyli zanim dispatcher wejdzie w listen(). Sam plik to za wcześnie.
    for _ in $(seq 1 20); do
        kibelek_zyje && break
        sleep 0.3
    done
    if kibelek_zyje; then
        echo "stoi"
    else
        echo "NIE WSTAŁ — jarvis log"; exit 1
    fi

    # 2. KIBELEK — to socket dispatchera, nie osobny proces. Meldujemy stan,
    #    bo bez niego cała magistrala jest głucha, a plik potrafi zostać po trupie.
    printf 'kibelek    : '
    if kibelek_zyje; then echo "słucha"; else echo "socket martwy"; fi

    # 3. PTT — demon evdev, osobny serwis systemd.
    printf 'ptt        : '
    if [ "$(systemctl --user is-active dyktafon-ptt.service 2>/dev/null)" = "active" ]; then
        echo "active"
    else
        systemctl --user start dyktafon-ptt.service 2>/dev/null
        sleep 0.5
        systemctl --user is-active dyktafon-ptt.service 2>/dev/null
    fi ;;

down)
    systemctl --user stop "$SERWIS" 2>/dev/null; echo "dispatcher : zdjęty"
    systemctl --user stop dyktafon-ptt.service 2>/dev/null; echo "ptt        : zdjęty" ;;

log)
    journalctl --user -u "$SERWIS" -n "${2:-20}" --no-pager -o cat ;;

status)
    printf 'dispatcher : '
    echo "$(systemctl --user is-active "$SERWIS" 2>/dev/null)$(systemctl --user is-enabled "$SERWIS" 2>/dev/null | sed 's/^/, autostart: /')"

    printf 'kibelek    : '
    if kibelek_zyje; then
        echo "słucha, feed $(wc -l < "$CFG/kibelek-feed.jsonl" 2>/dev/null || echo 0) wpisów"
    elif [ -S "$CFG/kibelek.sock" ]; then
        echo "socket-widmo (plik jest, nikt nie odbiera)"
    else
        echo "brak socketa"
    fi

    printf 'ptt        : '
    systemctl --user is-active dyktafon-ptt.service 2>/dev/null ;;

stop)
    # Ucina TRWAJĄCĄ WYPOWIEDŹ, nie magistralę — `down` zdejmuje infrastrukturę,
    # `stop` tylko zamyka usta. Osobno, bo to dwie różne intencje i pomylenie ich
    # w środku zdania kosztowałoby cały bus.
    "$HOME/Dokumenty/skrypcipki/jarvis-stop.sh" ;;

*)  echo "użycie: jarvis [status|up|down|log|stop]" >&2; exit 2 ;;
esac
