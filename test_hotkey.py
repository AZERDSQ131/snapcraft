#!/usr/bin/env python3
"""Test de détection clavier - loggue dans /tmp/key_test.log"""
import datetime
from pynput import keyboard

LOG = "/tmp/key_test.log"

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")
    line = f"[{ts}] {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
    print(line, end="")

log("=== Démarrage du test ===")
log("Appuie sur des touches (Ctrl+C pour arrêter)")

pressed = set()

def on_press(key):
    pressed.add(key)
    log(f"PRESS: {key!r}  |  actifs: {[str(k) for k in pressed]}")

def on_release(key):
    pressed.discard(key)
    log(f"RELEASE: {key!r}")
    if key == keyboard.Key.esc:
        return False  # stoppe le listener

with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()
