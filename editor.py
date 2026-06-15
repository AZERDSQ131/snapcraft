import math
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QApplication, QInputDialog, QScrollArea, QLabel
)
from PyQt6.QtCore import Qt, QPoint, QRect, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QPixmap, QPen, QFont, QPolygonF,
    QCursor, QKeySequence
)


RED = QColor(220, 38, 38)
PEN_WIDTH = 2


class AnnotationCanvas(QWidget):
    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self._bg = pixmap
        self._shapes: list[dict] = []
        self._tool = 'rect'
        self._color = QColor(RED)

        self._drawing = False
        self._p0: Optional[QPoint] = None
        self._p1: Optional[QPoint] = None
        self._pencil_pts: list[QPoint] = []

        logical_size = pixmap.size() / pixmap.devicePixelRatio()
        self.setFixedSize(logical_size)
        self.setMouseTracking(True)

    def set_tool(self, tool: str):
        self._tool = tool

    # ── paint ──────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(self.rect(), self._bg, self.rect())
        for shape in self._shapes:
            self._draw_shape(p, shape)
        self._draw_live(p)

    def _draw_live(self, p: QPainter):
        if not self._drawing or self._p0 is None or self._p1 is None:
            return
        pen = QPen(self._color, PEN_WIDTH, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._tool == 'rect':
            p.drawRect(QRect(self._p0, self._p1).normalized())
        elif self._tool == 'arrow':
            _draw_arrow(p, self._p0, self._p1)
        elif self._tool == 'pencil' and self._pencil_pts:
            for i in range(1, len(self._pencil_pts)):
                p.drawLine(self._pencil_pts[i - 1], self._pencil_pts[i])

    def _draw_shape(self, p: QPainter, shape: dict):
        color = shape.get('color', self._color)
        pen = QPen(color, PEN_WIDTH, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        t = shape['type']
        if t == 'rect':
            p.drawRect(shape['rect'])
        elif t == 'arrow':
            _draw_arrow(p, shape['start'], shape['end'])
        elif t == 'pencil':
            pts = shape['points']
            for i in range(1, len(pts)):
                p.drawLine(pts[i - 1], pts[i])
        elif t == 'text':
            p.setFont(QFont('.AppleSystemUIFont', 16, QFont.Weight.Bold))
            p.drawText(shape['point'], shape['text'])

    # ── mouse ──────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()

        if self._tool == 'text':
            text, ok = QInputDialog.getText(self, 'Texte', 'Entrez votre texte :')
            if ok and text.strip():
                self._shapes.append({'type': 'text', 'point': pos,
                                     'text': text, 'color': QColor(self._color)})
                self.update()
            return

        self._drawing = True
        self._p0 = pos
        self._p1 = pos
        if self._tool == 'pencil':
            self._pencil_pts = [pos]

    def mouseMoveEvent(self, event):
        if not self._drawing:
            return
        self._p1 = event.position().toPoint()
        if self._tool == 'pencil':
            self._pencil_pts.append(self._p1)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._drawing:
            return
        self._drawing = False
        pos = event.position().toPoint()
        p0 = self._p0

        if self._tool == 'rect':
            r = QRect(p0, pos).normalized()
            if r.width() > 3 or r.height() > 3:
                self._shapes.append({'type': 'rect', 'rect': r,
                                     'color': QColor(self._color)})
        elif self._tool == 'arrow':
            if (pos - p0).manhattanLength() > 5:
                self._shapes.append({'type': 'arrow', 'start': p0, 'end': pos,
                                     'color': QColor(self._color)})
        elif self._tool == 'pencil' and len(self._pencil_pts) > 1:
            self._shapes.append({'type': 'pencil',
                                 'points': list(self._pencil_pts),
                                 'color': QColor(self._color)})
            self._pencil_pts = []

        self._p0 = self._p1 = None
        self.update()

    # ── actions ────────────────────────────────────────────────────────────

    def undo(self):
        if self._shapes:
            self._shapes.pop()
            self.update()

    def render_result(self) -> QPixmap:
        ratio = self._bg.devicePixelRatio()
        result = QPixmap(self._bg.size())
        result.fill(Qt.GlobalColor.transparent)
        result.setDevicePixelRatio(ratio)
        p = QPainter(result)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(QPoint(0, 0), self._bg)
        for shape in self._shapes:
            s = dict(shape)
            s_color = s.get('color', self._color)
            pen = QPen(s_color, PEN_WIDTH, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            t = s['type']
            if t == 'rect':
                p.drawRect(s['rect'])
            elif t == 'arrow':
                _draw_arrow(p, s['start'], s['end'])
            elif t == 'pencil':
                pts = s['points']
                for i in range(1, len(pts)):
                    p.drawLine(pts[i - 1], pts[i])
            elif t == 'text':
                p.setFont(QFont('.AppleSystemUIFont', 16, QFont.Weight.Bold))
                p.drawText(s['point'], s['text'])
        p.end()
        return result


def _draw_arrow(p: QPainter, start: QPoint, end: QPoint, head: int = 14):
    p.drawLine(start, end)
    dx = end.x() - start.x()
    dy = end.y() - start.y()
    length = math.hypot(dx, dy)
    if length < 1:
        return
    angle = math.atan2(dy, dx)
    p1 = QPointF(end.x() - head * math.cos(angle - math.pi / 6),
                 end.y() - head * math.sin(angle - math.pi / 6))
    p2 = QPointF(end.x() - head * math.cos(angle + math.pi / 6),
                 end.y() - head * math.sin(angle + math.pi / 6))
    poly = QPolygonF([QPointF(end), p1, p2])
    p.setBrush(p.pen().color())
    p.drawPolygon(poly)
    p.setBrush(Qt.BrushStyle.NoBrush)


# ── Editor window ──────────────────────────────────────────────────────────────

DARK = "#1C1C1E"
DARK2 = "#2C2C2E"
DARK3 = "#3A3A3C"
ACCENT = "#FF3B30"
BLUE = "#007AFF"


class EditorWindow(QWidget):
    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.setWindowTitle("Annotation")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        self._canvas = AnnotationCanvas(pixmap)
        self._build_ui()
        self._size_window(pixmap)
        self.setStyleSheet(f"QWidget {{ background: {DARK}; color: white; "
                           f"font-family: -apple-system; }}")

    def _size_window(self, pixmap: QPixmap):
        screen = QApplication.primaryScreen().availableGeometry()
        img_w = int(pixmap.width() / pixmap.devicePixelRatio())
        img_h = int(pixmap.height() / pixmap.devicePixelRatio())
        w = min(img_w + 2, int(screen.width() * 0.92))
        h = min(img_h + 96, int(screen.height() * 0.88))
        self.resize(w, h)
        self.move(screen.x() + (screen.width() - w) // 2,
                  screen.y() + (screen.height() - h) // 2)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_toolbar())

        scroll = QScrollArea()
        scroll.setWidget(self._canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setStyleSheet(f"background: #141414; border: none;")
        root.addWidget(scroll, 1)

        root.addWidget(self._make_export_bar())

    # ── toolbar ──────────────────────────────────────────────────────────

    def _make_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(50)
        bar.setStyleSheet(f"background: {DARK2}; border-bottom: 1px solid {DARK3};")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(4)

        tools = [
            ('rect',   '▭',  'Rectangle (R)'),
            ('arrow',  '↗',  'Flèche (A)'),
            ('text',   'T',  'Texte (T)'),
            ('pencil', '✏',  'Crayon (P)'),
        ]

        self._tool_btns: dict[str, QPushButton] = {}
        for tid, icon, tip in tools:
            btn = QPushButton(icon)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setFixedSize(38, 34)
            btn.setStyleSheet(self._tool_btn_style())
            btn.clicked.connect(lambda _, t=tid: self._select_tool(t))
            layout.addWidget(btn)
            self._tool_btns[tid] = btn

        self._tool_btns['rect'].setChecked(True)

        layout.addStretch()

        undo_btn = QPushButton("↩  Annuler")
        undo_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: #AEAEB2;
                border: 1px solid {DARK3}; border-radius: 7px;
                padding: 4px 12px; font-size: 13px;
            }}
            QPushButton:hover {{ color: white; background: {DARK3}; }}
        """)
        undo_btn.clicked.connect(self._canvas.undo)
        layout.addWidget(undo_btn)

        return bar

    def _tool_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background: transparent; color: #AEAEB2;
                border: 1px solid transparent; border-radius: 7px;
                font-size: 17px;
            }}
            QPushButton:hover {{ background: {DARK3}; color: white; }}
            QPushButton:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
        """

    def _select_tool(self, tool: str):
        self._canvas.set_tool(tool)
        for tid, btn in self._tool_btns.items():
            btn.setChecked(tid == tool)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_R:
            self._select_tool('rect')
        elif key == Qt.Key.Key_A:
            self._select_tool('arrow')
        elif key == Qt.Key.Key_T:
            self._select_tool('text')
        elif key == Qt.Key.Key_P:
            self._select_tool('pencil')
        elif key == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.MetaModifier:
            self._canvas.undo()
        elif key == Qt.Key.Key_Escape:
            self.close()

    # ── export bar ───────────────────────────────────────────────────────

    def _make_export_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(54)
        bar.setStyleSheet(f"background: {DARK2}; border-top: 1px solid {DARK3};")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        layout.addStretch()

        def ghost_btn(label: str) -> QPushButton:
            b = QPushButton(label)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {DARK3}; color: white;
                    border: none; border-radius: 8px;
                    padding: 7px 16px; font-size: 13px;
                }}
                QPushButton:hover {{ background: #48484A; }}
            """)
            return b

        b1 = ghost_btn("📋  Copier & Fermer")
        b2 = ghost_btn("📋  Copier & Enregistrer")
        b3 = QPushButton("💾  Enregistrer")
        b3.setStyleSheet(f"""
            QPushButton {{
                background: {BLUE}; color: white;
                border: none; border-radius: 8px;
                padding: 7px 16px; font-size: 13px;
            }}
            QPushButton:hover {{ background: #0A84FF; }}
        """)

        b1.clicked.connect(self._export_copy)
        b2.clicked.connect(self._export_copy_save)
        b3.clicked.connect(self._export_save)

        for b in (b1, b2, b3):
            layout.addWidget(b)

        return bar

    # ── export actions ───────────────────────────────────────────────────

    def _desktop_path(self) -> str:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        return os.path.expanduser(f'~/Desktop/capture_{ts}.png')

    def _export_copy(self):
        QApplication.clipboard().setPixmap(self._canvas.render_result())
        self.close()

    def _export_copy_save(self):
        pix = self._canvas.render_result()
        QApplication.clipboard().setPixmap(pix)
        pix.save(self._desktop_path())
        self.close()

    def _export_save(self):
        self._canvas.render_result().save(self._desktop_path())
        self.close()
