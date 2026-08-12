#!/usr/bin/env python3
"""tts-cpu-diag.py — DIAGNOSTYKA pływania głosu F5 na CPU (sprzęt wyłączony jako zmienna).

Cel: F5 na GPU/ROCm pływa niewymiernie (raz pijany omija ŚĆŹŻ, słowo dalej lektor).
Pytanie: czy to nondeterminizm sprzętu (kernele GPU) czy config/checkpoint?
CPU liczy deterministyczniej. Odpalamy TO SAMO zdanie 3× seed=11 (test bit-powtarzalności)
+ seed 22/33 (skala pływania seed-do-seed). md5 = czy identyczne, ucho grruwiego = werdykt.

BEZ tasksetu — kernelowy systemd.cpuaffinity=1-7,9-15 ma sam rządzić (rdzeń 0 wolny).
Config 1:1 z żywym silnikiem: F5TTS_Base v0, NFE 64, SWAY 0, ref marka. Tylko device=cpu.
"""
import time, os, sys, hashlib, subprocess
import soundfile as sf
import numpy as np

# shim: torchaudio 2.9 -> torchcodec nie ładuje się przy ffmpeg 8. Podmieniam na soundfile.
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
CKPT = os.path.join(JV, "models/f5-pl/Polish/model_270000.safetensors")
VOC  = os.path.join(JV, "models/f5-pl/Polish/vocab.txt")
REF  = os.path.join(JV, "marek/sample_pan_tadeusz.wav")
REF_TXT = ("Litwo! Ojczyzno moja! ty jesteś jak zdrowie; "
           "ile cię trzeba cenić, ten tylko się dowie, kto cię stracił.")
# jedno zdanie nafaszerowane ŚĆŹŻ, bez cięcia — ma wywołać wewnątrz-zdaniowy dryf sybilantów.
GEN = ("Wściekły chrząszcz Grzegorz Brzęczyszczykiewicz szczerze świszcze, "
       "gdy źdźbło żółci ściska dźwięczną gęstwinę w Szczebrzeszynie.")

NFE, SWAY = 64, 0

# GROUND TRUTH: na jakich rdzeniach realnie siedzimy (nie deklaracja — sprawdzenie).
print(f"[affinity] proces widzi rdzenie: {sorted(os.sched_getaffinity(0))}", flush=True)
print(f"[threads]  torch.get_num_threads() = {torch.get_num_threads()}", flush=True)

from f5_tts.api import F5TTS
t0 = time.time()
f5 = F5TTS(model="F5TTS_Base", ckpt_file=CKPT, vocab_file=VOC, device="cpu")
print(f"[load] F5 v0 na CPU w {time.time()-t0:.1f}s", flush=True)

def gen(seed, tag):
    t = time.time()
    wav, sr, _ = f5.infer(ref_file=REF, ref_text=REF_TXT, gen_text=GEN,
                          nfe_step=NFE, sway_sampling_coef=SWAY, seed=seed,
                          show_info=lambda *a, **k: None)
    dt = time.time() - t
    out = f"/tmp/f5cpu_{tag}.wav"
    sf.write(out, wav, sr)
    h = hashlib.md5(open(out, "rb").read()).hexdigest()[:12]
    dur = len(wav) / sr
    print(f"[{tag}] seed={seed}  gen {dt:5.1f}s | audio {dur:4.1f}s | RTF {dt/dur:5.2f} | md5 {h} -> {out}", flush=True)
    return out

runs = [(11, "s11_a"), (11, "s11_b"), (11, "s11_c"), (22, "s22"), (33, "s33")]
outs = [gen(s, t) for s, t in runs]

print("\n=== ODSŁUCH (kolejno, 0.8s przerwy) ===", flush=True)
for o in outs:
    print(f"  gram {o}", flush=True)
    subprocess.run(["paplay", o], check=False)
    time.sleep(0.8)
print("gotowe — pliki zostają w /tmp/f5cpu_*.wav do ponownego odsłuchu", flush=True)
