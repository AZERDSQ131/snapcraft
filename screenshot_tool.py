#!/usr/bin/env python3
import os
import sys
import select
import subprocess
import threading
import traceback
import json
from datetime import datetime

import Quartz
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

LOG_FILE  = "/tmp/screenshot_tool.log"
KEYCODE_X = 7
CTRL  = Quartz.kCGEventFlagMaskControl
SHIFT = Quartz.kCGEventFlagMaskShift
PID_FILE = "/tmp/screenshot_tool.pid"


def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"{msg}\n")


def take_screenshot():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.expanduser(f'~/Desktop/capture_{ts}.png')
    log("capture start")
    proc = subprocess.run(
        ['screencapture', '-i', path],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and os.path.exists(path):
        log(f"capture saved: {path}")
        python_bin = sys.executable
        editor = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'editor.py')
        subprocess.Popen([python_bin, editor, path])
    else:
        log("capture cancelled")


def event_tap_loop(write_fd):
    tap_ref = [None]

    def callback(proxy, event_type, event, refcon):
        try:
            if event_type in (Quartz.kCGEventTapDisabledByTimeout,
                              Quartz.kCGEventTapDisabledByUserInput):
                log(f"tap désactivé (type={event_type}), réactivation...")
                if tap_ref[0]:
                    Quartz.CGEventTapEnable(tap_ref[0], True)
                return event

            if event_type == Quartz.kCGEventKeyDown:
                flags   = Quartz.CGEventGetFlags(event)
                keycode = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode)
                log(f"keydown: keycode={keycode} flags={flags:#010x}")
                if (keycode == KEYCODE_X
                        and bool(flags & CTRL)
                        and bool(flags & SHIFT)
                        and not bool(flags & Quartz.kCGEventFlagMaskCommand)
                        and not bool(flags & Quartz.kCGEventFlagMaskAlternate)):
                    os.write(write_fd, b'x')
                    return None
        except Exception:
            log(f"callback error: {traceback.format_exc()}")
        return event

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGHIDEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionDefault,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
        callback,
        None,
    )

    if tap is None:
        log("CGEventTapCreate failed — permission manquante")
        return

    log("event tap créé avec succès")
    tap_ref[0] = tap
    src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
    enabled = Quartz.CGEventTapIsEnabled(tap)
    log(f"tap activé: {enabled}")
    Quartz.CGEventTapEnable(tap, True)
    log("run loop démarré")
    Quartz.CFRunLoopRun()
    log("run loop terminé (inattendu)")


def run():
    log("=== started ===")

    # Empêche Python d'apparaître dans le Dock quand screencapture ouvre son UI
    try:
        import AppKit
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyProhibited)
    except Exception:
        pass

    trusted = AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    if not trusted:
        log("accessibility not granted")
        subprocess.run([
            'osascript', '-e',
            'display notification "Active la permission Accessibilite '
            'pour Python dans Reglages Systeme > Confidentialite > '
            'Accessibilite" with title "Screenshot Tool"'
        ])
        return

    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)

    t = threading.Thread(target=event_tap_loop, args=(write_fd,), daemon=True)
    t.start()

    log("ready — Ctrl+Shift+X")

    while True:
        try:
            r, _, _ = select.select([read_fd], [], [], None)
            if r:
                os.read(read_fd, 64)
                take_screenshot()
        except Exception:
            log(f"main loop error: {traceback.format_exc()}")


APP_NAME = "ScreenshotTool"
SUPPORT_DIR = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")


def install():
    import shutil

    os.makedirs(SUPPORT_DIR, exist_ok=True)
    script_dest = os.path.join(SUPPORT_DIR, "screenshot_tool.py")
    shutil.copy2(os.path.abspath(__file__), script_dest)
    os.chmod(script_dest, 0o755)

    agent_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(agent_dir, exist_ok=True)

    python_bin = sys.executable
    plist = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.screenshot-tool</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{script_dest}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/screenshot_tool.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/screenshot_tool.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/bin:/usr/local/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>'''

    plist_path = os.path.join(agent_dir, "com.screenshot-tool.plist")
    with open(plist_path, "w") as f:
        f.write(plist)

    subprocess.run(["launchctl", "load", plist_path])

    print(f"Installed: {plist_path}")
    print()
    print("The tool is now running in the background.")
    print("Grant Accessibility permission if prompted:")
    print("  System Settings > Privacy & Security > Accessibility")
    print(f"  Add: {python_bin}")
    print()
    print("Press Ctrl+Shift+X to capture.")
    print("The tool starts automatically on login.")


def uninstall():
    import shutil

    plist_path = os.path.expanduser(
        "~/Library/LaunchAgents/com.screenshot-tool.plist")
    if os.path.exists(plist_path):
        subprocess.run(["launchctl", "unload", plist_path])
        os.unlink(plist_path)

    if os.path.exists(SUPPORT_DIR):
        shutil.rmtree(SUPPORT_DIR)

    print("Uninstalled.")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "install":
            install()
        elif cmd == "uninstall":
            uninstall()
        else:
            print(f"Usage: {sys.argv[0]} [install|uninstall]")
    else:
        run()
