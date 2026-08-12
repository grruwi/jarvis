#!/usr/bin/env bash
# gienia-start.sh — odpala Gienię jako ŻYWĄ sesję tmux (widoczna, z pamięcią).
# Dispatcher wstrzykuje jej zadania (to:gienia) przez send-keys; ona sięga do kibelka
# własnym shellem (kib-send). grruwi ją wychowuje — to tylko starter.
#
#   Podgląd / rozmowa:   tmux attach -t gienia      (odłączenie: Ctrl-b, potem d)
#   Ubić:                tmux kill-session -t gienia
#
# UWAGA: -y = YOLO (auto-zatwierdzanie WSZYSTKICH narzędzi). Gienia MUSI mieć shell
# auto-approve, żeby sama odpalać kib-send bez pytania. To znaczy że może uruchomić
# dowolną komendę — to twój agent na twojej maszynie, ale miej to z tyłu głowy.
set -e
SESSION=gienia
MODEL=${1:-gemini-2.5-flash}      # koszt: gemini-2.5-flash tani, 3-flash drożej, 3.5-flash free-limit
DIR="$HOME/Dokumenty/jarvis/gienia"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Gienia już żyje. Podgląd:  tmux attach -t $SESSION"
    exit 0
fi

# wznów ostatnią sesję gemini (pamięć) jeśli jest; inaczej świeża
tmux new-session -d -s "$SESSION" -c "$DIR" \
    "gemini -m '$MODEL' -y -r latest 2>/dev/null || gemini -m '$MODEL' -y"

echo "Gienia odpalona (model $MODEL)."
echo "Podgląd/rozmowa:  tmux attach -t $SESSION    (odłącz: Ctrl-b d)"
