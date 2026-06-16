#!/usr/bin/env python3
"""Éditeur d'annotation — mode server (--server) ou standalone (<path>)."""
import sys, os, math, subprocess, tempfile, socket, threading

import objc
from AppKit import (
    NSApplication, NSApp, NSWindow, NSView, NSColor, NSBezierPath,
    NSImage, NSImageView, NSTextField, NSFont, NSAttributedString, NSScreen,
    NSAppearance,
    NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered,
    NSApplicationActivationPolicyRegular, NSApplicationActivationPolicyProhibited,
    NSSegmentedControl, NSSegmentStyleRounded,
    NSFontAttributeName, NSForegroundColorAttributeName,
    NSImageScaleProportionallyUpOrDown,
)
from Foundation import NSObject, NSMakeRect, NSMakePoint, NSString

# ── Constantes ────────────────────────────────────────────────────────────────
SOCKET_PATH = "/tmp/screenshot_editor.sock"
TOOLBAR_H   = 52
BUTTONS_H   = 60

TOOL_RECT  = 0
TOOL_ARROW = 1
TOOL_TEXT  = 2

NSWindowTitleHidden = 1
CTRL_MASK  = 1 << 18
SHIFT_MASK = 1 << 17

C_BG  = NSColor.colorWithRed_green_blue_alpha_(0.10, 0.10, 0.12, 1.0)
C_BAR = NSColor.colorWithRed_green_blue_alpha_(0.07, 0.07, 0.09, 1.0)
C_ANN = NSColor.colorWithRed_green_blue_alpha_(0.95, 0.22, 0.22, 1.0)
BUTTON_COLORS = [
    NSColor.colorWithRed_green_blue_alpha_(0.80, 0.18, 0.18, 1.0),
    NSColor.colorWithRed_green_blue_alpha_(0.18, 0.45, 0.82, 1.0),
    NSColor.colorWithRed_green_blue_alpha_(0.18, 0.65, 0.38, 1.0),
]


def screen_size():
    """Retourne la taille utilisable de l'écran (sans barre de menus/dock)."""
    f = NSScreen.mainScreen().visibleFrame()
    return int(f.size.width), int(f.size.height)


# ── Bouton custom ─────────────────────────────────────────────────────────────
class ClickButton(NSView):
    def drawRect_(self, rect):
        w, h = rect.size.width, rect.size.height
        p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0, 0, w, h), 9, 9)
        c = getattr(self, '_color', None) or NSColor.grayColor()
        c.colorWithAlphaComponent_(0.70 if getattr(self, '_pressed', False) else 1.0).setFill()
        p.fill()
        label = getattr(self, '_label', '') or ''
        attrs = {NSForegroundColorAttributeName: NSColor.whiteColor(),
                 NSFontAttributeName: NSFont.systemFontOfSize_weight_(13, 0.30)}
        s  = NSAttributedString.alloc().initWithString_attributes_(label, attrs)
        sz = s.size()
        s.drawAtPoint_(NSMakePoint((w - sz.width) / 2, (h - sz.height) / 2))

    def mouseDown_(self, event):
        self._pressed = True; self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        self._pressed = False; self.setNeedsDisplay_(True)
        loc = self.convertPoint_fromView_(event.locationInWindow(), None)
        b   = self.bounds()
        if 0 <= loc.x <= b.size.width and 0 <= loc.y <= b.size.height:
            cb = getattr(self, '_cb', None)
            if cb: cb()

    def acceptsFirstResponder(self): return False


def make_btn(frame, label, color, callback):
    b = ClickButton.alloc().initWithFrame_(frame)
    b._label = label; b._color = color; b._pressed = False; b._cb = callback
    return b


# ── Vue fond coloré ───────────────────────────────────────────────────────────
class BarView(NSView):
    def drawRect_(self, rect):
        (getattr(self, '_bg', None) or NSColor.blackColor()).setFill()
        NSBezierPath.fillRect_(rect)


def make_bar(frame, bg):
    v = BarView.alloc().initWithFrame_(frame); v._bg = bg; return v


# ── Annotation ────────────────────────────────────────────────────────────────
class Annotation:
    __slots__ = ("kind", "p1", "p2", "text")
    def __init__(self, kind, p1, p2, text=""):
        self.kind, self.p1, self.p2, self.text = kind, p1, p2, text


# ── Canvas unique : image + annotations ──────────────────────────────────────
class CanvasView(NSView):
    """isFlipped=False → y=0 en bas, cohérent avec NSImage.drawInRect_."""

    def initWithFrame_imagePath_(self, frame, path):
        self = objc.super(CanvasView, self).initWithFrame_(frame)
        if self is None: return None
        self._img_path   = path
        self._anns       = []
        self._redo_stack = []
        self._current    = None
        self._tool       = TOOL_RECT
        self._p0         = None
        self._tf         = None
        self._tf_pos     = (0.0, 0.0)
        return self

    def acceptsFirstResponder(self): return True
    def isOpaque(self): return False
    def setTool_(self, t): self._tool = t

    # ── Dessin (annotations seulement — l'image est dans NSImageView en dessous) ──
    def drawRect_(self, rect):
        NSColor.clearColor().setFill()
        NSBezierPath.fillRect_(rect)
        C_ANN.setStroke(); C_ANN.setFill()
        for a in self._anns: self._draw_ann(a)
        if self._current:    self._draw_ann(self._current)

    @objc.python_method
    def _draw_ann(self, a):
        x1, y1 = a.p1; x2, y2 = a.p2
        if a.kind == TOOL_RECT:
            p = NSBezierPath.bezierPathWithRect_(
                NSMakeRect(min(x1,x2), min(y1,y2), abs(x2-x1), abs(y2-y1)))
            p.setLineWidth_(2.5); p.stroke()
        elif a.kind == TOOL_ARROW:
            p = NSBezierPath.bezierPath(); p.setLineWidth_(2.5)
            p.moveToPoint_(NSMakePoint(x1, y1))
            p.lineToPoint_(NSMakePoint(x2, y2))
            ang = math.atan2(y2-y1, x2-x1); L = 20
            for s in (+1, -1):
                p.moveToPoint_(NSMakePoint(x2, y2))
                p.lineToPoint_(NSMakePoint(x2-L*math.cos(ang-s*.42),
                                           y2-L*math.sin(ang-s*.42)))
            p.stroke()
        elif a.kind == TOOL_TEXT and a.text:
            NSString.stringWithString_(a.text).drawAtPoint_withAttributes_(
                NSMakePoint(x1, y1),
                {NSForegroundColorAttributeName: C_ANN,
                 NSFontAttributeName: NSFont.boldSystemFontOfSize_(18)})

    # ── Souris ────────────────────────────────────────────────────────────
    def mouseDown_(self, event):
        loc = self.convertPoint_fromView_(event.locationInWindow(), None)
        self._p0 = (loc.x, loc.y)
        if self._tool == TOOL_TEXT: self._begin_text(loc.x, loc.y)

    def mouseDragged_(self, event):
        if self._tool == TOOL_TEXT or not self._p0: return
        loc = self.convertPoint_fromView_(event.locationInWindow(), None)
        self._current = Annotation(self._tool, self._p0, (loc.x, loc.y))
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        if self._current: self._push(self._current); self._current = None
        self._p0 = None

    # ── Clavier ───────────────────────────────────────────────────────────
    def keyDown_(self, event):
        f = event.modifierFlags()
        ctrl  = bool(f & CTRL_MASK)
        shift = bool(f & SHIFT_MASK)
        c = (event.charactersIgnoringModifiers() or "").lower()
        if ctrl and c == "z":
            self._redo() if shift else self._undo()
        else:
            objc.super(CanvasView, self).keyDown_(event)

    @objc.python_method
    def _push(self, a):
        self._anns.append(a); self._redo_stack.clear(); self.setNeedsDisplay_(True)

    @objc.python_method
    def _undo(self):
        if self._anns: self._redo_stack.append(self._anns.pop()); self.setNeedsDisplay_(True)

    @objc.python_method
    def _redo(self):
        if self._redo_stack: self._anns.append(self._redo_stack.pop()); self.setNeedsDisplay_(True)

    # ── Texte ─────────────────────────────────────────────────────────────
    @objc.python_method
    def _begin_text(self, x, y):
        if self._tf: self.confirmText()
        tf = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, 260, 36))
        tf.setFont_(NSFont.boldSystemFontOfSize_(18))
        tf.setTextColor_(C_ANN)
        tf.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(0, 0, 0, .5))
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
        if t: self._push(Annotation(TOOL_TEXT, self._tf_pos, self._tf_pos, t))
        else: self.setNeedsDisplay_(True)
        self.window().makeFirstResponder_(self)

    # ── Export ────────────────────────────────────────────────────────────
    @objc.python_method
    def _render(self):
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(self._img_path).convert("RGBA")
        d   = ImageDraw.Draw(img)
        try: font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
        except: font = ImageFont.load_default()
        b = self.bounds()
        cw, ch = b.size.width, b.size.height
        iw, ih = img.width, img.height
        sx, sy = iw / max(cw, 1), ih / max(ch, 1)
        fill, lw = (242, 56, 56, 255), max(2, int(3 * sx))
        for a in self._anns:
            # y est inversé : dans la vue y=0 en bas, dans PIL y=0 en haut
            x1, y1 = int(a.p1[0]*sx), int((ch - a.p1[1])*sy)
            x2, y2 = int(a.p2[0]*sx), int((ch - a.p2[1])*sy)
            if a.kind == TOOL_RECT:
                d.rectangle([min(x1,x2),min(y1,y2),max(x1,x2),max(y1,y2)],
                            outline=fill, width=lw)
            elif a.kind == TOOL_ARROW:
                d.line([x1,y1,x2,y2], fill=fill, width=lw)
                ang = math.atan2(y2-y1, x2-x1); L = int(20*sx)
                pts = [(x2,y2)]
                for s in (+1,-1):
                    pts.append((x2-L*math.cos(ang-s*.42), y2-L*math.sin(ang-s*.42)))
                d.polygon(pts, fill=fill)
            elif a.kind == TOOL_TEXT and a.text:
                d.text((x1,y1), a.text, fill=fill, font=font)
        return img.convert("RGB")

    @objc.python_method
    def _to_clipboard(self, img):
        tmp = tempfile.mktemp(suffix=".png"); img.save(tmp, "PNG")
        subprocess.run(["osascript", "-e",
            f'set the clipboard to (read (POSIX file "{tmp}") as «class PNGf»)'])
        os.unlink(tmp)

    @objc.python_method
    def do_copy_delete(self):
        self.confirmText(); img = self._render(); self._to_clipboard(img)
        if os.path.exists(self._img_path): os.unlink(self._img_path)
        self.window().close()

    @objc.python_method
    def do_copy_save(self):
        self.confirmText(); img = self._render()
        self._to_clipboard(img); img.save(self._img_path, "PNG")
        self.window().close()

    @objc.python_method
    def do_save(self):
        self.confirmText(); self._render().save(self._img_path, "PNG")
        self.window().close()


# ── Fenêtre sans barre de titre ───────────────────────────────────────────────
class EditorWindow(NSWindow):
    def canBecomeKeyWindow(self):  return True
    def canBecomeMainWindow(self): return True


# ── Construction fenêtre ──────────────────────────────────────────────────────
def build_window(image_path, delegate):
    ns   = NSImage.alloc().initWithContentsOfFile_(image_path)
    sz   = ns.size()
    sw, sh = screen_size()

    max_w = sw - 40
    max_h = sh - 40
    img_w, img_h = int(sz.width), int(sz.height)

    canvas_max_h = max_h - TOOLBAR_H - BUTTONS_H
    scale = min(max_w / max(img_w, 1), canvas_max_h / max(img_h, 1), 1.0)
    cw = max(int(img_w * scale), 400)
    ch = max(int(img_h * scale), 200)
    ww = cw
    wh = ch + TOOLBAR_H + BUTTONS_H

    win = EditorWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, ww, wh), NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered, False)
    win.center()
    win.setMovableByWindowBackground_(True)
    win.setBackgroundColor_(C_BG)
    win.setOpaque_(True)
    # Force dark appearance → segmented control et contrôles visibles sur fond sombre
    win.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))

    cv = win.contentView()

    # Layout : y=0 en BAS (NSView non-flipped par défaut)
    # ── Barre du bas (boutons d'action) ──────────────────────────────────
    bot = make_bar(NSMakeRect(0, 0, ww, BUTTONS_H), C_BAR)
    pad = 12; bh = 38; bw = (ww - pad * 4) // 3; by = (BUTTONS_H - bh) // 2
    for i, (lbl, cb) in enumerate([
        ("Copier & Supprimer",   delegate.do_copy_delete),
        ("Copier & Enregistrer", delegate.do_copy_save),
        ("Enregistrer",          delegate.do_save),
    ]):
        bot.addSubview_(make_btn(NSMakeRect(pad+i*(bw+pad), by, bw, bh),
                                 lbl, BUTTON_COLORS[i], cb))
    cv.addSubview_(bot)

    # ── Image (NSImageView en fond) ───────────────────────────────────────
    img_frame = NSMakeRect(0, BUTTONS_H, ww, ch)
    img_view = NSImageView.alloc().initWithFrame_(img_frame)
    img_view.setImage_(NSImage.alloc().initWithContentsOfFile_(image_path))
    img_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
    img_view.setEditable_(False)
    cv.addSubview_(img_view)

    # ── Canvas (couche annotations transparente au-dessus) ────────────────
    canvas = CanvasView.alloc().initWithFrame_imagePath_(img_frame, image_path)
    cv.addSubview_(canvas)

    # ── Barre du haut ─────────────────────────────────────────────────────
    top = make_bar(NSMakeRect(0, BUTTONS_H + ch, ww, TOOLBAR_H), C_BAR)
    seg = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(pad, 11, 270, 30))
    seg.setSegmentCount_(3)
    for i, lbl in enumerate(["▭  Rectangle", "➜  Flèche", "T  Texte"]):
        seg.setLabel_forSegment_(lbl, i)
    seg.setSelectedSegment_(0); seg.setSegmentStyle_(NSSegmentStyleRounded)
    seg.setTarget_(delegate); seg.setAction_("toolChanged:")
    top.addSubview_(seg)
    c_undo  = NSColor.colorWithRed_green_blue_alpha_(.22,.22,.28,1)
    c_close = NSColor.colorWithRed_green_blue_alpha_(.55,.12,.12,1)
    # De droite à gauche : ×  |  ↪  |  ↩
    top.addSubview_(make_btn(NSMakeRect(ww-pad-38,  11, 38, 30), "×",  c_close, delegate.do_close))
    top.addSubview_(make_btn(NSMakeRect(ww-pad-90,  11, 42, 30), "↪",  c_undo,  delegate.do_redo))
    top.addSubview_(make_btn(NSMakeRect(ww-pad-140, 11, 42, 30), "↩",  c_undo,  delegate.do_undo))
    cv.addSubview_(top)

    win.makeKeyAndOrderFront_(None)
    win.makeFirstResponder_(canvas)
    return win, canvas


# ── Delegate ──────────────────────────────────────────────────────────────────
class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, _):
        self._canvas = None; self._win = None
        if _SERVER_MODE:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyProhibited)
            threading.Thread(target=self._listen, daemon=True).start()
        else:
            self._show(_IMAGE_PATH)

    @objc.python_method
    def _listen(self):
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
        self._show(path)
        NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def _show(self, path):
        self._win, self._canvas = build_window(path, self)

    def toolChanged_(self, s):
        if self._canvas: self._canvas.setTool_(s.selectedSegment())

    @objc.python_method
    def do_copy_delete(self):
        if self._canvas: self._canvas.do_copy_delete()

    @objc.python_method
    def do_copy_save(self):
        if self._canvas: self._canvas.do_copy_save()

    @objc.python_method
    def do_save(self):
        if self._canvas: self._canvas.do_save()

    @objc.python_method
    def do_undo(self):
        if self._canvas: self._canvas._undo()

    @objc.python_method
    def do_redo(self):
        if self._canvas: self._canvas._redo()

    @objc.python_method
    def do_close(self):
        if self._win: self._win.close()


# ── Entrée ────────────────────────────────────────────────────────────────────
_SERVER_MODE = "--server" in sys.argv
_IMAGE_PATH  = next((a for a in sys.argv[1:] if not a.startswith("-")), None)


def main():
    if not _SERVER_MODE and (not _IMAGE_PATH or not os.path.exists(_IMAGE_PATH)):
        print("Usage: editor.py <path>  |  editor.py --server")
        sys.exit(1)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    d = AppDelegate.alloc().init()
    app.setDelegate_(d)
    app.run()


if __name__ == "__main__":
    main()
