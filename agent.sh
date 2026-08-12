#!/usr/bin/env bash
# agent.sh <nazwa> [komenda...] — stawia CLI w panelu tmux i rejestruje adres.
#
#   agent claude              # panel `claude`, odpala Claude CLI
#   agent gienia              # panel `gienia`, odpala jej launcher
#   agent test 'cat'          # panel testowy (komendę można podać jawnie)
#
# Każdy agent zna SWOJĄ komendę — nazwa wystarczy, nic się nie powtarza.
#
# Osobno od `jarvis`, bo to inna kategoria: bus jest infrastrukturą i ma stać
# bez nikogo, a agent to sesja z tokenami i pamięcią — podnoszona świadomie.
#
# Po co tmux, skoro Konsole ma D-Bus: Konsole rejestruje KARTE, nie proces. Wyjdziesz
# z CLI — karta zyje dalej, adres pokazuje goly shell, a wstrzykniety tekst staje sie
# POLECENIEM. tmux podaje `pane_current_command`, wiec dispatcher sprawdza, kto siedzi
# w panelu, ZANIM cokolwiek wysle. Do tego panel przezywa restart GUI i jest dostepny
# przez SSH — kanal nie umiera razem z sesja graficzna.
#
# Adres to `pane_id` (`%7`), nie nazwa: tmux gwarantuje, ze jest unikalny i nie zmienia
# sie przez cale zycie panelu. Nazwy okien potrafia sie przemianowac same.
set -uo pipefail

CFG="$HOME/.config/jarvis"
name="${1:?uzycie: agent <nazwa> [komenda...]}"; shift

# Kto czym wstaje. Bez tego `agent gienia` odpalałoby Claude'a.
KOMENDA=("$@")
if [ ${#KOMENDA[@]} -eq 0 ]; then
    case "$name" in
        claude) KOMENDA=(claude) ;;
        gienia) KOMENDA=(gienia) ;;   # alias na gienia-launch.sh (sandbox + ccr)
        *) echo "nie znam agenta '$name' — podaj komendę jawnie" >&2; exit 2 ;;
    esac
fi

mkdir -p "$CFG"
command -v tmux >/dev/null || { echo "brak tmuxa" >&2; exit 1; }

# Każdy agent ma WŁASNĄ sesję o swojej nazwie: `tmux attach -t claude`.
# Wspólna sesja "jarvis" była błędem — jarvis to infra i nie ma z tmuxem nic wspólnego.
SESJA="$name"

# Komenda leci przez interaktywnego basha, bo `claude` to funkcja z ~/.bashrc
# (claude-tune pinuje rdzenie) — samo `claude` w respawn-pane by jej nie widzialo.
odpal="bash -lic $(printf '%q' "${KOMENDA[*]}")"

# Sesja powstaje OD RAZU z oknem agenta. Zakładanie jej z pustym oknem "glowne"
# zostawiało bezpańską powłokę obok każdego agenta.
NOWA_SESJA=""
if ! tmux has-session -t "$SESJA" 2>/dev/null; then
    tmux new-session -d -s "$SESJA" -n "$name" "$odpal"
    NOWA_SESJA=1
fi

# Panel juz zarejestrowany i zywy? Nie ruszamy go — restart CLI to decyzja czlowieka,
# nie efekt uboczny ponownego wywolania skryptu.
reg="$CFG/term-$name.json"
if [ -f "$reg" ]; then
    pane=$(jq -r '.pane // empty' "$reg" 2>/dev/null)
    if [ -n "$pane" ] && tmux list-panes -a -F '#{pane_id}' 2>/dev/null | grep -qx "$pane"; then
        cmd=$(tmux display-message -p -t "$pane" '#{pane_current_command}' 2>/dev/null)
        case "$cmd" in
            bash|sh|zsh|fish|dash) ;;   # w panelu goly shell — CLI wyszlo, stawiamy od nowa
            *) echo "$name: panel $pane zyje ($cmd) — zostawiam"; exit 0 ;;
        esac
    fi
fi

if [ -n "$NOWA_SESJA" ]; then
    pane=$(tmux list-panes -t "$SESJA:$name" -F '#{pane_id}' | head -1)
elif [ -n "${pane:-}" ] && tmux list-panes -a -F '#{pane_id}' 2>/dev/null | grep -qx "$pane"; then
    tmux respawn-pane -k -t "$pane" "$odpal"
else
    tmux new-window -d -t "$SESJA" -n "$name" "$odpal"
    pane=$(tmux list-panes -t "$SESJA:$name" -F '#{pane_id}' | head -1)
fi

tmux set-window-option -t "$pane" automatic-rename off >/dev/null 2>&1
printf '{"kind":"tmux","pane":"%s","session":"%s","window":"%s"}\n' \
       "$pane" "$SESJA" "$name" > "$reg"
echo "$name -> tmux $pane (${KOMENDA[*]}) | podglad: tmux attach -t $SESJA"
