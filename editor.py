#!/usr/bin/env python3
"""
Éditeur d'annotation — deux modes :
  server : pré-chargé, écoute sur un socket Unix (utilisé par screenshot_tool)
  direct : editor.py <path> — mode standalone / fallback
"""
import sys, os, math, subprocess, tempfile, socket, threading

import objc
from AppKit import (
    NSApplication, NSApp, NSWindow, NSView, NSButton, NSColor,
    NSBezierPath, NSImage, NSTextField, NSFont, NSAttributedString,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskFullSizeContentView,
    NSBackingStoreBuffered, NSApplicationActivationPolicyRegular,
    NSApplicationActivationPolicyProhibited,
    NSSegmentedControl, NSSegmentStyleRounded,
    NSFontAttributeName, NSForegroundColorAttributeName,
)
from Foundation import NSObject, NSMakeRect, NSMakePoint, NSString

# ── Constantes ────────────────────────────────────────────────────────────────
SOCKET_PATH    = "/tmp/screenshot_editor.sock"
TOOLBAR_H      = 52
BUTTONS_H      = 56
MAX_W, MAX_H   = 1440, 960

TOOL_RECT  = 0
TOOL_ARROW = 1
TOOL_TEXT  = 2

NSWindowTitleHidden             = 1
NSWindowStyleMaskFullSizeContent = 32768
CTRL_MASK  = 1 << 18
SHIFT_MASK = 1 << 17

C_BG      = NSColor.colorWithRed_green_blue_alpha_(0.10, 0.10, 0.12, 1.0)
C_BAR     = NSColor.colorWithRed_green_blue_alpha_(0.07, 0.07, 0.09, 1.0)
C_RED_ANN = NSColor.colorWithRed_green_blue_alpha_(0.95, 0.22, 0.22, 1.0)
C_BTN = [
    NSColor.colorWithRed_green_blue_alpha_(0.82, 0.18, 0.18, 1.0),
    NSColor.colorWithRed_green_blue_alpha_(0.18, 0.46, 0.82, 1.0),
    NSColor.colorWithRed_green_blue_alpha_(0.18, 0.68, 0.40, 1.0),
]


# ── Bouton plat custom ────────────────────────────────────────────────────────
class FlatButton(NSButton):
    _fill = None
    _pressed = False

    def setFillColor_(self, c):
        self._fill = c

    def drawRect_(self, rect):
        w, h = rect.size.width, rect.size.height
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0, 0, w, h), 8, 8)
        fill = self._fill or NSColor.grayColor()
        fill.colorWithAlphaComponent_(0.75 if self._pressed else 1.0).setFill()
        path.fill()

        attrs = {
            NSForegroundColorAttributeName: NSColor.whiteColor(),
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(13, 0.35),
        }
        a = NSAttributedString.alloc().initWithString_attributes_(self.title(), attrs)
        sz = a.size()
        a.drawAtPoint_(NSMakePoint((w - sz.width) / 2, (h - sz.height) / 2))

    def mouseDown_(self, event):
        self._pressed = True
        self.setNeedsDisplay_(True)
        objc.super(FlatButton, self).mouseDown_(event)
        self._pressed = False
        self.setNeedsDisplay_(True)


def flat_btn(label, action, target, frame, color):
    b = FlatButton.alloc().initWithFrame_(frame)
    b.setTitle_(label)
    b.setBordered_(False)
    b.setFillColor_(color)
    b.setTarget_(target)
    b.setAction_(action)
    return b


# ── Vue fond coloré ───────────────────────────────────────────────────────────
class BarView(NSView):
    _bg = None
    def initWithFrame_bg_(self, frame, bg):
        self = objc.super(BarView, self).initWithFrame_(frame)
        self._bg = bg
        return self
    def drawRect_(self, rect):
        self._bg.setFill()
        NSBezierPath.fillRect_(rect)


# ── Annotation ────────────────────────────────────────────────────────────────
class Annotation:
    def __init__(self, kind, p1, p2, text=""):
        self.kind, self.p1, self.p2, self.text = kind, p1, p2, text


def _arrow_path(path, x1, y1, x2, y2):
    path.moveToPoint_(NSMakePoint(x1, y1))
    path.lineToPoint_(NSMakePoint(x2, y2))
    a, L = math.atan2(y2-y1, x2-x1), 20
    for s in (+1, -1):
        path.moveToPoint_(NSMakePoint(x2, y2))
        path.lineToPoint_(NSMakePoint(x2 - L*math.cos(a - s*.42),
                                      y2 - L*math.sin(a - s*.42)))


# ── Canvas ────────────────────────────────────────────────────────────────────
class CanvasView(NSView):
    def initWithFrame_imagePath_(self, frame, path):
        self = objc.super(CanvasView, self).initWithFrame_(frame)
        if self is None: return None
        self._path       = path
        self._ns_img     = NSImage.alloc().initWithContentsOfFile_(path)
        self._anns       = []
        self._redo       = []
        self._cur        = None
        self._tool       = TOOL_RECT
        self._p0         = None
        self._tf         = None
        self._tf_pos     = (0, 0)
        return self

    def isFlipped(self): return True
    def acceptsFirstResponder(self): return True

    def setTool_(self, t): self._tool = t

    # ── Dessin ────────────────────────────────────────────────────────────
    def drawRect_(self, rect):
        self._ns_img.drawInRect_(self.bounds())
        C_RED_ANN.setStroke(); C_RED_ANN.setFill()
        for a in self._anns: self._draw(a)
        if self._cur: self._draw(self._cur)

    @objc.python_method
    def _draw(self, a):
        x1,y1 = a.p1; x2,y2 = a.p2
        if a.kind == TOOL_RECT:
            p = NSBezierPath.bezierPathWithRect_(
                NSMakeRect(min(x1,x2), min(y1,y2), abs(x2-x1), abs(y2-y1)))
            p.setLineWidth_(2.5); p.stroke()
        elif a.kind == TOOL_ARROW:
            p = NSBezierPath.bezierPath(); p.setLineWidth_(2.5)
            _arrow_path(p, x1, y1, x2, y2); p.stroke()
        elif a.kind == TOOL_TEXT and a.text:
            NSString.stringWithString_(a.text).drawAtPoint_withAttributes_(
                NSMakePoint(x1, y1),
                {NSForegroundColorAttributeName: C_RED_ANN,
                 NSFontAttributeName: NSFont.boldSystemFontOfSize_(18)})

    # ── Souris ────────────────────────────────────────────────────────────
    def mouseDown_(self, event):
        loc = self.convertPoint_fromView_(event.locationInWindow(), None)
        self._p0 = (loc.x, loc.y)
        if self._tool == TOOL_TEXT:
            self._start_text(loc.x, loc.y)

    def mouseDragged_(self, event):
        if self._tool == TOOL_TEXT or not self._p0: return
        loc = self.convertPoint_fromView_(event.locationInWindow(), None)
        self._cur = Annotation(self._tool, self._p0, (loc.x, loc.y))
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        if self._cur:
            self._commit(self._cur); self._cur = None
        self._p0 = None

    # ── Clavier ───────────────────────────────────────────────────────────
    def keyDown_(self, event):
        f = event.modifierFlags()
        ctrl  = bool(f & CTRL_MASK)
        shift = bool(f & SHIFT_MASK)
        c = (event.charactersIgnoringModifiers() or "").lower()
        if ctrl and c == "z":
            self._redo_ann() if shift else self._undo()
        else:
            objc.super(CanvasView, self).keyDown_(event)

    @objc.python_method
    def _commit(self, a):
        self._anns.append(a); self._redo.clear(); self.setNeedsDisplay_(True)

    def _undo(self):
        if self._anns: self._redo.append(self._anns.pop()); self.setNeedsDisplay_(True)

    def _redo_ann(self):
        if self._redo: self._anns.append(self._redo.pop()); self.setNeedsDisplay_(True)

    # ── Texte ─────────────────────────────────────────────────────────────
    @objc.python_method
    def _start_text(self, x, y):
        if self._tf: self.confirmText()
        tf = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, 260, 36))
        tf.setFont_(NSFont.boldSystemFontOfSize_(18))
        tf.setTextColor_(C_RED_ANN)
        tf.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(0,0,0,.45))
        tf.setDrawsBackground_(True); tf.setBordered_(False)
        tf.setStringValue_(""); tf.setPlaceholderString_("Texte…")
        tf.setTarget_(self); tf.setAction_("confirmText")
        self.addSubview_(tf)
        self.window().makeFirstResponder_(tf)
        self._tf = tf; self._tf_pos = (x, y)

    def confirmText(self):
        if not self._tf: return
        t = self._tf.stringValue()
        self._tf.removeFromSuperview(); self._tf = None
        if t: self._commit(Annotation(TOOL_TEXT, self._tf_pos, self._tf_pos, t))
        else: self.setNeedsDisplay_(True)
        self.window().makeFirstResponder_(self)

    # ── Export ────────────────────────────────────────────────────────────
    @objc.python_method
    def _pil_render(self):
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(self._path).convert("RGBA")
        d   = ImageDraw.Draw(img)
        try: font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
        except: font = ImageFont.load_default()
        fill, lw = (242, 56, 56, 255), 3
        for a in self._anns:
            x1,y1 = a.p1; x2,y2 = a.p2
            if a.kind == TOOL_RECT:
                d.rectangle([min(x1,x2),min(y1,y2),max(x1,x2),max(y1,y2)], outline=fill, width=lw)
            elif a.kind == TOOL_ARROW:
                d.line([x1,y1,x2,y2], fill=fill, width=lw)
                ang, L = math.atan2(y2-y1, x2-x1), 20
                pts = [(x2,y2)]
                for s in (+1,-1): pts.append((x2-L*math.cos(ang-s*.42), y2-L*math.sin(ang-s*.42)))
                d.polygon(pts, fill=fill)
            elif a.kind == TOOL_TEXT and a.text:
                d.text((x1,y1), a.text, fill=fill, font=font)
        return img.convert("RGB")

    @staticmethod
    def _clipboard(img):
        tmp = tempfile.mktemp(suffix=".png"); img.save(tmp, "PNG")
        subprocess.run(["osascript","-e",
            f'set the clipboard to (read (POSIX file "{tmp}") as «class PNGf»)'])
        os.unlink(tmp)

    def do_copy_delete(self):
        self.confirmText(); img = self._pil_render(); self._clipboard(img)
        if os.path.exists(self._path): os.unlink(self._path)
        self.window().close()

    def do_copy_save(self):
        self.confirmText(); img = self._pil_render()
        self._clipboard(img); img.save(self._path, "PNG")
        self.window().close()

    def do_save(self):
        self.confirmText(); self._pil_render().save(self._path, "PNG")
        self.window().close()


# ── Fenêtre d'édition ─────────────────────────────────────────────────────────
def build_window(image_path, delegate):
    ns = NSImage.alloc().initWithContentsOfFile_(image_path)
    sz = ns.size()
    W, H = int(sz.width), int(sz.height)
    ww = min(W, MAX_W)
    wh = min(H + TOOLBAR_H + BUTTONS_H, MAX_H)

    style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
             | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskFullSizeContent)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, ww, wh), style, NSBackingStoreBuffered, False)
    win.center()
    win.setTitle_("Screenshot Editor")
    win.setTitleVisibility_(NSWindowTitleHidden)
    win.setTitlebarAppearsTransparent_(True)
    win.setMovableByWindowBackground_(True)
    win.setBackgroundColor_(C_BG)
    for i in range(3):
        win.standardWindowButton_(i).setHidden_(True)

    cv = win.contentView()

    # Barre du bas
    bot = BarView.alloc().initWithFrame_bg_(NSMakeRect(0, 0, ww, BUTTONS_H), C_BAR)
    pad, bh = 12, 36
    bw = (ww - pad * 4) // 3
    by = (BUTTONS_H - bh) // 2
    labels = ["Copier & Supprimer", "Copier & Enregistrer", "Enregistrer"]
    actions = ["actCopyDelete:", "actCopySave:", "actSave:"]
    for i, (lbl, act) in enumerate(zip(labels, actions)):
        bx = pad + i * (bw + pad)
        bot.addSubview_(flat_btn(lbl, act, delegate, NSMakeRect(bx, by, bw, bh), C_BTN[i]))
    cv.addSubview_(bot)

    # Canvas
    ch = wh - TOOLBAR_H - BUTTONS_H
    canvas = CanvasView.alloc().initWithFrame_imagePath_(
        NSMakeRect(0, BUTTONS_H, ww, ch), image_path)
    cv.addSubview_(canvas)

    # Barre du haut
    top = BarView.alloc().initWithFrame_bg_(
        NSMakeRect(0, BUTTONS_H + ch, ww, TOOLBAR_H), C_BAR)

    seg = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(pad, 11, 270, 30))
    seg.setSegmentCount_(3)
    for i, lbl in enumerate(["▭  Rectangle", "➜  Flèche", "T  Texte"]):
        seg.setLabel_forSegment_(lbl, i)
    seg.setSelectedSegment_(0)
    seg.setSegmentStyle_(NSSegmentStyleRounded)
    seg.setTarget_(delegate); seg.setAction_("toolChanged:")
    top.addSubview_(seg)

    # Undo / Redo
    for j, (lbl, act) in enumerate([("↩", "actUndo:"), ("↪", "actRedo:")]):
        ub = flat_btn(lbl, act, delegate,
                      NSMakeRect(ww - 100 + j*46, 11, 40, 30),
                      NSColor.colorWithRed_green_blue_alpha_(.25,.25,.30,1))
        top.addSubview_(ub)

    cv.addSubview_(top)

    win.makeKeyAndOrderFront_(None)
    win.makeFirstResponder_(canvas)
    return win, canvas


# ── Delegate ──────────────────────────────────────────────────────────────────
class AppDelegate(NSObject):
    _canvas = None

    def applicationDidFinishLaunching_(self, notif):
        # Mode serveur : on attend les connexions socket, pas de fenêtre tout de suite
        if _SERVER_MODE:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyProhibited)
            t = threading.Thread(target=self._socket_loop, daemon=True)
            t.start()
        else:
            self._open(_IMAGE_PATH)

    @objc.python_method
    def _socket_loop(self):
        if os.path.exists(SOCKET_PATH): os.unlink(SOCKET_PATH)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCKET_PATH); srv.listen(5)
        while True:
            conn, _ = srv.accept()
            path = conn.recv(4096).decode().strip(); conn.close()
            if path and os.path.exists(path):
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "openPath:", path, False)

    def openPath_(self, path):
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self._open(path)
        NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def _open(self, path):
        win, canvas = build_window(path, self)
        self._canvas = canvas
        self._win = win

    # Outils
    def toolChanged_(self, s): self._canvas and self._canvas.setTool_(s.selectedSegment())
    def actCopyDelete_(self, _): self._canvas and self._canvas.do_copy_delete()
    def actCopySave_(self, _):   self._canvas and self._canvas.do_copy_save()
    def actSave_(self, _):       self._canvas and self._canvas.do_save()
    def actUndo_(self, _):       self._canvas and self._canvas._undo()
    def actRedo_(self, _):       self._canvas and self._canvas._redo_ann()


# ── Entrée ────────────────────────────────────────────────────────────────────
_SERVER_MODE = "--server" in sys.argv
_IMAGE_PATH  = next((a for a in sys.argv[1:] if not a.startswith("-")), None)

def main():
    if not _SERVER_MODE and (not _IMAGE_PATH or not os.path.exists(_IMAGE_PATH)):
        print("Usage: editor.py <image_path>  |  editor.py --server")
        sys.exit(1)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    d = AppDelegate.alloc().init()
    app.setDelegate_(d)
    app.run()

if __name__ == "__main__":
    main()
