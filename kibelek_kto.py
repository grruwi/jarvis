#!/usr/bin/env python3
"""kibelek_kto.py — kto siedzi przy tym terminalu.

Karol loguje sie na KONTO grruwiego (pelne prawa, wspolny `~`), wiec `whoami`
nie odroznia ludzi. Odroznia ich ADRES: tailscale daje kazdej maszynie staly
IP, a sshd wystawia go w `SSH_CONNECTION`. Brak `SSH_CONNECTION` = ktos siedzi
fizycznie przy kombajnie, czyli grruwi.

Mapa mieszka w `~/.config/jarvis/kibelek-osoby.json` — nowy czlowiek to wiersz
w JSON-ie, nie zmiana w kodzie.

⚠️ To identyfikacja WYGODNA, nie kryptograficzna: kto ma dostep do konta, moze
podac dowolne `--from`. Do dzielenia uprawnien to sie NIE nadaje.

(snake_case wbrew regule kebab-case dla skryptow — modulu z myslnikiem Python
nie zaimportuje.)
"""
import os, json

MAPA = os.path.expanduser("~/.config/jarvis/kibelek-osoby.json")


def kto(domyslny=None):
    """Zwraca alias osoby przy terminalu: 'karol', 'grruwi', ..."""
    try:
        with open(MAPA) as f:
            m = json.load(f)
    except Exception:
        return domyslny or "grruwi"

    zapas = domyslny or m.get("domyslny", "grruwi")
    polaczenie = os.environ.get("SSH_CONNECTION", "").split()
    if not polaczenie:
        return zapas                       # siedzi przy maszynie
    return m.get("po_ip", {}).get(polaczenie[0], zapas)


if __name__ == "__main__":
    print(kto())
