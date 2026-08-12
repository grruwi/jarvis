#!/usr/bin/env bash
# term-register.sh <nazwa> — rejestruje BIEŻĄCĄ sesję Konsole w adresowniku Jarvisa.
#
# Konsole eksportuje KONSOLE_DBUS_SERVICE + KONSOLE_DBUS_SESSION do każdej karty.
# Zapisujemy je pod nazwą-adresatem (claude/gienia) → dispatcher celuje po session-ID
# (qdbus sendText), niezależnie od fokusu. To NIE tajny kanał — tylko mapa "gdzie stoi CLI".
#
# Wywołanie: przy starcie CLI (SessionStart hook / launcher). Idempotentne — nadpisuje wpis.
name="${1:?podaj nazwę adresata (claude/gienia)}"
CFG="$HOME/.config/jarvis"
mkdir -p "$CFG"

# tmux ma pierwszeństwo: `pane_id` żyje tyle co panel i dispatcher potrafi sprawdzić,
# KTO w nim siedzi, zanim cokolwiek wyśle. Konsole rejestruje samą KARTĘ — wyjdziesz z
# CLI, karta zostaje, a wstrzyknięty tekst staje się poleceniem dla gołego basha
# (dokładnie tak wyglądał ten adresownik 2026-08-02).
if [ -n "${TMUX:-}" ] && [ -n "${TMUX_PANE:-}" ]; then
  printf '{"kind":"tmux","pane":"%s","session":"%s","window":"%s"}\n' \
    "$TMUX_PANE" "$(tmux display-message -p -t "$TMUX_PANE" '#{session_name}')" \
    "$(tmux display-message -p -t "$TMUX_PANE" '#{window_name}')" > "$CFG/term-$name.json"
  echo "term-register: $name -> tmux $TMUX_PANE" >&2
  exit 0
fi

if [ -z "${KONSOLE_DBUS_SERVICE:-}" ] || [ -z "${KONSOLE_DBUS_SESSION:-}" ]; then
  echo "term-register: brak KONSOLE_DBUS_* (nie w Konsoli?) — pomijam rejestrację" >&2
  exit 0
fi

# Zmienna w środowisku NIE dowodzi, że karta żyje. Proces odpięty od terminala
# (sesja w tle, `setsid`, demon) dziedziczy KONSOLE_DBUS_SERVICE po Konsoli, która
# dawno padła — i rejestrował adres trupa, kasując przy okazji dobry wpis tmuxa.
# Dokładnie tak zginął kanał głosowy 2026-08-03: sesja w Coworku wystartowała z
# odziedziczonym `:1.288`, dispatcher dostał martwy adres, dyktafon gadał w próżnię.
# Pytamy więc samą sesję o tytuł — martwa nazwa D-Bus zwraca błąd.
QD=$(command -v qdbus6 || command -v qdbus)
if [ -z "$QD" ] || ! "$QD" "$KONSOLE_DBUS_SERVICE" "$KONSOLE_DBUS_SESSION" \
        org.kde.konsole.Session.title 1 >/dev/null 2>&1; then
  echo "term-register: $KONSOLE_DBUS_SERVICE$KONSOLE_DBUS_SESSION nie odpowiada — NIE nadpisuję $name" >&2
  exit 0
fi

printf '{"svc":"%s","ses":"%s"}\n' "$KONSOLE_DBUS_SERVICE" "$KONSOLE_DBUS_SESSION" > "$CFG/term-$name.json"
echo "term-register: $name -> $KONSOLE_DBUS_SERVICE $KONSOLE_DBUS_SESSION" >&2
