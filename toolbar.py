from typing import Optional
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QApplication
from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QCursor

from capture import FullScreenCapture, RegionCapture
from editor import EditorWindow


class ToolbarWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._editor: Optional[EditorWindow] = None
        self._region_sel: Optional[RegionCapture] = None
        self._drag_pos: Optional[QPoint] = None
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool              # invisible dans le Dock/Mission Control
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.setStyleSheet("""
            QWidget#toolbar {
                background: rgba(28, 28, 30, 235);
                border-radius: 14px;
            }
        """)

        container = QWidget(self)
        container.setObjectName("toolbar")
        inner = QHBoxLayout(container)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(6)

        btn_style = """
            QPushButton {
                background: rgba(58, 58, 60, 200);
                color: white;
                border: none;
                border-radius: 9px;
                padding: 7px 14px;
                font-size: 13px;
                font-family: -apple-system;
            }
            QPushButton:hover  { background: rgba(80, 80, 84, 230); }
            QPushButton:pressed { background: rgba(28, 28, 30, 255); }
        """
        close_style = """
            QPushButton {
                background: rgba(58, 58, 60, 200);
                color: #AEAEB2;
                border: none;
                border-radius: 9px;
                padding: 7px 10px;
                font-size: 13px;
                font-family: -apple-system;
            }
            QPushButton:hover { background: rgba(80, 80, 84, 230); color: white; }
        """

        btn_full   = QPushButton("🖥  Plein écran")
        btn_region = QPushButton("✂️  Sélection")
        btn_close  = QPushButton("✕")

        for btn in (btn_full, btn_region):
            btn.setStyleSheet(btn_style)
        btn_close.setStyleSheet(close_style)
        btn_close.setFixedWidth(34)

        btn_full.clicked.connect(self._capture_full)
        btn_region.clicked.connect(self._capture_region)
        btn_close.clicked.connect(self.hide)

        inner.addWidget(btn_full)
        inner.addWidget(btn_region)
        inner.addWidget(btn_close)

        layout.addWidget(container)
        self.adjustSize()

    # ── visibilité ────────────────────────────────────────────────────────

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            # Centré sur le curseur
            pos = QCursor.pos()
            self.move(pos.x() - self.width() // 2,
                      pos.y() - self.height() // 2 - 20)
            self.show()
            self.raise_()
            self.activateWindow()

    # ── captures ──────────────────────────────────────────────────────────

    def _capture_full(self):
        self.hide()
        QTimer.singleShot(150, self._do_full)

    def _do_full(self):
        pixmap = FullScreenCapture.capture()
        if pixmap:
            self._open_editor(pixmap)

    def _capture_region(self):
        self.hide()
        QTimer.singleShot(150, self._do_region)

    def _do_region(self):
        self._region_sel = RegionCapture()
        self._region_sel.captured.connect(self._open_editor)
        self._region_sel.start_capture()

    def _open_editor(self, pixmap):
        self._editor = EditorWindow(pixmap)
        self._editor.show()

    # ── drag de la barre ──────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (event.globalPosition().toPoint()
                              - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, event):
        if (event.buttons() == Qt.MouseButton.LeftButton
                and self._drag_pos is not None):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
