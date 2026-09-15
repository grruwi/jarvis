#!/usr/bin/env python3
"""kibelek-ntfy-most.py — most z telefonu na KIBELEK przez ntfy.

Co robi: siedzi na strumieniu ntfy i kazda wiadomosc, ktora tam wpadnie,
wrzuca na szyne kibelka DOKLADNIE tak, jakby grruwi wpisal ja w TUI.

Zasada naczelna: most NICZEGO NIE INTERPRETUJE. Kopiuje logike z
kibelek-tui.py:574-580 co do znaku — bez tagu leci `to: "log"` (wiadomosc
zostaje w feedzie i nikt jej nie czyta), z tagiem @klodzio / @voice /
@gienia / @claude idzie do dispatchera, ktory robi swoje jak zawsze.

⛔ Strumien, NIE `?poll=1`. Poll zwraca CALY bufor (12 h wstecz) — tutaj
przyszlaby wtedy lawina starych wiadomosci przy kazdym restarcie.
Strumien daje wylacznie to, co przyjdzie od momentu podlaczenia.

Uruchomienie: systemd --user (kibelek-ntfy-most.service) albo recznie.
"""
import json
import os
import socket
import sys
import time
import urllib.request

# ── konfiguracja ─────────────────────────────────────────────────────────
NTFY = "http://127.0.0.1:2586"
TEMAT = os.environ.get("KIBELEK_NTFY_TEMAT", "kibelek")
NADAWCA = "grruwi"          # kto pisze z tego tematu; temat = jedyny zamek
SOCK = os.path.expanduser("~/.config/jarvis/kibelek.sock")

# Ta sama lista co kibelek-tui.py:37. Rozjedzie sie — most zacznie
# wysylac do "log" cos, co w TUI poszloby do dispatchera.
TARGETS = ["klodzio", "claude", "voice", "gienia"]


def log(txt):
    print(f"{time.strftime('%H:%M:%S')}  {txt}", flush=True)


def na_szyne(target, text):
    """Kopia kibelek-tui.py:send() — ta sama koperta, ten sam socket."""
    msg = {"from": NADAWCA, "to": target, "type": "task",
           "payload": text, "lang": "pl", "engine": "f5"}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(SOCK)
    except (FileNotFoundError, ConnectionRefusedError):
        return "kibelek nie dziala (dispatcher lezy)"
    try:
        s.sendall(json.dumps(msg).encode())
        s.recv(4096)
    finally:
        s.close()
    return None


def adresat(text):
    """Kopia kibelek-tui.py:576-579. Bez @ nikt nie skacze."""
    target = "log"
    for t in TARGETS:
        if text.lower().startswith("@" + t):
            return t, text[len(t) + 1:].strip()
    return target, text


def sluchaj():
    url = f"{NTFY}/{TEMAT}/json"
    with urllib.request.urlopen(url, timeout=None) as strumien:
        log(f"podlaczony do {TEMAT}")
        for linia in strumien:
            linia = linia.strip()
            if not linia:
                continue
            try:
                m = json.loads(linia)
            except json.JSONDecodeError:
                continue
            if m.get("event") != "message":
                continue          # open / keepalive
            tekst = (m.get("message") or "").strip()
            if not tekst:
                continue
            target, tresc = adresat(tekst)
            blad = na_szyne(target, tresc)
            log(f"-> {target}: {tresc[:60]}" + ("" if not blad else f"  [BLAD: {blad}]"))


def main():
    while True:
        try:
            sluchaj()
            log("strumien zamkniety przez serwer — lacze ponownie za 5 s")
        except KeyboardInterrupt:
            log("koniec")
            return 0
        except Exception as e:
            log(f"zerwane ({type(e).__name__}: {e}) — ponawiam za 5 s")
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
