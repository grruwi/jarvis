#!/usr/bin/env python3
"""voice-hook-gienia.py — Stop hook Gieni: mówi JEJ ostatnią odpowiedź przez kibelek (from=gienia).

Bliźniak voice-hook.py, dwie różnice:
  - --from gienia  (dispatcher wybiera JEJ głos po `from`)
  - osobna flaga-guard voice-gienia.on  (można wyciszać ją niezależnie ode mnie)

Odpala go harness Gieni (ccr Claude Code) na Stop. Lokalny skrypt, ZERO tokenów modelu.
W jej bwrap-sandboxie cały FS jest widoczny (--dev-bind / /), więc kib-send + socket działają.
"""
import os, sys, json, time, subprocess

FLAG = os.path.expanduser("~/.config/jarvis/voice-gienia.on")
KIB  = os.path.expanduser("~/Dokumenty/jarvis/kib-send.py")

SETTLE_TRIES = 8
SETTLE_GAP   = 0.15


def main():
    if not os.path.exists(FLAG):
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    tp = payload.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return
    text = None
    for _ in range(SETTLE_TRIES):
        cand, settled = final_text(tp)
        if settled and cand:
            text = cand
            break
        time.sleep(SETTLE_GAP)
    if not text:
        return
    try:
        subprocess.run(["python3", KIB, "--from", "gienia", "--to", "voice",
                        "--engine", "f5", text], timeout=300)
    except Exception:
        pass


def final_text(path):
    """(tekst, settled): settled=True gdy ostatnia wypowiedź-z-tekstem jest FINALNA (po niej
    brak tool_use) — zabija wyścig ze zrzutem transkryptu i podwójne odpalenie."""
    msgs = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            if o.get("type") != "assistant":
                continue
            msg = o.get("message", {})
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            txt = "".join(b.get("text", "") for b in content
                          if isinstance(b, dict) and b.get("type") == "text").strip()
            has_tool = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
            msgs.append((txt, has_tool))
    last_i = None
    for i, (txt, _) in enumerate(msgs):
        if txt:
            last_i = i
    if last_i is None:
        return (None, False)
    settled = not any(has for (_, has) in msgs[last_i + 1:])
    return (msgs[last_i][0], settled)


if __name__ == "__main__":
    main()
