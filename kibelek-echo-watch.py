#!/usr/bin/env python3
"""kibelek-echo-watch.py — pilnuje transkryptow i wypuszcza moje wypowiedzi na kibelek.

DLACZEGO NIE HOOK `Stop` (poprzednie podejscie, 2026-08-12):
hook startuje w tej samej chwili, w ktorej finalna odpowiedz trafia do jsonl —
czasem zdazy, czasem nie. Czekanie na "az plik przestanie rosnac" tez zawodzi,
bo w trakcie tury plik staje na czas kazdego tool calla. A dedup po uuid zamienial
jedno chybienie w TRWALA cisze: raz zapisany stary uuid blokowal wszystko dalej.

TERAZ: nikt nie zgaduje, kiedy zapis sie skonczyl. Sledzimy PRZYROST pliku i kazda
domknieta linie wypuszczamy od razu. Efekt uboczny jest pozadany — Karol widzi
wypowiedzi po kawalku, w tym samym rytmie co grruwi na czacie, zamiast dostawac
cala ture po fakcie.

Obejmuje WSZYSTKIE sesje naraz (Cowork, CLI, Gienia) — nadawca bierze sie ze
sciezki, bo Gienia pisze do wlasnego drzewa `~/.claude-code-router`.

⚠️ Na starcie ustawia sie na KONIEC istniejacych plikow. Bez tego pierwszy przebieg
wypluje na kibelek cala historie sesji.

Uruchomienie (na probe):  python3 kibelek-echo-watch.py &
Zatrzymanie:              pkill -f kibelek-echo-watch
"""
import os, sys, json, time, glob, subprocess

KIB_SEND = os.path.expanduser("~/Dokumenty/jarvis/kib-send.py")
POZYCJE  = os.path.expanduser("~/.config/jarvis/kibelek-echo-pozycje.json")
WZORCE   = [os.path.expanduser("~/.claude/projects/*/*.jsonl"),
            os.path.expanduser("~/.claude-code-router/projects/*/*.jsonl")]
ODSTEP   = 1.0      # sekundy miedzy zerknieciami
LIMIT    = 4000     # znakow na wiadomosc


def kto_z_sciezki(sciezka):
    return "gienia" if ".claude-code-router" in sciezka else "klodzio"


def wczytaj_pozycje():
    try:
        with open(POZYCJE) as f:
            return json.load(f)
    except Exception:
        return {}


def zapisz_pozycje(p):
    try:
        os.makedirs(os.path.dirname(POZYCJE), exist_ok=True)
        with open(POZYCJE, "w") as f:
            json.dump(p, f)
    except Exception as e:
        print(f"[echo-watch] nie zapisalem pozycji: {e!r}", file=sys.stderr)


def pliki():
    for w in WZORCE:
        for f in glob.glob(w):
            yield f


def tekst_z_linii(linia):
    """Zwraca tresc mojej wypowiedzi albo None. Pomija myslenie, tool calle i sidechainy."""
    try:
        d = json.loads(linia)
    except Exception:
        return None
    if d.get("type") != "assistant" or d.get("isSidechain"):
        return None
    kawalki = [c.get("text", "") for c in d.get("message", {}).get("content", [])
               if isinstance(c, dict) and c.get("type") == "text"]
    tekst = "\n".join(k for k in kawalki if k.strip()).strip()
    return tekst or None


def wyslij(nadawca, tekst):
    if len(tekst) > LIMIT:
        tekst = tekst[:LIMIT] + " […]"
    if tekst.startswith("-"):
        tekst = " " + tekst          # kib-send wzialby myslnik za flage
    try:
        subprocess.run([sys.executable, KIB_SEND, "--from", nadawca, "--to", "log", tekst],
                       timeout=5, capture_output=True)
    except Exception as e:
        print(f"[echo-watch] kibelek nie odebral: {e!r}", file=sys.stderr)


def main():
    poz = wczytaj_pozycje()
    # pierwszy raz widziany plik = ustaw sie na jego koniec, nie na poczatek
    for f in pliki():
        if f not in poz:
            try:
                poz[f] = os.path.getsize(f)
            except OSError:
                poz[f] = 0
    zapisz_pozycje(poz)
    print(f"[echo-watch] pilnuje {len(poz)} transkryptow", file=sys.stderr, flush=True)

    while True:
        zmiana = False
        for f in pliki():
            try:
                rozmiar = os.path.getsize(f)
            except OSError:
                continue
            start = poz.get(f)
            if start is None:                 # plik pojawil sie w trakcie — nowa sesja
                poz[f] = rozmiar; zmiana = True; continue
            if rozmiar < start:               # plik sie skurczyl (rotacja/nadpisanie)
                poz[f] = rozmiar; zmiana = True; continue
            if rozmiar == start:
                continue
            try:
                with open(f, "rb") as fh:
                    fh.seek(start)
                    surowe = fh.read(rozmiar - start)
            except OSError:
                continue
            # ostatnia linia moze byc niedomknieta — zostawiamy ja na nastepny obrot
            czesci = surowe.split(b"\n")
            ogon = czesci.pop()
            przesuniecie = rozmiar - len(ogon)
            for linia in czesci:
                if not linia.strip():
                    continue
                tekst = tekst_z_linii(linia.decode("utf-8", "replace"))
                if tekst:
                    wyslij(kto_z_sciezki(f), tekst)
            poz[f] = przesuniecie
            zmiana = True
        if zmiana:
            zapisz_pozycje(poz)
        time.sleep(ODSTEP)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
