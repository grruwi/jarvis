#!/usr/bin/env python3
"""dispatcher.py — KIBELEK + router Jarvisa (jedyny czytelnik, PUSH-only).

Kibelek = unix-socket `~/.config/jarvis/kibelek.sock`. NIE ma rosnącego pliku-spool
(to strukturalnie zabija token-hazard: wiadomość żyje tylko w locie po sokecie).
Dispatcher POSIADA socket => jest jedynym czytelnikiem z definicji. Event-driven:
accept() blokuje aż ktoś wrzuci wiadomość — zero pollingu.

Wiadomość (jedna linia JSON):
    {"from": nadawca, "to": adresat|[adresaci], "type": rodzaj, "payload": treść}

Adresaci (routing po `to`):
    voice   -> mówi przez tts-worker; głos wybierany po `from` (klodzio/gienia)
    klodzio -> wpycha tekst do mojego terminala (alias: claude) + Enter (tmux send-keys; fallback: inbox-plik)
    gienia  -> pyta Gemmę (LM Studio API); jej odpowiedź-JSON wraca do kibelka
    log     -> tylko zapis do stderr (podgląd)

`to` może być stringiem albo listą — rozgłasza do każdego (np. ["voice","klodzio"]).
"""
import os, sys, json, socket, subprocess, threading, time, shutil, urllib.request

CFG   = os.path.expanduser("~/.config/jarvis")
SOCK  = os.path.join(CFG, "kibelek.sock")
TTS   = os.path.join(CFG, "tts.sock")                 # gniazdo tts-workera
INBOX = os.path.join(CFG, "klodzio-inbox.log")         # fallback gdy kanał leży (NIKT nie tailuje)
FEED  = os.path.join(CFG, "kibelek-feed.jsonl")       # podgląd dla okienka (TYLKO ludzkie oczy)
os.makedirs(CFG, exist_ok=True)

# Gienia = ŻYWA sesja ccr Claude Code w Konsoli (widoczna, z pamięcią). Dispatcher wstrzykuje
# jej zadania celując po session-ID (qdbus sendText) — niezależnie od fokusu. Ona odpowiada we
# własnym CLI i sięga kibelka własnym shellem (kib-send). Adres bierze z adresownika (patrz niżej).
#
# ADRESOWNIK: term-<nazwa>.json, dwa rodzaje wpisu:
#   {"kind":"tmux","pane":"%7",...}                       <- jarvis-tmux.sh (preferowany)
#   {"svc":KONSOLE_DBUS_SERVICE,"ses":KONSOLE_DBUS_SESSION} <- term-register.sh (stary)
# To mapa "gdzie stoi CLI", NIE kanał — treść dalej płynie kibelkiem.
QDBUS = shutil.which("qdbus6") or shutil.which("qdbus")
TMUX  = shutil.which("tmux")

# Powłoki: gdy w panelu siedzi któraś z nich, CLI już wyszło, a wstrzyknięty tekst
# byłby WYKONANY jako polecenie. Wtedy kanał odmawia — cisza jest tańsza niż `rm`.
POWLOKI = {"bash", "sh", "zsh", "fish", "dash"}

# Zapasowy silnik głosu. DOMYŚLNY JĘZYK TO POLSKI — angielski trzeba wskazać jawnie
# (`"lang":"en"` w wiadomości), nie odwrotnie.
VOICEBOX_URL   = os.environ.get("VOICEBOX_URL", "http://127.0.0.1:17493")
VOICEBOX_GLOSY = {"klodzio": "fronczek", "claude": "fronczek", "gienia": "fronczek"}

def log(*a): print("[dispatcher]", *a, file=sys.stderr, flush=True)

def feed_tap(msg, resp):
    """Dopisuje przelot wiadomości do feedu dla okienka. Rotacja: >1MB -> ostatnie 500 linii."""
    try:
        line = json.dumps({
            "t":    time.strftime("%H:%M:%S"),
            "from": msg.get("from", "?"), "to": msg.get("to", "?"),
            "type": msg.get("type", "?"), "text": _text(msg), "resp": resp,
        }, ensure_ascii=False)
        with open(FEED, "a") as f:
            f.write(line + "\n")
        if os.path.getsize(FEED) > 1_000_000:
            with open(FEED) as f: tail = f.readlines()[-500:]
            with open(FEED, "w") as f: f.writelines(tail)
    except Exception as e:
        log("feed_tap błąd:", repr(e))


# ── trasa: GŁOS ─────────────────────────────────────────────────────────────
def route_voice(msg):
    """Mówi treść przez rezydentnego tts-workera. from=speaker (claude/gienia).
    Gdy workera F5 nie ma — spada na Voicebox (Fronczek), żeby cisza nie była
    domyślną odpowiedzią kanału."""
    if not os.path.exists(TTS):
        r = _voicebox_speak(_text(msg), msg.get("from", "klodzio"), msg.get("lang", "pl"))
        return r or "err tts-worker nie działa (brak tts.sock), Voicebox też nie odebrał"
    req = {
        "from":   msg.get("from", "klodzio"),
        "text":   _text(msg),
        "lang":   msg.get("lang", "pl"),
        "engine": msg.get("engine", "f5"),
    }
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.connect(TTS); c.sendall(json.dumps(req).encode())
        r = c.recv(4096).decode(); c.close()
        return f"voice -> {r}"
    except Exception as e:
        return f"err voice: {e}"


def _voicebox_speak(text, mowca, lang="pl"):
    """Zapasowy silnik głosu: natywny Voicebox na 17493. Zwraca opis albo None.

    `language` podajemy JAWNIE, bo binarka backendu czyta pominięte pole jako "en"
    i wypowiada polski tekst angielską fonetyką (łatka w źródłach jest, ale wejdzie
    dopiero po przebudowie sidecara). Nie czekamy na dźwięk — /speak oddaje sterowanie
    od razu, więc kibelek się nie zatyka na czas mówienia."""
    profil = VOICEBOX_GLOSY.get(mowca, VOICEBOX_GLOSY["klodzio"])
    try:
        req = urllib.request.Request(
            f"{VOICEBOX_URL}/speak",
            data=json.dumps({"text": text, "profile": profil,
                             "language": lang}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            gen = json.load(r)
        return f"voice -> voicebox/{profil} ({gen.get('id', '?')[:8]})"
    except Exception as e:
        log("voicebox nie odebrał:", repr(e))
        return None


# ── trasa: CLAUDE (wpychanie do terminala) ──────────────────────────────────
def route_klodzio(msg):
    """Wpycha tekst + Enter do mojego terminala. Kolejność: tmux (celowanie po pane_id,
    z weryfikacją kto tam siedzi) → Konsole-DBus (stary adresownik) → inbox-plik.

    ⛔ ydotool wypadł z łańcucha 2026-08-02 i nie wraca. Nie ma CELOWANIA — całe jego API
    to click/mousemove/type/key, wysyła przez uinput (udaje fizyczną klawiaturę), więc tekst
    ląduje tam, gdzie akurat jest fokus. Gdy aktywnym oknem był kibelek-tui, zrobił pętlę
    sprzężenia zwrotnego 10×/s. Kanał ma być NIEZALEŻNY od tego, co kliknięte."""
    text = _text_adresowany(msg, "klodzio")
    for probuj in (_tmux_send, _konsole_send):
        r = probuj("klodzio", text)
        if r:
            return r
    # fallback: dopisz do inboxa (nikt nie tailuje — bez token-hazardu; ja czytam na żądanie)
    with open(INBOX, "a") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "from": msg.get("from"), "text": text}) + "\n")
    return "claude -> inbox (brak żywego panelu — odpal jarvis-tmux.sh claude)"


# ── trasa: GIENIA (wstrzyknięcie do jej żywej sesji tmux) ───────────────────
def route_clonker(msg):
    """To samo co Gienia, tylko inny mozg (Haiku zamiast lokalnej Gemmy) i wlasny wpis
    w adresowniku. Osobna nazwa, zeby dalo sie miec obie naraz i celowac swiadomie."""
    text = _text_adresowany(msg, "clonker")
    for probuj in (_tmux_send, _konsole_send):
        r = probuj("clonker", text)
        if r:
            return r
    return "err clonker niezarejestrowany/martwy (brak term-clonker.json — odpal go i zarejestruj)"


def route_gienia(msg, emit):
    """Wstrzykuje zadanie do żywej sesji Gieni (ccr Claude Code w Konsoli) — celowanie
    Konsole-DBus po session-ID, bez fokusu. Jej odpowiedź, pamięć i widoczność żyją w JEJ CLI;
    do kibelka sięga sama (kib-send). Wymaga rejestracji term-gienia.json (pisze ją
    gienia-launch.sh na starcie)."""
    text = _text_adresowany(msg, "gienia")
    for probuj in (_tmux_send, _konsole_send):
        r = probuj("gienia", text)
        if r:
            return r
    return "err Gienia niezarejestrowana/martwa (brak term-gienia.json — odpal ją na nowo)"


# ── pomocnicze ──────────────────────────────────────────────────────────────
def _text(msg):
    p = msg.get("payload", "")
    if isinstance(p, dict): return p.get("text", "") or json.dumps(p, ensure_ascii=False)
    return str(p)

def _text_adresowany(msg, adresat):
    """Ta sama tresc, ale z NAGLOWKIEM `[nadawca → adresat]` na przodzie.

    Kibelek nosi `from`/`to` w kopercie, ale trasy wstrzykiwaly do terminala sam
    `payload` — odbiorca (ja, Gienia) dostawal goly tekst i nie mial jak odroznic
    kibelka od tego, co grruwi wpisal wprost w CLI, ani zobaczyc kto pisze.
    Nazwa adresata bierze sie z TRASY, a nie z `to`, bo `to` moze byc lista i
    kazdy z odbiorcow ma zobaczyc SIEBIE jako adresata.

    Robi sie to wazniejsze z kazdym nowym bytem w kanale: przy trzech i wiecej
    „kto do kogo" przestaje byc oczywiste z samej tresci.
    """
    frm = str(msg.get("from") or "?")
    # ⚠️ ASCII, NIE "→": tmux wpycha tekst przez `send-keys -l`, a trzybajtowy
    # znak UTF-8 potrafi zostac wziety przez TUI za poczatek sekwencji klawisza
    # i zjada to, co przyjdzie zaraz po nim — czyli Enter. Objaw: tekst wchodzi,
    # zatwierdzenie nie (2026-08-11, przy okazji padl tez dyktafon).
    return f"[{frm} -> {adresat}] {_text(msg)}"

def _adres(name):
    """Czyta term-<nazwa>.json. Zwraca dict albo None."""
    reg = os.path.join(CFG, f"term-{name}.json")
    if not os.path.exists(reg):
        return None
    try:
        with open(reg) as f:
            return json.load(f)
    except Exception as e:
        log(f"adresownik {name} zepsuty:", repr(e))
        return None


def _tmux_send(name, text):
    """Wstrzykuje tekst+Enter do panelu tmux zapisanego pod `name` — celuje po pane_id,
    więc fokus, minimalizacja i to, czy ktokolwiek jest podłączony (`attach`), nie mają
    znaczenia. Zwraca opis sukcesu albo None → wołający robi fallback.

    Trzy bezpieczniki, każdy z krwi:
      1. panel musi ISTNIEĆ — martwy pane_id odrzucamy zamiast krzyczeć w pustkę;
      2. w panelu NIE MOŻE siedzieć powłoka — inaczej tekst staje się poleceniem
         (dokładnie tak wyglądał adresownik Konsole 2026-08-02: oba wpisy na jedną
         kartę z gołym bashem);
      3. tekst leci `-l` (literalnie), Enter osobno — bez tego tmux tłumaczyłby
         nazwy klawiszy w treści ("Enter", "C-c") na faktyczne wciśnięcia.
    """
    d = _adres(name)
    if not TMUX or not d or d.get("kind") != "tmux":
        return None
    pane = d.get("pane")
    if not pane:
        return None
    try:
        cmd = subprocess.run(
            [TMUX, "display-message", "-p", "-t", pane, "#{pane_current_command}"],
            capture_output=True, text=True, timeout=5)
        if cmd.returncode != 0:
            log(f"tmux {name}: panel {pane} nie żyje"); return None
        proces = cmd.stdout.strip()
        if proces in POWLOKI:
            log(f"tmux {name}: w panelu {pane} siedzi {proces} — ODMAWIAM (tekst byłby poleceniem)")
            return None
        subprocess.run([TMUX, "send-keys", "-t", pane, "-l", "--", text],
                       check=True, timeout=10)
        # TUI (ink/readline) potrzebuje chwili na przetrawienie wklejki, zanim przyjmie Enter
        time.sleep(0.15)
        subprocess.run([TMUX, "send-keys", "-t", pane, "Enter"], check=True, timeout=5)
        return f"{name} -> tmux {pane} ({proces})"
    except Exception as e:
        log(f"tmux {name} padł:", repr(e))
        return None


def _konsole_proces(svc, ses):
    """Co siedzi w karcie Konsole. Najpierw pytamy wprost o proces pierwszoplanowy;
    gdy ta metoda nie istnieje, czytamy tytuł ("~ : bash" → "bash"). Pusty wynik znaczy
    "nie wiem" — a nie "powłoka", żeby brak metody nie wyłączał całej trasy."""
    for arg in (["org.kde.konsole.Session.foregroundProcessName"],
                ["org.kde.konsole.Session.title", "1"]):
        try:
            r = subprocess.run([QDBUS, svc, ses] + arg,
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().rsplit(":", 1)[-1].strip()
        except Exception:
            pass
    return ""


def _konsole_send(name, text):
    """Wstrzykuje tekst+Enter do sesji Konsole zarejestrowanej pod `name` (term-<name>.json),
    celując po session-ID — OLEWA fokus (fix bugu 'zmiana fokusu → weszło ostatnie słowo').
    Zwraca opis sukcesu albo None gdy się nie da (brak wpisu / martwa sesja / brak qdbus)
    → wołający robi fallback."""
    d = _adres(name)
    if not QDBUS or not d or "svc" not in d:
        return None
    svc, ses = d["svc"], d["ses"]
    if _konsole_proces(svc, ses) in POWLOKI:
        log(f"konsole {name}: w karcie {ses} siedzi powłoka — ODMAWIAM (tekst byłby poleceniem)")
        return None
    try:
        subprocess.run([QDBUS, svc, ses, "org.kde.konsole.Session.sendText", text + "\n"],
                       check=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return f"{name} -> konsole dbus ({ses})"
    except Exception as e:
        log(f"konsole dbus {name} padł (sesja martwa/stały wpis?):", repr(e)); return None

# `claude` zostaje ALIASEM na te sama trase — zeby stare wpisy, skrypty i nawyk
# grruwiego dalej dzialaly. Nazwa wlasciwa to `klodzio` (tak nazywa sie na kibelku).
ROUTES = {"voice": route_voice, "klodzio": route_klodzio, "claude": route_klodzio,
          "clonker": route_clonker}

def dispatch(msg, emit):
    """Rozgłasza wiadomość do adresata(-ów) z pola `to`."""
    feed_tap(msg, "")     # NATYCHMIAST — człowiek widzi wiadomość ZANIM ją wypowiem
                          # (route_voice blokuje aż tts skończy mówić; tap na końcu = feed po mowie)
    tos = msg.get("to", "log")
    if isinstance(tos, str): tos = [tos]
    results = []
    for to in tos:
        if to == "gienia":
            results.append(route_gienia(msg, emit))
        elif to in ROUTES:
            results.append(ROUTES[to](msg))
        elif to == "log":
            results.append("log")
        else:
            results.append(f"err nieznany adresat: {to}")
    resp = "; ".join(results)
    if "err" in resp:     # błąd dokładamy osobną linią (sukcesu nie dublujemy)
        feed_tap(msg, resp)
    return resp


def serve():
    if os.path.exists(SOCK): os.remove(SOCK)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(SOCK); s.listen(16)
    log(f"kibelek słucha na {SOCK} — jedyny czytelnik, PUSH-only")

    def emit(sub):
        """Re-wrzucenie wiadomości do kibelka (np. odpowiedź Gieni) — w osobnym wątku,
        żeby nie zablokować bieżącej obsługi."""
        threading.Thread(target=dispatch, args=(sub, emit), daemon=True).start()

    while True:
        conn, _ = s.accept()
        with conn:
            buf = conn.recv(65536).decode("utf-8", "replace").strip()
            if not buf: continue
            try:
                msg = json.loads(buf)
            except Exception as e:
                conn.sendall(f"err zły json: {e}".encode()); continue
            log(f"{msg.get('from','?')} -> {msg.get('to','?')} [{msg.get('type','?')}]")
            try:
                resp = dispatch(msg, emit)   # dispatch() sam tapuje feed (i pod-wiadomości)
            except Exception as e:
                resp = f"err dispatch: {e}"; log(resp); feed_tap(msg, resp)
            try:
                conn.sendall(resp.encode())
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                log("klient rozłączył się przed odpowiedzią (nieszkodliwe):", repr(e))


if __name__ == "__main__":
    serve()
