#!/usr/bin/env python3
"""Éditeur d'annotation pour screenshots."""
import sys
import os
import math
import subprocess
import tempfile

import objc
from AppKit import (
    NSApplication, NSApp, NSWindow, NSView, NSButton, NSColor,
    NSBezierPath, NSImage, NSTextField, NSFont, NSText,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskFullSizeContentView,
    NSBackingStoreBuffered, NSApplicationActivationPolicyRegular,
    NSSegmentedControl, NSSegmentStyleRounded,
    NSFontAttributeName, NSForegroundColorAttributeName,
)
from Foundation import NSObject, NSMakeRect, NSMakePoint, NSString

IMAGE_PATH = sys.argv[1] if len(sys.argv) > 1 else None

TOOL_RECT  = 0
TOOL_ARROW = 1
TOOL_TEXT  = 2

# NSWindowTitleHidden = 1, NSWindowStyleMaskFullSizeContentView = 32768
NSWindowTitleHidden              = 1
NSWindowStyleMaskFullSizeContent = 32768

DARK   = NSColor.colorWithRed_green_blue_alpha_(0.11, 0.11, 0.13, 1.0)
DARKER = NSColor.colorWithRed_green_blue_alpha_(0.08, 0.08, 0.10, 1.0)
RED_ANN = NSColor.colorWithRed_green_blue_alpha_(0.95, 0.22, 0.22, 1.0)

CTRL_MASK  = 1 << 18   # NSEventModifierFlagControl
SHIFT_MASK = 1 << 17   # NSEventModifierFlagShift


class Annotation:
    def __init__(self, kind, p1, p2, text=""):
        self.kind = kind
        self.p1   = p1
        self.p2   = p2
        self.text = text


def _draw_arrow_path(path, x1, y1, x2, y2):
    path.moveToPoint_(NSMakePoint(x1, y1))
    path.lineToPoint_(NSMakePoint(x2, y2))
    angle = math.atan2(y2 - y1, x2 - x1)
    L = 20
    for sign in (+1, -1):
        path.moveToPoint_(NSMakePoint(x2, y2))
        path.lineToPoint_(NSMakePoint(
            x2 - L * math.cos(angle - sign * 0.42),
            y2 - L * math.sin(angle - sign * 0.42),
        ))


# ── Vue de fond coloré ────────────────────────────────────────────────────────
class ColorView(NSView):
    def initWithFrame_color_(self, frame, color):
        self = objc.super(ColorView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._bg = color
        return self

    def drawRect_(self, rect):
        self._bg.setFill()
        NSBezierPath.fillRect_(rect)


# ── Canvas principal ──────────────────────────────────────────────────────────
class CanvasView(NSView):
    def initWithFrame_imagePath_(self, frame, image_path):
        self = objc.super(CanvasView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._image_path  = image_path
        self._ns_image    = NSImage.alloc().initWithContentsOfFile_(image_path)
        self._annotations = []
        self._redo_stack  = []
        self._current     = None
        self._tool        = TOOL_RECT
        self._drag_start  = None
        self._text_field  = None
        self._text_pos    = (0, 0)
        return self

    def isFlipped(self):
        return True

    def acceptsFirstResponder(self):
        return True

    def setTool_(self, tool):
        self._tool = tool

    # ── Dessin ────────────────────────────────────────────────────────────────
    def drawRect_(self, rect):
        self._ns_image.drawInRect_(self.bounds())
        RED_ANN.setStroke()
        RED_ANN.setFill()
        lw = 2.5
        for ann in self._annotations:
            self._draw_ann(ann, lw)
        if self._current:
            self._draw_ann(self._current, lw)

    def _draw_ann(self, ann, lw):
        x1, y1 = ann.p1
        x2, y2 = ann.p2

        if ann.kind == TOOL_RECT:
            path = NSBezierPath.bezierPathWithRect_(
                NSMakeRect(min(x1,x2), min(y1,y2), abs(x2-x1), abs(y2-y1)))
            path.setLineWidth_(lw)
            path.stroke()

        elif ann.kind == TOOL_ARROW:
            path = NSBezierPath.bezierPath()
            path.setLineWidth_(lw)
            _draw_arrow_path(path, x1, y1, x2, y2)
            path.stroke()

        elif ann.kind == TOOL_TEXT and ann.text:
            NSString.stringWithString_(ann.text).drawAtPoint_withAttributes_(
                NSMakePoint(x1, y1),
                {
                    NSForegroundColorAttributeName: RED_ANN,
                    NSFontAttributeName: NSFont.boldSystemFontOfSize_(18),
                },
            )

    # ── Souris ────────────────────────────────────────────────────────────────
    def mouseDown_(self, event):
        loc = self.convertPoint_fromView_(event.locationInWindow(), None)
        self._drag_start = (loc.x, loc.y)
        if self._tool == TOOL_TEXT:
            self._begin_text_input(loc.x, loc.y)

    def mouseDragged_(self, event):
        if self._tool == TOOL_TEXT or self._drag_start is None:
            return
        loc = self.convertPoint_fromView_(event.locationInWindow(), None)
        self._current = Annotation(self._tool, self._drag_start, (loc.x, loc.y))
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        if self._current:
            self._add_annotation(self._current)
            self._current = None
        self._drag_start = None

    # ── Clavier ───────────────────────────────────────────────────────────────
    def keyDown_(self, event):
        flags = event.modifierFlags()
        ctrl  = bool(flags & CTRL_MASK)
        shift = bool(flags & SHIFT_MASK)
        char  = (event.charactersIgnoringModifiers() or "").lower()

        if ctrl and char == "z":
            if shift:
                self._redo()
            else:
                self._undo()
        else:
            objc.super(CanvasView, self).keyDown_(event)

    # ── Undo / Redo ───────────────────────────────────────────────────────────
    def _add_annotation(self, ann):
        self._annotations.append(ann)
        self._redo_stack.clear()
        self.setNeedsDisplay_(True)

    def _undo(self):
        if self._annotations:
            self._redo_stack.append(self._annotations.pop())
            self.setNeedsDisplay_(True)

    def _redo(self):
        if self._redo_stack:
            self._annotations.append(self._redo_stack.pop())
            self.setNeedsDisplay_(True)

    # ── Texte ─────────────────────────────────────────────────────────────────
    def _begin_text_input(self, x, y):
        if self._text_field:
            self.confirmText()

        field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, 240, 34))
        field.setFont_(NSFont.boldSystemFontOfSize_(18))
        field.setTextColor_(RED_ANN)
        field.setBackgroundColor_(
            NSColor.colorWithRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.45))
        field.setDrawsBackground_(True)
        field.setBordered_(False)
        field.setStringValue_("")
        field.setPlaceholderString_("Tapez votre texte…")
        field.setTarget_(self)
        field.setAction_("confirmText")
        self.addSubview_(field)
        self.window().makeFirstResponder_(field)
        self._text_field = field
        self._text_pos   = (x, y)

    def confirmText(self):
        if not self._text_field:
            return
        text = self._text_field.stringValue()
        self._text_field.removeFromSuperview()
        self._text_field = None
        if text:
            self._add_annotation(Annotation(TOOL_TEXT, self._text_pos, self._text_pos, text))
        else:
            self.setNeedsDisplay_(True)
        self.window().makeFirstResponder_(self)

    # ── Export ────────────────────────────────────────────────────────────────
    def _rendered_pil(self):
        from PIL import Image, ImageDraw, ImageFont
        img  = Image.open(self._image_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
        except Exception:
            font = ImageFont.load_default()
        fill = (242, 56, 56, 255)
        lw   = 3
        for ann in self._annotations:
            x1, y1 = ann.p1
            x2, y2 = ann.p2
            if ann.kind == TOOL_RECT:
                draw.rectangle([min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2)],
                               outline=fill, width=lw)
            elif ann.kind == TOOL_ARROW:
                draw.line([x1, y1, x2, y2], fill=fill, width=lw)
                angle = math.atan2(y2 - y1, x2 - x1)
                L = 20
                pts = [(x2, y2)]
                for sign in (+1, -1):
                    pts.append((x2 - L*math.cos(angle - sign*0.42),
                                y2 - L*math.sin(angle - sign*0.42)))
                draw.polygon(pts, fill=fill)
            elif ann.kind == TOOL_TEXT and ann.text:
                draw.text((x1, y1), ann.text, fill=fill, font=font)
        return img.convert("RGB")

    @staticmethod
    def _copy_to_clipboard(img):
        tmp = tempfile.mktemp(suffix=".png")
        img.save(tmp, "PNG")
        subprocess.run([
            "osascript", "-e",
            f'set the clipboard to (read (POSIX file "{tmp}") as «class PNGf»)'
        ])
        os.unlink(tmp)

    def action_copy_delete(self):
        self.confirmText()
        img = self._rendered_pil()
        self._copy_to_clipboard(img)
        if os.path.exists(self._image_path):
            os.unlink(self._image_path)
        NSApp.terminate_(None)

    def action_copy_save(self):
        self.confirmText()
        img = self._rendered_pil()
        self._copy_to_clipboard(img)
        img.save(self._image_path, "PNG")
        NSApp.terminate_(None)

    def action_save(self):
        self.confirmText()
        self._rendered_pil().save(self._image_path, "PNG")
        NSApp.terminate_(None)


# ── Bouton stylé ──────────────────────────────────────────────────────────────
def make_button(label, action, target, frame, r, g, b):
    btn = NSButton.alloc().initWithFrame_(frame)
    btn.setTitle_(label)
    btn.setBezelStyle_(1)   # NSRoundedBezelStyle
    btn.setBezelColor_(NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0))
    btn.setTarget_(target)
    btn.setAction_(action)
    btn.setFont_(NSFont.systemFontOfSize_weight_(13, 0.4))
    return btn


# ── Delegate principal ────────────────────────────────────────────────────────
class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        ns_img = NSImage.alloc().initWithContentsOfFile_(IMAGE_PATH)
        sz     = ns_img.size()
        W, H   = int(sz.width), int(sz.height)

        TOOLBAR_H = 52
        BUTTONS_H = 56
        win_w = min(W, 1440)
        win_h = min(H + TOOLBAR_H + BUTTONS_H, 1020)

        style = (NSWindowStyleMaskTitled
                 | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable
                 | NSWindowStyleMaskFullSizeContent)

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, win_w, win_h), style, NSBackingStoreBuffered, False)
        self._window.center()
        self._window.setTitle_("Screenshot Editor")
        self._window.setTitleVisibility_(NSWindowTitleHidden)
        self._window.setTitlebarAppearsTransparent_(True)
        self._window.setMovableByWindowBackground_(True)
        self._window.setBackgroundColor_(DARK)

        for btn_type in (0, 1, 2):
            self._window.standardWindowButton_(btn_type).setHidden_(True)

        content = self._window.contentView()

        # ── Barre du bas (boutons d'action) ───────────────────────────
        bottom = ColorView.alloc().initWithFrame_color_(
            NSMakeRect(0, 0, win_w, BUTTONS_H), DARKER)
        content.addSubview_(bottom)

        pad   = 12
        bw    = (win_w - pad * 4) // 3
        bh    = 36
        by    = (BUTTONS_H - bh) // 2
        specs = [
            ("Copier & Supprimer",   "btnCopyDelete:", 0.85, 0.22, 0.22),
            ("Copier & Enregistrer", "btnCopySave:",   0.18, 0.48, 0.85),
            ("Enregistrer",          "btnSave:",        0.18, 0.72, 0.42),
        ]
        for i, (label, action, r, g, b) in enumerate(specs):
            bx  = pad + i * (bw + pad)
            btn = make_button(label, action, self,
                              NSMakeRect(bx, by, bw, bh), r, g, b)
            bottom.addSubview_(btn)

        # ── Barre du haut (outils + undo/redo) ────────────────────────
        canvas_h = win_h - TOOLBAR_H - BUTTONS_H
        toolbar  = ColorView.alloc().initWithFrame_color_(
            NSMakeRect(0, BUTTONS_H + canvas_h, win_w, TOOLBAR_H), DARKER)
        content.addSubview_(toolbar)

        seg = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(pad, 11, 270, 30))
        seg.setSegmentCount_(3)
        seg.setLabel_forSegment_("▭  Rectangle", 0)
        seg.setLabel_forSegment_("➜  Flèche",    1)
        seg.setLabel_forSegment_("T  Texte",      2)
        seg.setSelectedSegment_(0)
        seg.setSegmentStyle_(NSSegmentStyleRounded)
        seg.setTarget_(self)
        seg.setAction_("toolChanged:")
        toolbar.addSubview_(seg)

        # Boutons undo / redo
        for j, (lbl, sel) in enumerate([("↩ Undo", "btnUndo:"), ("↪ Redo", "btnRedo:")]):
            ub = NSButton.alloc().initWithFrame_(
                NSMakeRect(win_w - 180 + j * 88, 11, 78, 30))
            ub.setTitle_(lbl)
            ub.setBezelStyle_(4)
            ub.setTarget_(self)
            ub.setAction_(sel)
            ub.setFont_(NSFont.systemFontOfSize_(13))
            toolbar.addSubview_(ub)

        # ── Canvas ────────────────────────────────────────────────────
        self._canvas = CanvasView.alloc().initWithFrame_imagePath_(
            NSMakeRect(0, BUTTONS_H, win_w, canvas_h), IMAGE_PATH)
        content.addSubview_(self._canvas)

        self._window.makeKeyAndOrderFront_(None)
        self._window.makeFirstResponder_(self._canvas)
        NSApp.activateIgnoringOtherApps_(True)

    # ── Actions ───────────────────────────────────────────────────────────────
    def toolChanged_(self, sender):
        self._canvas.setTool_(sender.selectedSegment())

    def btnCopyDelete_(self, sender):
        self._canvas.action_copy_delete()

    def btnCopySave_(self, sender):
        self._canvas.action_copy_save()

    def btnSave_(self, sender):
        self._canvas.action_save()

    def btnUndo_(self, sender):
        self._canvas._undo()

    def btnRedo_(self, sender):
        self._canvas._redo()


def main():
    if not IMAGE_PATH or not os.path.exists(IMAGE_PATH):
        print("Usage: editor.py <image_path>")
        sys.exit(1)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()
