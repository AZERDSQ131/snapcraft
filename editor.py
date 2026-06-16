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
    NSBezierPath, NSImage, NSTextField, NSFont,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable, NSBackingStoreBuffered,
    NSApplicationActivationPolicyRegular,
    NSSegmentedControl, NSSegmentStyleRounded,
)
from Foundation import NSObject, NSMakeRect, NSMakePoint

IMAGE_PATH = sys.argv[1] if len(sys.argv) > 1 else None

TOOL_RECT  = 0
TOOL_ARROW = 1
TOOL_TEXT  = 2

RED = NSColor.colorWithRed_green_blue_alpha_(0.9, 0.1, 0.1, 1.0)


class Annotation:
    def __init__(self, kind, p1, p2, text=""):
        self.kind = kind
        self.p1   = p1
        self.p2   = p2
        self.text = text


def draw_arrow(path, x1, y1, x2, y2):
    path.moveToPoint_(NSMakePoint(x1, y1))
    path.lineToPoint_(NSMakePoint(x2, y2))
    angle = math.atan2(y2 - y1, x2 - x1)
    L = 18
    for sign in (+1, -1):
        ax = x2 - L * math.cos(angle - sign * 0.45)
        ay = y2 - L * math.sin(angle - sign * 0.45)
        path.moveToPoint_(NSMakePoint(x2, y2))
        path.lineToPoint_(NSMakePoint(ax, ay))


class CanvasView(NSView):
    def initWithFrame_imagePath_(self, frame, image_path):
        self = objc.super(CanvasView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._image_path  = image_path
        # Chargement natif rapide — pas de conversion PIL au démarrage
        self._ns_image    = NSImage.alloc().initWithContentsOfFile_(image_path)
        self._annotations = []
        self._current     = None
        self._tool        = TOOL_RECT
        self._drag_start  = None
        self._text_field  = None
        self._text_pos    = (0, 0)
        return self

    def isFlipped(self):
        return True

    def setTool_(self, tool):
        self._tool = tool

    def drawRect_(self, rect):
        self._ns_image.drawInRect_(self.bounds())
        RED.setStroke()
        RED.setFill()
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
            draw_arrow(path, x1, y1, x2, y2)
            path.stroke()

        elif ann.kind == TOOL_TEXT and ann.text:
            from AppKit import NSString
            NSString.stringWithString_(ann.text).drawAtPoint_withAttributes_(
                NSMakePoint(x1, y1),
                {"NSColor": RED, "NSFont": NSFont.boldSystemFontOfSize_(18)},
            )

    # ── Souris ────────────────────────────────────────────────────────────
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
            self._annotations.append(self._current)
            self._current = None
            self.setNeedsDisplay_(True)
        self._drag_start = None

    # ── Texte ─────────────────────────────────────────────────────────────
    def _begin_text_input(self, x, y):
        if self._text_field:
            self.confirmText()

        field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, 220, 32))
        field.setFont_(NSFont.boldSystemFontOfSize_(18))
        field.setTextColor_(RED)
        field.setDrawsBackground_(False)
        field.setBordered_(True)
        field.setStringValue_("")
        field.setPlaceholderString_("Texte…")
        # Entrée → confirmText
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
        if text:
            self._annotations.append(
                Annotation(TOOL_TEXT, self._text_pos, self._text_pos, text))
        self._text_field.removeFromSuperview()
        self._text_field = None
        self.setNeedsDisplay_(True)

    # ── Export ────────────────────────────────────────────────────────────
    def _rendered_pil(self):
        from PIL import Image, ImageDraw, ImageFont
        img  = Image.open(self._image_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
        except Exception:
            font = ImageFont.load_default()
        fill = (230, 25, 25, 255)
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
                L = 18
                pts = [(x2, y2)]
                for sign in (+1, -1):
                    pts.append((x2 - L*math.cos(angle - sign*0.45),
                                y2 - L*math.sin(angle - sign*0.45)))
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


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        ns_img = NSImage.alloc().initWithContentsOfFile_(IMAGE_PATH)
        sz     = ns_img.size()
        W, H   = int(sz.width), int(sz.height)

        TOOLBAR_H = 50
        BUTTONS_H = 50
        win_w = min(W, 1400)
        win_h = min(H + TOOLBAR_H + BUTTONS_H, 1000)

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(100, 100, win_w, win_h),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("Screenshot Editor")
        content  = self._window.contentView()

        # ── Outils ────────────────────────────────────────────────────
        seg = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(8, win_h - TOOLBAR_H + 10, 260, 30))
        seg.setSegmentCount_(3)
        seg.setLabel_forSegment_("▭  Rectangle", 0)
        seg.setLabel_forSegment_("➜  Flèche",    1)
        seg.setLabel_forSegment_("T  Texte",      2)
        seg.setSelectedSegment_(0)
        seg.setSegmentStyle_(NSSegmentStyleRounded)
        seg.setTarget_(self)
        seg.setAction_("toolChanged:")
        content.addSubview_(seg)
        self._seg = seg

        # ── Canvas ────────────────────────────────────────────────────
        canvas_h = win_h - TOOLBAR_H - BUTTONS_H
        self._canvas = CanvasView.alloc().initWithFrame_imagePath_(
            NSMakeRect(0, BUTTONS_H, win_w, canvas_h), IMAGE_PATH)
        content.addSubview_(self._canvas)

        # ── Boutons ───────────────────────────────────────────────────
        btn_w = win_w // 3
        for i, (label, action) in enumerate([
            ("Copier & Supprimer",  "btnCopyDelete:"),
            ("Copier & Enregistrer","btnCopySave:"),
            ("Enregistrer",         "btnSave:"),
        ]):
            btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(i * btn_w, 6, btn_w - 8, 38))
            btn.setTitle_(label)
            btn.setBezelStyle_(4)
            btn.setTarget_(self)
            btn.setAction_(action)
            content.addSubview_(btn)

        self._window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    def toolChanged_(self, sender):
        self._canvas.setTool_(sender.selectedSegment())

    def btnCopyDelete_(self, sender):
        self._canvas.action_copy_delete()

    def btnCopySave_(self, sender):
        self._canvas.action_copy_save()

    def btnSave_(self, sender):
        self._canvas.action_save()


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
