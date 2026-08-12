#!/usr/bin/env python3
"""tts-f5.py — BAZA głosu Jarvisa. Rezydentny silnik F5, recepta tts-test-f5.py 1:1.

Config v0 (F5TTS_Base = dim 1024 / depth 22, wokoder vocos) + polski vocab + checkpoint
Gregniuki/Marek. Model siedzi CIEPŁY w VRAM i mówi na żądanie.

Filtr clean() jest TU, w silniku — GLOBALNIE. Każdy tekst wchodzący socketem (hook,
ręczny kib-send, Gienia — wszystko jedno) jest normalizowany ZANIM trafi do F5. Powód:
F5 ma vocab 2545 tokenów; znak SPOZA vocab (np. polski cudzysłów „) wykłada cały chunk
i F5 go gubi. Więc: liczby -> słowa, ścieżki/kod -> precz, symbole -> pauzy, na końcu
whitelist samych znaków bezpiecznych. Nic nieliterowego nie dochodzi do modelu.

Protokół: linia JSON {"text": "..."} na ~/.config/jarvis/tts.sock -> mówi. Odp "ok"/"err".
Wyciszenie: plik ~/.config/jarvis/mute (jarvis off).
"""
import os, sys, json, socket, subprocess, threading, time, re
import soundfile as sf
import numpy as np

# --- shim: torchaudio 2.9 wczytuje przez torchcodec, który nie ładuje się przy ffmpeg 8
# (wspiera 4-7). Podmieniam load/info na soundfile -> torchcodec nigdy nie dotknięty. ---
import torch, torchaudio
def _sf_load(path, *a, **k):
    d, sr = sf.read(path, dtype="float32", always_2d=True)
    return torch.from_numpy(d.T.copy()), sr
def _sf_info(path, *a, **k):
    i = sf.info(path)
    class _I: sample_rate=i.samplerate; num_frames=i.frames; num_channels=i.channels; bits_per_sample=16; encoding="PCM_S"
    return _I()
torchaudio.load = _sf_load; torchaudio.info = _sf_info

JV   = os.path.expanduser("~/Dokumenty/jarvis")
CFG  = os.path.expanduser("~/.config/jarvis")
SOCK = os.path.join(CFG, "tts.sock")
MUTE = os.path.join(CFG, "mute")
os.makedirs(CFG, exist_ok=True)

CKPT = os.path.join(JV, "models/f5-pl/Polish/model_270000.safetensors")
VOC  = os.path.join(JV, "models/f5-pl/Polish/vocab.txt")
REF  = os.path.join(JV, "marek/sample_pan_tadeusz.wav")
OUT  = "/tmp/jarvis_f5_out.wav"
REF_TXT = ("Litwo! Ojczyzno moja! ty jesteś jak zdrowie; "
           "ile cię trzeba cenić, ten tylko się dowie, kto cię stracił.")

# kroki ODE (denoising). 32 = pod prędkość ale mętne; 64 = ostra artykulacja (grruwi A/B).
NFE = 64
# sway_sampling_coef: schedule kroków szum->mowa. -1 (default F5) głodzi fazę detalu ->
# rozmyte ŚĆŹŻ; 0 = równo (grruwi "50/50", ostrzejsze sybilanty).
SWAY = 0
# seed PRZYPIĘTY: F5 domyślnie losuje ziarno co wywołanie -> ta sama konfiguracja raz brzmi
# trzeźwo raz pijawo (RNG). Sztywny seed = powtarzalność (grruwi 2026-07-05: "przypnij seed").
# Podmienić jeśli kiedyś zabrzmi źle (słyszane kandydaty: 11/22/33).
SEED = 11


# ══════ FILTR (globalny) — technika/markdown -> wymawialny polski ══════════════
_PL = "a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
_JED   = ["zero","jeden","dwa","trzy","cztery","pięć","sześć","siedem","osiem","dziewięć"]
_NAST  = ["dziesięć","jedenaście","dwanaście","trzynaście","czternaście","piętnaście",
          "szesnaście","siedemnaście","osiemnaście","dziewiętnaście"]
_DZIES = ["","","dwadzieścia","trzydzieści","czterdzieści","pięćdziesiąt","sześćdziesiąt",
          "siedemdziesiąt","osiemdziesiąt","dziewięćdziesiąt"]
_SETKI = ["","sto","dwieście","trzysta","czterysta","pięćset","sześćset","siedemset",
          "osiemset","dziewięćset"]

def _pod_tysiac(n):
    out = []
    if n >= 100: out.append(_SETKI[n // 100]); n %= 100
    if n >= 20:
        out.append(_DZIES[n // 10]); n %= 10
        if n: out.append(_JED[n])
    elif n >= 10: out.append(_NAST[n - 10])
    elif n > 0:   out.append(_JED[n])
    return " ".join(out)

def liczba(n):
    if n == 0: return "zero"
    if n >= 1_000_000: return " ".join(_JED[int(c)] for c in str(n))
    if n < 1000: return _pod_tysiac(n)
    t, r = n // 1000, n % 1000
    if t == 1: tys = "tysiąc"
    else:
        l2, l1 = t % 100, t % 10
        odm = "tysiące" if (2 <= l1 <= 4 and not 12 <= l2 <= 14) else "tysięcy"
        tys = _pod_tysiac(t) + " " + odm
    return tys + (" " + _pod_tysiac(r) if r else "")

def _num_sub(m):
    s = m.group(0)
    if "." in s or "," in s:
        a, b = re.split(r"[.,]", s, 1)
        return f"{liczba(int(a or 0))} przecinek {' '.join(_JED[int(c)] for c in b)}"
    return liczba(int(s))

_CODE_EXT = re.compile(r"\.(py|sh|json|sock|txt|md|log|wav|onnx|safetensors|pt|"
                       r"cfg|conf|toml|ya?ml|ini|c|h|js|ts|rs|go)$", re.I)
def _is_junk(tok):
    if any(c in tok for c in "/\\~@"): return True
    if re.search(r"[\w]_[\w]", tok): return True
    if _CODE_EXT.search(tok): return True
    if re.search(r"[A-Za-ząćęłńóśźż]\.[A-Za-z]", tok): return True
    if re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok) and len(re.sub(r"\W", "", tok)) > 4:
        return True
    return False

def clean(t):
    """Markdown + technika -> czysty wymawialny polski (tylko znaki które F5 zna)."""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = t.replace("\n", " ")
    t = " ".join("" if _is_junk(w) else w for w in t.split())      # ścieżki/kod -> precz
    t = re.sub(r"[*#>|]+", " ", t)
    t = re.sub(r"^\s*[-•·]\s*", "", t, flags=re.M)
    t = t.replace("…", ". ").replace("&", " i ").replace("%", " procent ")
    t = re.sub(r"\s*=\s*", " równa się ", t)
    t = re.sub(r"[—–]", ", ", t)
    t = re.sub(r"[→←↔⇒⟂•·]+", ", ", t)
    t = t.replace("-", " ")
    t = re.sub(r"[\U0001F000-\U0001FAFF]", " ", t)
    t = re.sub(rf"(?<![{_PL}0-9])\d+(?:[.,]\d+)?(?![{_PL}0-9])", _num_sub, t)
    t = re.sub(rf"[^{_PL}\s.,!?;:]", " ", t)                       # whitelist: reszta precz
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)
    t = re.sub(r"([.,!?;:])\1+", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t).strip()
    if t and t[-1] not in ".!?": t += "."
    return t


# ══════ SILNIK ════════════════════════════════════════════════════════════════
_lock = threading.Lock()
_f5 = None
def log(*a): print("[tts-f5]", *a, file=sys.stderr, flush=True)

def load_f5():
    global _f5
    if _f5 is None:
        from f5_tts.api import F5TTS
        t0 = time.time()
        # model='F5TTS_Base' = config v0 (dim 1024/depth 22, vocos); NIE domyślny v1_Base.
        _f5 = F5TTS(model="F5TTS_Base", ckpt_file=CKPT, vocab_file=VOC, device="cuda")
        log(f"F5 (v0) załadowany w {time.time()-t0:.1f}s (ciepły, w VRAM)")
    return _f5

def _gen(f5, s):
    wav, sr, _ = f5.infer(ref_file=REF, ref_text=REF_TXT, gen_text=s,
                          nfe_step=NFE, sway_sampling_coef=SWAY, seed=SEED,
                          show_info=lambda *a, **k: None)
    return wav, sr

def speak(text):
    # CIĘCIE NA ZDANIA: F5 dryfuje/mętnieje na długim tekście (tnie go wewnętrznie i psuje
    # sklejenia). Każde zdanie osobno = krótki, czysty przebieg. Sklejam z 0.15s ciszą.
    f5 = load_f5()
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()] or [text]
    parts, sr = [], 24000
    for s in sents:
        w, sr = _gen(f5, s)
        parts.append(w); parts.append(np.zeros(int(sr * 0.15), dtype=np.float32))
    sf.write(OUT, np.concatenate(parts), sr)
    subprocess.run(["paplay", OUT], check=False)

def handle(req):
    raw = (req.get("text") or "").strip()
    text = clean(raw)                        # <-- FILTR GLOBALNY: każdy tekst tędy
    if not text:
        return "err brak text"
    if os.path.exists(MUTE):
        return "ok (muted)"
    with _lock:
        try:
            speak(text)
            return "ok"
        except Exception as e:
            log("BŁĄD:", repr(e))
            return f"err {e}"

def serve():
    if os.path.exists(SOCK): os.remove(SOCK)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(SOCK); s.listen(8)
    log(f"słucham na {SOCK}")
    if "--warm" in sys.argv:
        try:
            load_f5().infer(ref_file=REF, ref_text=REF_TXT, gen_text="rozgrzewka",
                            nfe_step=NFE, file_wave="/tmp/jarvis_warm.wav", show_info=lambda *a, **k: None)
            log("kernele skompilowane — pierwsza wiadomość od razu szybka")
        except Exception as e:
            log("rozgrzewka nieudana:", repr(e))
    while True:
        conn, _ = s.accept()
        with conn:
            buf = conn.recv(65536).decode("utf-8", "replace").strip()
            if not buf: continue
            try:
                req = json.loads(buf)
            except Exception as e:
                conn.sendall(f"err zły json: {e}".encode()); continue
            conn.sendall(handle(req).encode())

if __name__ == "__main__":
    serve()
