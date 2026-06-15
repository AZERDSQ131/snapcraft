import subprocess
import tempfile
import os
from typing import Optional
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPixmap, QPen, QCursor


class FullScreenCapture:
    @staticmethod
    def capture() -> Optional[QPixmap]:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            tmpfile = f.name

        result = subprocess.run(
            ['screencapture', '-x', '-t', 'png', tmpfile],
            capture_output=True
        )

        if result.returncode == 0 and os.path.exists(tmpfile):
            pixmap = QPixmap(tmpfile)
            os.unlink(tmpfile)
            screen = QApplication.primaryScreen()
            pixmap.setDevicePixelRatio(screen.devicePixelRatio())
            return pixmap

        return None


class RegionCapture(QWidget):
    captured = pyqtSignal(QPixmap)

    def __init__(self):
        super().__init__()
        self._start = QPoint()
        self._end = QPoint()
        self._drawing = False
        self._bg: Optional[QPixmap] = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def start_capture(self):
        self._bg = FullScreenCapture.capture()
        if self._bg is None:
            self.close()
            return

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.show()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._bg:
            painter.drawPixmap(self.rect(), self._bg, self.rect())

        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if self._drawing and not self._start.isNull() and not self._end.isNull():
            rect = QRect(self._start, self._end).normalized()

            if self._bg:
                painter.drawPixmap(rect, self._bg, rect)

            pen = QPen(QColor(255, 255, 255, 200), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

            info = f"{rect.width()} × {rect.height()}"
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect.x(), max(rect.y() - 6, 14), info)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._end = self._start
            self._drawing = True

    def mouseMoveEvent(self, event):
        if self._drawing:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._end = event.position().toPoint()
            self._drawing = False
            self._finish()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def _finish(self):
        rect = QRect(self._start, self._end).normalized()
        if rect.width() < 5 or rect.height() < 5:
            self.close()
            return

        self.hide()
        QApplication.processEvents()

        if self._bg:
            cropped = self._bg.copy(rect)
            self.close()
            self.captured.emit(cropped)
        else:
            self.close()
