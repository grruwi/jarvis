#!/usr/bin/env python3
"""kibelek-tui.py — OCZKO na kibelek w terminalu (curses). Podgląd + pisanie.

Górny panel = przelot wiadomości na żywo (kolor po adresacie). Dolna linia = pisanie.
Bez prefiksu wiadomość ZOSTAJE na kibelku — nikt po nią nie skacze. Adresata
wybierasz świadomie prefiksem: @klodzio / @voice / @gienia na początku.
@claude dziala dalej jako alias na klodzia.
Wyjście: Esc albo Ctrl-C.

Uruchom w systemowym terminalu:  python3 ~/Dokumenty/jarvis/kibelek-tui.py
"""
import os, re, json, socket, curses, textwrap, locale
from collections import deque

locale.setlocale(locale.LC_ALL, "")   # curses musi znać UTF-8 PRZED initem, inaczej ramki→krzaki

CFG  = os.path.expanduser("~/.config/jarvis")
FEED = os.path.join(CFG, "kibelek-feed.jsonl")
SOCK = os.path.join(CFG, "kibelek.sock")

# pary kolorów curses (nr pary)
GREEN, CYAN, MAGENTA, WHITE, RED, GRAY, YELLOW, BLUE = 1, 2, 3, 4, 5, 6, 7, 8
ORANGE = 9   # gemini — druga rodzina modeli ma być odróżnialna od gieni

# Rotacja kolorów treści: KAŻDA kolejna wiadomość dostaje inną barwę. Kolor po
# autorze nie wystarczał — dwie wiadomości z rzędu od tej samej osoby zlewały się
# w ścianę tak samo jak biel. Nick zostaje w kolorze postaci (niesie "kto"),
# treść rotuje (niesie "gdzie kończy się jedna, a zaczyna druga").
ROT = [10, 11, 12, 13, 14, 15, 16, 17]
ROT_256 = [81, 213, 156, 222, 209, 147, 158, 180]
ROT_8 = [curses.COLOR_CYAN, curses.COLOR_MAGENTA, curses.COLOR_GREEN,
         curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_BLUE,
         curses.COLOR_CYAN, curses.COLOR_WHITE]
CP = {"voice": GREEN, "klodzio": CYAN, "claude": CYAN, "gienia": MAGENTA, "log": WHITE, "err": RED, "meta": GRAY}
# Kolejnosc ma znaczenie: dopasowanie prefiksu leci po liscie, a "klodzio"
# musi wyprzedzic alias "claude", zeby to on byl nazwa wlasciwa.
TARGETS = ["klodzio", "claude", "voice", "gienia"]

# kolor po AUTORZE / adresacie (rozróżnia kto z kim gada)
PEOPLE = {"grruwi": YELLOW, "klodzio": CYAN, "claude": CYAN, "voice": GREEN, "gienia": MAGENTA,
          "gemini": ORANGE, "gamon": ORANGE, "dispatcher": BLUE, "pukacz": BLUE,
          "tui": RED}

# Kolory da się nadpisać BEZ dotykania kodu — w tym samym pliku, w którym siedzą
# tożsamości. Nazwy po polsku, żeby dało się to edytować bez zaglądania tutaj.
NAZWY_KOLOROW = {"zolty": YELLOW, "żółty": YELLOW, "cyjan": CYAN, "zielony": GREEN,
                 "magenta": MAGENTA, "pomaranczowy": ORANGE, "pomarańczowy": ORANGE,
                 "niebieski": BLUE, "czerwony": RED, "bialy": WHITE, "biały": WHITE,
                 "szary": GRAY}
# Jasne warianty = ten sam kolor + pogrubienie; terminal rysuje je jaśniej.
for _n, _c in list(NAZWY_KOLOROW.items()):
    NAZWY_KOLOROW["jasny " + _n] = NAZWY_KOLOROW["jasno" + _n] = _c + 100

def _kto_patrzy():
    try:
        from kibelek_kto import kto
        return kto()
    except Exception:
        return "grruwi"

WIDZ        = _kto_patrzy()
PLIK_OSOB   = os.path.expanduser("~/.config/jarvis/kibelek-osoby.json")
PLIK_WIDOKU = os.path.expanduser(f"~/.config/jarvis/kibelek-widok-{WIDZ}.json")
# Bazowa barwa treści. Fragmenty pokolorowane przez markdown (kod, cytaty) i tak
# biorą swoje — to ustawienie dotyczy tylko zwykłego tekstu.
TRYBY_TRESCI = ["rotacja", "nadawca", "bialy"]
OPIS_TRYBU   = {"rotacja": "rotacja — sąsiednie wiadomości różnymi barwami",
                "nadawca": "nadawca — treść w barwie osoby",
                "bialy":   "biała — kolor tylko tam, gdzie robi go formatowanie"}
USTAWIENIA  = {"tryb_tresci": "rotacja"}

def _wczytaj_widok():
    """Jak TEN człowiek chce widzieć kanał. Karol i grruwi patrzą na ten sam feed
    z dwóch maszyn — barwy i miganie to gust widza, nie własność wiadomości, więc
    każdy ma swój plik. Wspólny `kibelek-osoby.json` daje tylko punkt wyjścia."""
    kolory, tresci, ust = {}, {}, {}
    for p in (PLIK_OSOB, PLIK_WIDOKU):        # widz nadpisuje wspólne domyślne
        try:
            with open(p) as f:
                d = json.load(f)
            kolory.update(d.get("kolory", {}))
            tresci.update(d.get("kolory_tresci", {}))
            ust.update(d.get("ustawienia", {}))
        except Exception:
            pass
    # stary zapis (przełącznik tak/nie) czytamy dalej, żeby nikomu nie zniknęło ustawienie
    if "miganie" in ust and "tryb_tresci" not in ust:
        ust["tryb_tresci"] = "rotacja" if ust["miganie"] else "nadawca"
    na_pary = lambda m: {k.lower(): NAZWY_KOLOROW[str(v).lower()]
                         for k, v in m.items() if str(v).lower() in NAZWY_KOLOROW}
    return na_pary(kolory), na_pary(tresci), ust

# Barwa NAZWY i barwa JEJ TEKSTU to dwie różne rzeczy — pierwsza ma być stała, żeby
# oko łapało nadawcę, druga bywa kwestią czytelności na danym tle.
PEOPLE_TRESC = {}

def who_cp_tresc(name):
    return PEOPLE_TRESC.get(str(name).lower(), who_cp(name))

_k, _t, _u = _wczytaj_widok()
PEOPLE.update(_k)
PEOPLE_TRESC.update(_t)
USTAWIENIA.update(_u)

PALETA = ["zolty", "cyjan", "zielony", "magenta", "pomaranczowy",
          "niebieski", "czerwony", "bialy", "szary"]
PALETA += ["jasny " + p for p in PALETA]

def panel_ustawien(stdscr):
    """Nakładka F2: kto ma jaki kolor. Zapisuje do kibelek-osoby.json, czyli tam,
    gdzie i tak mieszkają tożsamości — plik zostaje źródłem prawdy, panel jest
    tylko wygodniejszym sposobem, żeby go zmienić."""
    # czytamy WSPÓLNE domyślne, ale zapisujemy WYŁĄCZNIE do pliku tego widza
    kolory, tresci = {}, {}
    for p in (PLIK_OSOB, PLIK_WIDOKU):
        try:
            with open(p) as f:
                d = json.load(f)
            kolory.update(d.get("kolory", {}))
            tresci.update(d.get("kolory_tresci", {}))
        except Exception:
            pass
    ustaw = dict(USTAWIENIA)
    osoby = sorted(set(list(kolory) + ["grruwi", "klodzio", "karol", "gienia", "voice"]))
    MIGANIE = len(osoby)                 # ostatnia pozycja listy = przełącznik
    wybor, kolumna = 0, 0                # kolumna: 0 = nazwa, 1 = tekst tej osoby

    def barwa(nazwa_koloru):
        cp = NAZWY_KOLOROW.get(str(nazwa_koloru).lower(), WHITE)
        return curses.color_pair(cp % BOLD) | (curses.A_BOLD if cp >= BOLD else 0)

    while True:
        H, W = stdscr.getmaxyx()
        stdscr.erase()
        stdscr.addnstr(1, 2, f" USTAWIENIA — widok: {WIDZ} ", W - 3, curses.A_BOLD)
        stdscr.addnstr(2, 2, "↑↓ osoba   Tab = nazwa/tekst   ←→ kolor   Enter = zapisz   Esc = anuluj",
                       W - 3, curses.color_pair(GRAY))
        stdscr.addnstr(3, 18, "NAZWA", 8, curses.A_BOLD if kolumna == 0 else 0)
        stdscr.addnstr(3, 42, "TEKST", 8, curses.A_BOLD if kolumna == 1 else 0)
        for i, osoba in enumerate(osoby):
            y = 4 + i
            if y >= H - 2:
                break
            k_naz = kolory.get(osoba, "bialy")
            k_trs = tresci.get(osoba, k_naz)
            stdscr.addnstr(y, 2, ("▶ " if i == wybor else "  ") + osoba.ljust(12),
                           W - 3, curses.A_REVERSE if i == wybor else 0)
            # ⚠️ Próbka NIGDY nie dostaje A_REVERSE — odwrócenie zamienia barwę
            # próbki na barwę tła i pokazywało coś innego, niż jest ustawione.
            # Zaznaczenie niesie marker i podświetlona NAZWA koloru obok.
            for kol, (x, nazwa_k) in enumerate(((18, k_naz), (42, k_trs))):
                akt = (i == wybor and kolumna == kol)
                stdscr.addnstr(y, x, "▸" if akt else " ", 1, curses.A_BOLD)
                stdscr.addnstr(y, x + 2, "███", 3, barwa(nazwa_k))
                stdscr.addnstr(y, x + 6, nazwa_k.ljust(16)[:16], max(1, W - x - 7),
                               curses.A_REVERSE if akt else curses.color_pair(GRAY))
        y = min(4 + MIGANIE, H - 2)
        stdscr.addnstr(y, 2, ("▶ " if wybor == MIGANIE else "  ") + "kolor treści",
                       W - 3, curses.A_REVERSE if wybor == MIGANIE else 0)
        stdscr.addnstr(y, 18, OPIS_TRYBU.get(ustaw.get("tryb_tresci", "rotacja"), "?"),
                       max(1, W - 19), curses.color_pair(GRAY))
        stdscr.refresh()

        try:
            ch = stdscr.get_wch()
        except Exception:
            continue
        if ch in ("\x1b", 27):
            return
        if ch in ("\n", "\r"):
            try:
                with open(PLIK_WIDOKU) as f:
                    dane = json.load(f)
            except Exception:
                dane = {}
            # WŁASNY kolor nazwy idzie do WSPÓLNEGO pliku — jak na Twitchu: każdy
            # decyduje, jak jego nick wygląda u wszystkich. Cudze kolory zostają
            # prywatne, bo przypisywanie barw obcym to robota każdego u siebie.
            moj = kolory.pop(WIDZ, None)
            if moj:
                try:
                    with open(PLIK_OSOB) as f:
                        wspolne = json.load(f)
                except Exception:
                    wspolne = {}
                wspolne.setdefault("kolory", {})[WIDZ] = moj
                try:
                    with open(PLIK_OSOB, "w") as f:
                        json.dump(wspolne, f, ensure_ascii=False, indent=2)
                except Exception:
                    kolory[WIDZ] = moj      # nie udało się globalnie — zostaw u siebie

            dane["_opis"] = f"Widok kibelka dla: {WIDZ}. Prywatne — nie widzą tego inni."
            dane["kolory"], dane["kolory_tresci"], dane["ustawienia"] = kolory, tresci, ustaw
            try:
                os.makedirs(os.path.dirname(PLIK_WIDOKU), exist_ok=True)
                with open(PLIK_WIDOKU, "w") as f:
                    json.dump(dane, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            k, t, u = _wczytaj_widok()        # widoczne od razu, bez restartu
            PEOPLE.update(k); PEOPLE_TRESC.update(t); USTAWIENIA.update(u)
            return
        if ch == curses.KEY_UP:
            wybor = (wybor - 1) % (MIGANIE + 1)
        elif ch == curses.KEY_DOWN:
            wybor = (wybor + 1) % (MIGANIE + 1)
        elif ch == "\t":
            kolumna = 1 - kolumna
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
            if wybor == MIGANIE:
                i = TRYBY_TRESCI.index(ustaw.get("tryb_tresci", "rotacja")) \
                    if ustaw.get("tryb_tresci", "rotacja") in TRYBY_TRESCI else 0
                ustaw["tryb_tresci"] = TRYBY_TRESCI[(i + (1 if ch == curses.KEY_RIGHT else -1))
                                                    % len(TRYBY_TRESCI)]
                ustaw.pop("miganie", None)          # stary klucz już nie rządzi
            else:
                osoba = osoby[wybor]
                mapa = kolory if kolumna == 0 else tresci
                teraz = mapa.get(osoba, kolory.get(osoba, "bialy"))
                i = PALETA.index(teraz) if teraz in PALETA else 0
                mapa[osoba] = PALETA[(i + (1 if ch == curses.KEY_RIGHT else -1)) % len(PALETA)]


def adresat(m):
    """`to` bywa listą (rozgłos) — bierzemy pierwszego."""
    t = m.get("to", "?")
    return t[0] if isinstance(t, list) else str(t)

def rozmowa(m):
    """Para (kto, do kogo) — zmiana tej pary oznacza NOWĄ rozmowę, nie nową linijkę."""
    return (str(m.get("from", "?")), adresat(m))

def who_cp(name):
    return PEOPLE.get(str(name).lower(), WHITE)
# kolor po TYPIE wiadomości
def type_cp(t, is_err):
    if is_err: return RED
    return {"say": BLUE, "task": YELLOW, "log": GRAY}.get(str(t).lower(), GRAY)

BOLD    = 100   # doklejane do numeru pary kolorów = "to samo, ale pogrubione"
KURSYWA = 200   # jw. — par jest kilkanaście, więc setki nie zderzą się z kolorem

def markdown_spans(tekst, cp):
    """Formatowanie WEWNĄTRZ wiersza: **grube**, *kursywa*, `kod`."""
    out = []
    for kawalek in re.split(r"(\*\*[^*\n]+\*\*|\*[^*\n]+\*|_[^_\n]+_|`[^`\n]+`)", tekst):
        if not kawalek:
            continue
        if kawalek.startswith("**") and kawalek.endswith("**") and len(kawalek) > 4:
            out.append((kawalek[2:-2], cp + BOLD))
        elif kawalek.startswith("`") and kawalek.endswith("`") and len(kawalek) > 2:
            out.append((kawalek[1:-1], CYAN))
        elif (kawalek[0] in "*_" and kawalek[-1] == kawalek[0] and len(kawalek) > 2):
            out.append((kawalek[1:-1], cp + KURSYWA))
        else:
            out.append((kawalek, cp))
    return out or [(tekst, cp)]


def markdown_wiersze(tekst, cp, width):
    """Formatowanie CAŁYCH WIERSZY: bloki kodu, cytaty, listy, nagłówki.

    Musi być osobno od `markdown_spans`, bo te konstrukcje obejmują wiersz
    w całości — sam podział na spany ich nie wyłapie. Zwraca gotowe wiersze."""
    wiersze, w_kodzie = [], False
    for linia in tekst.split("\n"):
        goła = linia.strip()

        if goła.startswith("```"):              # znacznik bloku sam się nie pokazuje
            w_kodzie = not w_kodzie
            continue
        if w_kodzie:
            wiersze.extend(wrap_spans([("  │ " + linia.rstrip(), CYAN)], width))
            continue
        if not goła:
            wiersze.append([])
            continue

        naglowek = re.match(r"^(#{1,6})\s+(.*)$", goła)
        if naglowek:
            wiersze.extend(wrap_spans([(naglowek.group(2), cp + BOLD)], width))
            continue

        if goła.startswith(">"):                # cytat — kreska i przygaszenie
            wiersze.extend(wrap_spans([("  ▏ ", GRAY)] +
                                      markdown_spans(goła.lstrip("> ").strip(), GRAY), width))
            continue

        punkt = re.match(r"^[-*+]\s+(.*)$", goła)
        if punkt:
            wiersze.extend(wrap_spans([("  • ", cp)] + markdown_spans(punkt.group(1), cp), width))
            continue

        numer = re.match(r"^(\d{1,2})[.)]\s+(.*)$", goła)
        if numer:
            wiersze.extend(wrap_spans([(f"  {numer.group(1)}. ", cp)] +
                                      markdown_spans(numer.group(2), cp), width))
            continue

        wiersze.extend(wrap_spans(markdown_spans(goła, cp), width))
    return wiersze

def wrap_spans(spans, width):
    """Zawija listę (tekst, kolor) do szerokości, zachowując kolory. Zwraca listę wierszy."""
    lines = [[]]; x = 0
    for text, cp in spans:
        for word in re.split(r"(\s+)", text):
            if not word: continue
            wl = len(word)
            if x + wl > width and x > 0:            # łamanie na granicy słowa
                lines.append([]); x = 0
                if not word.strip(): continue       # nie zaczynaj wiersza spacją
            while wl > width:                       # słowo dłuższe niż wiersz — twarde cięcie
                take = width - x
                lines[-1].append((word[:take], cp)); word = word[take:]; wl = len(word)
                lines.append([]); x = 0
            lines[-1].append((word, cp)); x += wl
    return lines

def send(target, text):
    # Kto pisze — po adresie, z ktorego przyszlo SSH. Karol siedzi na TYM SAMYM
    # koncie co grruwi, wiec bez tego kazdy podpisywalby sie "grruwi".
    try:
        from kibelek_kto import kto
        nadawca = kto()
    except Exception:
        nadawca = "grruwi"
    msg = {"from": nadawca, "to": target, "type": "task",
           "payload": text, "lang": "pl", "engine": "f5"}
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(SOCK); s.sendall(json.dumps(msg).encode()); s.recv(4096); s.close()
        return None
    except Exception as e:
        return str(e)

def rows_from_msgs(msgs, width):
    """Zamienia wiadomości na wiersze kolorowanych spanów (czas/autor/adresat/typ/treść osobno)."""
    out = []  # każdy element = wiersz = lista (tekst, kolor)
    for nr, m in enumerate(msgs):
        # Kreska tylko tam, gdzie zmienia się ROZMOWA (nadawca albo adresat).
        # Seria wiadomości od jednej osoby do jednej osoby to jedna wypowiedź
        # pocięta na kawałki — kreska w środku niej dzieliłaby zdanie, nie rozmowę.
        # Nagłówek i kreska należą się NOWEJ rozmowie. Seria wiadomości od tej samej
        # osoby do tej samej osoby to jedna wypowiedź pocięta na kawałki — powtarzanie
        # "kto → do kogo" przy każdym kawałku zaśmiecało ekran bardziej niż treść.
        nowa = nr == 0 or rozmowa(msgs[nr - 1]) != rozmowa(m)
        if nowa and nr > 0:
            out.append([("─" * max(1, width - 1), GRAY)])
        frm = str(m.get("from", "?"))
        tgt = m.get("to", "?"); tgt = tgt[0] if isinstance(tgt, list) else str(tgt)
        typ = str(m.get("type", "?"))
        is_err = str(m.get("resp", "")).startswith("err") or typ.lower() == "err"
        spans = [
            (m.get("t", "") + " ", GRAY),                 # czas — przygaszony
            # modulo, bo kolor z pliku może JUŻ nieść pogrubienie ("jasny zielony")
            # — bez tego flagi zsumowałyby się w kursywę.
            (frm,                who_cp(frm) % BOLD + BOLD),   # autor — ma rzucać się w oczy
            (" → ",              GRAY),
            (tgt,                who_cp(tgt) % BOLD + BOLD),   # adresat — tak samo
            # [typ] pokazujemy TYLKO przy błędzie. Reszta rodzajów (say/task/ask)
            # jest martwa — żadna trasa dispatchera ich nie czyta, więc na ekranie
            # był z nich sam szum.
            (f" [{typ}]" if is_err else ":", type_cp(typ, is_err)),
        ]
        # treść bierze kolejny kolor z rotacji — sąsiednie wiadomości NIGDY
        # nie mają tej samej barwy, więc widać gdzie kończy się jedna.
        tresc = str(m.get("text", ""))
        # Miganie = treść rotuje barwami (sąsiednie wypowiedzi się nie zlewają).
        # Wyłączone = treść w barwie nadawcy. Przypisany kolor osoby i tak zostaje
        # w nagłówku, bo tam niesie tożsamość niezależnie od tego ustawienia.
        tryb = USTAWIENIA.get("tryb_tresci", "rotacja")
        if is_err:
            cp_tresci = RED
        elif tryb == "bialy":
            cp_tresci = WHITE
        elif tryb == "nadawca":
            cp_tresci = who_cp_tresc(frm)
        else:
            cp_tresci = ROT[nr % len(ROT)]
        # Nagłówek ZAWSZE osobno, treść ZAWSZE pod spodem. Wcześniej krótkie
        # wiadomości zostawały przy nagłówku dla oszczędności miejsca — ale przez to
        # dyktowane głosem (długie, bez markdownu) wyglądały inaczej niż reszta.
        if nowa:
            out.extend(wrap_spans(spans, width))
        out.extend(markdown_wiersze(tresc, cp_tresci, width))
        resp = str(m.get("resp", ""))
        if resp and resp != "log":
            out.extend(wrap_spans([("    ↳ " + resp, RED if is_err else GRAY)], width))
        # Bez pustych wierszy — granicę wiadomości niesie teraz POGRUBIONY nagłówek
        # (kto → do kogo). Odstępy byly proteza na czas, gdy nazwy sie zlewaly z trescia.
    return out

# --- skok o całe słowo (Ctrl+←/→), semantyka jak w readline/bashu ---
# Kody klawiszy zależą od terminfo, więc oprócz typowych wartości liczbowych
# rozpoznajemy je po NAZWIE (kLFT5 = Ctrl+←, kLFT3 = Alt+←). keyname bywa
# rzucane wyjątkiem dla nieznanych kodów, stąd try.
CTRL_LEFT  = {545, 546, 543}    # Ctrl+←, Ctrl+Shift+←, Alt+←
CTRL_RIGHT = {560, 561, 558}    # Ctrl+→, Ctrl+Shift+→, Alt+→

def _nazwa_klawisza(ch):
    if not isinstance(ch, int):
        return ""
    try:
        return curses.keyname(ch).decode("ascii", "replace")
    except Exception:
        return ""

def skok_w_lewo(s, i):
    while i > 0 and not s[i-1].isalnum(): i -= 1      # przeskocz spacje/znaki
    while i > 0 and s[i-1].isalnum():     i -= 1      # przeskocz samo słowo
    return i

def skok_w_prawo(s, i):
    n = len(s)
    while i < n and not s[i].isalnum(): i += 1
    while i < n and s[i].isalnum():     i += 1
    return i


def main(stdscr):
    curses.curs_set(1); curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN,   -1)
    curses.init_pair(2, curses.COLOR_CYAN,    -1)
    curses.init_pair(3, curses.COLOR_MAGENTA, -1)
    curses.init_pair(4, curses.COLOR_WHITE,   -1)
    curses.init_pair(5, curses.COLOR_RED,     -1)
    curses.init_pair(6, 8,                    -1)  # szary (bright black)
    curses.init_pair(7, curses.COLOR_YELLOW,  -1)
    curses.init_pair(8, curses.COLOR_BLUE,    -1)
    # pomarańcz istnieje tylko w palecie 256; na uboższym terminalu spada na żółty
    curses.init_pair(9, 208 if curses.COLORS >= 256 else curses.COLOR_YELLOW, -1)
    bogata = curses.COLORS >= 256
    for i, para in enumerate(ROT):
        curses.init_pair(para, (ROT_256 if bogata else ROT_8)[i], -1)
    stdscr.timeout(250)
    try:   # tylko rolka myszy (nie klik) — zachowuje zaznaczanie tekstu
        curses.mousemask(curses.BUTTON4_PRESSED | getattr(curses, "BUTTON5_PRESSED", 0))
    except Exception:
        pass

    msgs = deque(maxlen=500)
    pos = 0
    buf = ""
    cur = 0            # pozycja kursora w buf
    history = []       # wysłane wpisy (nawigacja ↑/↓ jak w shellu)
    hidx = None        # indeks w historii (None = edycja bieżącego wpisu)
    draft = ""         # zachowany bieżący wpis przy wejściu w historię
    scroll = 0         # ile wierszy od dołu odjęte (0 = przyklejony do dołu)

    while True:
        # --- dociągnij nowe wiadomości z feedu (tail; koszt ~0 gdy cisza) ---
        try:
            if os.path.exists(FEED):
                sz = os.path.getsize(FEED)
                if sz < pos: pos = 0
                if sz > pos:
                    with open(FEED) as f:
                        f.seek(pos)
                        for ln in f:
                            try: msgs.append(json.loads(ln))
                            except Exception: pass
                        pos = f.tell()
        except Exception:
            pass

        # --- rysowanie ---
        H, W = stdscr.getmaxyx()
        stdscr.erase()

        # Box wejścia ROŚNIE o kolejne wiersze i zawija na krawędzi — wcześniej
        # była jedna linia, a wszystko poza szerokość okna po prostu znikało
        # z widoku (tekst istniał w buforze, tylko go nie było widać).
        # Zawijanie jest po ZNAKACH, nie po słowach: kursor musi mapować się 1:1
        # na pozycję w buforze, a przy łamaniu po słowach ta arytmetyka kłamie.
        iw = max(1, W - 1)
        ptxt = "> " + buf
        ilines = [ptxt[i:i + iw] for i in range(0, len(ptxt), iw)] or [""]
        imax = max(1, (H - 2) // 2)            # box nie zjada więcej niż połowy ekranu
        ioff = max(0, len(ilines) - imax)      # dłuższy wpis → pokazuj OGON (tam jest kursor)
        ilines = ilines[ioff:]
        input_h = len(ilines)
        sep_y = max(0, H - 1 - input_h)
        feed_h = max(1, sep_y)

        rows = rows_from_msgs(msgs, W - 1)
        maxscroll = max(0, len(rows) - feed_h)
        if scroll > maxscroll: scroll = maxscroll     # clamp gdy feed urósł/zmalał
        end = len(rows) - scroll
        for y, line in enumerate(rows[max(0, end - feed_h):end]):
            x = 0
            for txt, cp in line:
                if x >= W - 1: break
                atr = curses.color_pair(cp % BOLD)
                if cp >= KURSYWA:
                    # A_ITALIC bywa nieobsługiwane przez starsze ncurses — wtedy
                    # podkreślenie, byle kursywa nie zniknęła bez śladu.
                    atr |= getattr(curses, "A_ITALIC", curses.A_UNDERLINE)
                elif cp >= BOLD:
                    atr |= curses.A_BOLD
                try: stdscr.addnstr(y, x, txt, W - 1 - x, atr)
                except curses.error: pass
                x += len(txt)
        # separator z podpowiedzią (+ znacznik gdy odjechany od dołu)
        tag = f" [scroll +{scroll}]" if scroll else ""
        hint = " kibelek - bez @ zostaje tutaj | @klodzio @voice @gienia | F2=kolory | Esc=wyjscie" + tag + " "
        try: stdscr.addnstr(sep_y, 0, hint.ljust(W - 1, "-"), W - 1, curses.color_pair(6))
        except curses.error: pass
        # wiersze wejścia
        for i, ln in enumerate(ilines):
            try: stdscr.addnstr(sep_y + 1 + i, 0, ln, W - 1, curses.A_BOLD)
            except curses.error: pass
        # kursor: pozycja w ZAWINIĘTYM tekście, pomniejszona o urwane wiersze
        cpos = 2 + cur
        crow = min(max(0, cpos // iw - ioff), input_h - 1)
        try: stdscr.move(sep_y + 1 + crow, min(cpos % iw, W - 1))
        except curses.error: pass
        stdscr.refresh()

        # --- wejście (get_wch: czyta CAŁY znak, nie bajt — inaczej polskie litery→krzaki) ---
        try:
            ch = stdscr.get_wch()
        except curses.error:
            continue                          # timeout, brak wejścia
        if ch in ("\x1b", 27):                # Esc
            break
        elif ch == curses.KEY_F2:             # panel ustawień (kolory osób)
            panel_ustawien(stdscr)
        elif ch == curses.KEY_MOUSE:          # rolka myszy = przewijanie feedu
            try: _, _, _, _, bstate = curses.getmouse()
            except curses.error: bstate = 0
            dn = getattr(curses, "BUTTON5_PRESSED", 0)
            if   bstate & curses.BUTTON4_PRESSED: scroll += 3
            elif dn and bstate & dn:              scroll = max(0, scroll - 3)
        elif ch == curses.KEY_UP:             # historia wstecz (jak w shellu)
            if history:
                if hidx is None: draft = buf; hidx = len(history) - 1
                else:            hidx = max(0, hidx - 1)
                buf = history[hidx]; cur = len(buf)
        elif ch == curses.KEY_DOWN:           # historia w przód
            if hidx is not None:
                hidx += 1
                if hidx >= len(history): hidx = None; buf = draft
                else:                    buf = history[hidx]
                cur = len(buf)
        elif ch in CTRL_LEFT or _nazwa_klawisza(ch) in ("kLFT5", "kLFT3"):
            cur = skok_w_lewo(buf, cur)               # Ctrl+← = słowo wstecz
        elif ch in CTRL_RIGHT or _nazwa_klawisza(ch) in ("kRIT5", "kRIT3"):
            cur = skok_w_prawo(buf, cur)              # Ctrl+→ = słowo w przód
        elif ch == curses.KEY_LEFT:  cur = max(0, cur - 1)
        elif ch == curses.KEY_RIGHT: cur = min(len(buf), cur + 1)
        elif ch == curses.KEY_HOME:  cur = 0
        elif ch == curses.KEY_END:   cur = len(buf)
        elif ch in ("\x08", "\x17"):          # Ctrl+Backspace / Ctrl+W = zjedz słowo
            # Zwykły Backspace to \x7f (terminfo kbs), więc \x08 (Ctrl+H) jest
            # wolne i tam siada Ctrl+Backspace. Ctrl+W dołożone, bo działa
            # wszędzie — nawet gdy terminal nie odróżnia Ctrl+Backspace.
            if cur > 0:
                i = skok_w_lewo(buf, cur)
                buf = buf[:i] + buf[cur:]; cur = i
        elif ch in (curses.KEY_BACKSPACE, "\x7f"):
            if cur > 0: buf = buf[:cur-1] + buf[cur:]; cur -= 1
        elif _nazwa_klawisza(ch) in ("kDC5", "kDC3"):   # Ctrl+Del = słowo w przód
            j = skok_w_prawo(buf, cur); buf = buf[:cur] + buf[j:]
        elif ch == curses.KEY_DC:             # Delete = usuń pod kursorem
            if cur < len(buf): buf = buf[:cur] + buf[cur+1:]
        elif ch in ("\n", "\r"):              # Enter — wyślij
            text = buf.strip()
            buf = ""; cur = 0; hidx = None; draft = ""; scroll = 0
            if not text: continue
            if not history or history[-1] != text: history.append(text)
            # Domyslnie NIKT nie skacze: wiadomosc ma wyladowac na kibelku i tam
            # zostac. Adresata wybiera sie SWIADOMIE przez @. (Dyktafon to inna
            # droga — whisper ustawia `to` jawnie i dalej celuje we mnie.)
            target = "log"
            for t in TARGETS:
                if text.lower().startswith("@" + t):
                    target = t; text = text[len(t) + 1:].strip(); break
            err = send(target, text)
            if err:
                msgs.append({"t": "--:--:--", "from": "tui", "to": target,
                             "type": "err", "text": text, "resp": "err " + err})
        elif isinstance(ch, str) and ch.isprintable():
            buf = buf[:cur] + ch + buf[cur:]; cur += 1   # wstaw w miejscu kursora

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
