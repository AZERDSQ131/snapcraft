#!/usr/bin/env python3
"""
Screenshot Tool — macOS
Raccourci global : Ctrl+Shift+X
"""

import sys
import os
import fcntl
import select
import threading
import traceback

import Quartz
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer

from toolbar import ToolbarWindow

LOCK_FILE = "/tmp/screenshot_tool.lock"
LOG_FILE  = "/tmp/screenshot_tool.log"
KEYCODE_X = 7
CTRL  = Quartz.kCGEventFlagMaskControl
SHIFT = Quartz.kCGEventFlagMaskShift


def log(msg: str):
    line = f"{msg}\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    with open(LOG_FILE, "a") as f:
        f.write(line)


def ensure_accessibility():
    """Vérifie la permission Accessibilité et déclenche la dialog système si manquante."""
    trusted = AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    log(f"Accessibilité : {'✓ OK' if trusted else '✗ MANQUANT — dialog système ouverte'}")
    listen = Quartz.CGPreflightListenEventAccess()
    log(f"Contrôle des saisies : {'✓ OK' if listen else '✗ MANQUANT'}")
    return trusted


def ensure_single_instance():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("Déjà en cours d'exécution.")
        sys.exit(0)
    return lock


def _start_event_tap(write_fd: int):
    tap_ref = [None]  # pour la réactivation depuis le callback

    def _cb(proxy, event_type, event, refcon):
        try:
            # Réactiver le tap s'il a été désactivé par macOS
            if event_type in (Quartz.kCGEventTapDisabledByTimeout,
                              Quartz.kCGEventTapDisabledByUserInput):
                log("Tap désactivé par macOS — réactivation automatique")
                if tap_ref[0]:
                    Quartz.CGEventTapEnable(tap_ref[0], True)
                return event

            if event_type == Quartz.kCGEventKeyDown:
                flags   = Quartz.CGEventGetFlags(event)
                keycode = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode)
                if (keycode == KEYCODE_X
                        and bool(flags & CTRL)
                        and bool(flags & SHIFT)
                        and not bool(flags & Quartz.kCGEventFlagMaskCommand)
                        and not bool(flags & Quartz.kCGEventFlagMaskAlternate)):
                    log("Raccourci détecté !")
                    os.write(write_fd, b'\x01')
                    return None  # supprime l'événement → pas de bip
        except Exception:
            log(f"EXCEPTION dans callback :\n{traceback.format_exc()}")
        return event

    # Masque : uniquement kCGEventKeyDown (les events de désactivation
    # arrivent automatiquement dans le callback sans être dans le masque)
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGHIDEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionDefault,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
        _cb,
        None,
    )

    if tap is None:
        log("ERREUR : CGEventTapCreate → None.")
        log("→ La permission Accessibilité n'est pas accordée à Python.app")
        log(f"→ Ajoute ce binaire dans Réglages Système → Accessibilité :")
        log(f"   {sys.executable}")
        return

    tap_ref[0] = tap
    log("CGEventTap créé — en attente de Ctrl+Shift+X …")
    src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    Quartz.CFRunLoopRun()


def main():
    open(LOG_FILE, "w").close()
    log("=== Screenshot Tool démarrage ===")

    _lock = ensure_single_instance()  # noqa: F841

    # QApplication doit exister avant d'afficher des dialogs
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("ScreenshotTool")

    # Vérifier/demander la permission — déclenche la dialog macOS si besoin
    trusted = ensure_accessibility()
    if not trusted:
        log("En attente que l'utilisateur accorde la permission…")
        osascript_msg = (
            'display alert "Screenshot Tool" message '
            '"Accorde la permission Accessibilité à Python dans\\n'
            'Réglages Système → Confidentialité → Accessibilité\\n\\n'
            'Puis relance l\'app." as warning'
        )
        os.system(f"osascript -e '{osascript_msg}'")

    toolbar = ToolbarWindow()

    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)

    def _poll_pipe():
        r, _, _ = select.select([read_fd], [], [], 0)
        if r:
            os.read(read_fd, 64)
            log("Signal Qt reçu → toggle toolbar")
            toolbar.toggle()

    timer = QTimer()
    timer.timeout.connect(_poll_pipe)
    timer.start(40)

    t = threading.Thread(target=_start_event_tap, args=(write_fd,), daemon=True)
    t.start()

    log("Qt event loop démarrée — raccourci : Ctrl+Shift+X")
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
