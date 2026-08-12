#!/usr/bin/env python3
"""kib-send.py — wrzuca jedną wiadomość do KIBELKA (dispatchera).

To jedyny sposób gadania z busem — każdy (ja przez Bash, Gienia, efektory) używa tego.
Użycie:
    kib-send.py --from klodzio --to voice  --type say "cześć bambik"
    kib-send.py --from gienia --to klodzio --type summon "przyjdź, mamy robotę"
    kib-send.py --from klodzio --to gienia --type ask "co sądzisz o X?"
    kib-send.py --from klodzio --to voice --engine piper "szybko, gram"   # CPU-fallback
`--to` może być kilkukrotne (rozgłos): --to voice --to klodzio
"""
import os, sys, json, socket

SOCK = os.path.expanduser("~/.config/jarvis/kibelek.sock")
args = sys.argv[1:]
msg = {"from": "klodzio", "to": [], "type": "say", "payload": "", "lang": "pl", "engine": "f5"}
rest = []
i = 0
while i < len(args):
    a = args[i]
    if   a == "--from":   msg["from"] = args[i+1]; i += 2
    elif a == "--to":     msg["to"].append(args[i+1]); i += 2
    elif a == "--type":   msg["type"] = args[i+1]; i += 2
    elif a == "--lang":   msg["lang"] = args[i+1]; i += 2
    elif a == "--engine": msg["engine"] = args[i+1]; i += 2
    else: rest.append(a); i += 1
msg["payload"] = " ".join(rest)
if not msg["to"]: msg["to"] = "voice"
elif len(msg["to"]) == 1: msg["to"] = msg["to"][0]

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    s.connect(SOCK)
except (FileNotFoundError, ConnectionRefusedError):
    sys.exit("kibelek nie działa — odpal dispatcher.py")
s.sendall(json.dumps(msg).encode())
print(s.recv(4096).decode())
