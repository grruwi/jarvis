#!/usr/bin/env python3
"""kibelek-echo.py — hook `Stop`: wrzuca MOJĄ ostatnią turę na kibelek.

Po co: feed kibelka nosił dotąd tylko jedną stronę rozmowy (wejście grruwiego),
bo odpowiedź leci do CLI, a nie do busa. Kto patrzy w `kibelek-tui.py` (Karol
przez SSH) widział człowieka mówiącego w pustkę. To domyka pętlę.

Adresat = `log`: dispatcher zapisuje wpis do feedu i NIC nie wstrzykuje dalej
(dispatcher.py:289) — bez tego echo wróciłoby do mojego promptu i kręciło się
w kółko.

⚠️ WYŚCIG Z ZAPISEM (znaleziony 2026-08-12, objaw: „wysyła co drugą, z lagiem"):
hook startuje w tej samej sekundzie, w której finalna odpowiedź trafia do jsonl.
Czytanie od razu łapało tekst SPRZED ostatniego tool calla, a dedup po uuid
kazał potem milczeć — więc tura ginęła. Stąd `poczekaj_na_zapis()` i zbieranie
CAŁEJ tury zamiast jednej wiadomości.

Ścieżki sesji NIE szukamy — `transcript_path` przychodzi na stdin od harnessu,
więc katalog (`-home-grruwi`, Cowork, `ccr` Gieni) jest bez znaczenia.

Użycie (w settings.json):
    kibelek-echo.py --kto klodzio
    kibelek-echo.py --kto gienia
"""
import os, sys, json, time, subprocess

KIB_SEND = os.path.expanduser("~/Dokumenty/jarvis/kib-send.py")
STAN     = os.path.expanduser("~/.config/jarvis/kibelek-echo-stan.json")
LIMIT    = 4000          # znaków; feed rotuje po 1 MB, więc ucinamy tylko monstra
OGON     = 512 * 1024    # ile bajtów transkryptu czytamy od końca za pierwszym razem


def kto_pisze():
    a = sys.argv[1:]
    return a[a.index("--kto") + 1] if "--kto" in a and len(a) > a.index("--kto") + 1 else "klodzio"


def poczekaj_na_zapis(sciezka, limit_s=4.0, krok=0.2):
    """Czeka, aż plik przestanie rosnąć. Bez tego łapiemy turę w połowie zapisu."""
    poprzedni, stabilne = -1, 0
    koniec = time.time() + limit_s
    while time.time() < koniec:
        try:
            teraz = os.path.getsize(sciezka)
        except OSError:
            return
        if teraz == poprzedni:
            stabilne += 1
            if stabilne >= 2:      # dwa odczyty bez zmiany = zapis dobiegł końca
                return
        else:
            stabilne = 0
        poprzedni = teraz
        time.sleep(krok)


def ogon_linii(sciezka, ile):
    """Czyta końcówkę pliku. Transkrypt długiej sesji waży dziesiątki MB, a hook
    chodzi po KAŻDEJ turze — wczytywanie całości byłoby podatkiem na nic."""
    with open(sciezka, "rb") as f:
        f.seek(0, 2)
        start = max(0, f.tell() - ile)
        f.seek(start)
        dane = f.read()
    if start > 0:
        dane = dane.split(b"\n", 1)[-1]   # pierwsza linia bloku bywa ucięta w pół
    return dane.decode("utf-8", "replace").splitlines()


def _prompt_uzytkownika(d):
    """Odróżnia prawdziwą wiadomość grruwiego od tool_result — oba mają type=user."""
    if d.get("type") != "user" or d.get("isSidechain"):
        return False
    tresc = d.get("message", {}).get("content", "")
    if isinstance(tresc, str):
        return bool(tresc.strip())
    return not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in tresc)


def ostatnia_tura(sciezka):
    """Zwraca (uuid, tekst) CAŁEJ mojej ostatniej tury — wszystkie bloki tekstu od
    ostatniego promptu grruwiego, sklejone. Jedna wiadomość nie wystarcza: tura z
    tool callami ma tekst i przed, i po nich, a on widzi na czacie jedno i drugie."""
    for ile in (OGON, 8 * OGON):
        wpisy = []
        for linia in ogon_linii(sciezka, ile):
            try:
                wpisy.append(json.loads(linia))
            except Exception:
                continue
        # od końca w tył, aż do promptu grruwiego
        kawalki, ostatni_uuid = [], ""
        for d in reversed(wpisy):
            if _prompt_uzytkownika(d):
                break
            if d.get("type") != "assistant" or d.get("isSidechain"):
                continue
            teksty = [c.get("text", "") for c in d.get("message", {}).get("content", [])
                      if isinstance(c, dict) and c.get("type") == "text"]
            tekst = "\n".join(t for t in teksty if t.strip()).strip()
            if tekst:
                kawalki.append(tekst)
                if not ostatni_uuid:
                    ostatni_uuid = d.get("uuid", "")
        if kawalki:
            return ostatni_uuid, "\n\n".join(reversed(kawalki))
    return None, None


def juz_bylo(sesja, uuid):
    """Stop chodzi też przy /clear, resume i compact — bez tego Karol dostawałby
    tę samą odpowiedź po kilka razy."""
    try:
        with open(STAN) as f:
            stan = json.load(f)
    except Exception:
        stan = {}
    if stan.get(sesja) == uuid:
        return True
    stan[sesja] = uuid
    if len(stan) > 20:                     # stare sesje wypadają, plik nie puchnie
        stan = dict(list(stan.items())[-20:])
    try:
        os.makedirs(os.path.dirname(STAN), exist_ok=True)
        with open(STAN, "w") as f:
            json.dump(stan, f)
    except Exception:
        pass
    return False


def main():
    try:
        wejscie = json.load(sys.stdin)
    except Exception:
        return
    sciezka = wejscie.get("transcript_path", "")
    if not sciezka or not os.path.exists(sciezka):
        return

    poczekaj_na_zapis(sciezka)

    uuid, tekst = ostatnia_tura(sciezka)
    if not tekst:
        return
    if juz_bylo(wejscie.get("session_id", "?"), uuid):
        return

    if len(tekst) > LIMIT:
        tekst = tekst[:LIMIT] + " […]"
    if tekst.startswith("-"):
        tekst = " " + tekst                # kib-send wziąłby myślnik za flagę

    try:
        subprocess.run([sys.executable, KIB_SEND, "--from", kto_pisze(), "--to", "log", tekst],
                       timeout=5, capture_output=True)
    except Exception as e:
        print(f"[kibelek-echo] kibelek nie odebrał: {e!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
