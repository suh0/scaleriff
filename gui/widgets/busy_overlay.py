"""무거운 계산 동안 창 전체를 흐리게 덮고 스피너를 돌린다.

계산(work)은 QThread에서, 위젯 갱신(done)은 메인 스레드에서 실행한다.
오버레이가 입력을 막으므로 계산 중 타임라인을 다른 곳에서 건드리지 않는다.
"""
from __future__ import annotations

import traceback

from PyQt6.QtCore import Qt, QThread, QTimer, QRectF
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from gui import theme as T
from gui.anim import reduced_motion

SHOW_DELAY_MS = 120   # 이보다 빨리 끝나면 오버레이를 그리지 않는다(깜빡임 방지)
FRAME_MS = 33         # ≈30fps — 계산 스레드와 GIL 경합을 줄인다
BLUR_DIV = 12         # 축소 배율 — 클수록 더 흐림


def _sync() -> bool:
    """offscreen(자동 테스트)에선 동기 실행 — 기존 테스트가 결과를 바로 확인한다."""
    return QGuiApplication.platformName() == "offscreen"


class _Worker(QThread):
    def __init__(self, work):
        super().__init__()
        self._work = work
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self._work()
        except Exception:
            self.error = traceback.format_exc()


class BusyOverlay(QWidget):
    def __init__(self, win: QWidget, text: str):
        super().__init__(win)
        self._text = text
        self._bg = None
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        delay = QTimer(self)        # 오버레이와 함께 사라지는 지연 타이머
        delay.setSingleShot(True)
        delay.timeout.connect(self.reveal)
        delay.start(SHOW_DELAY_MS)
        self.setGeometry(win.rect())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.show()                 # 투명 상태로 즉시 입력만 막는다
        self.raise_()
        self.setFocus()
        self.grabKeyboard()

    def reveal(self):
        if not self.isVisible():    # 이미 끝남
            return
        win = self.parentWidget()
        pix = win.grab()
        small = pix.scaled(max(1, pix.width() // BLUR_DIV), max(1, pix.height() // BLUR_DIV),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        self._bg = small.scaled(pix.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        if not reduced_motion():
            self._timer.start()
        self.update()

    def close_overlay(self):
        self._timer.stop()
        self.releaseKeyboard()
        self.hide()
        self.deleteLater()

    def _tick(self):
        self._angle = (self._angle + 12) % 360
        self.update()

    def keyPressEvent(self, e):
        e.accept()

    def mousePressEvent(self, e):
        e.accept()

    def paintEvent(self, event):
        if self._bg is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(self.rect(), self._bg)
        scrim = QColor(T.BG_BASE)
        scrim.setAlpha(150)
        p.fillRect(self.rect(), scrim)
        c = self.rect().center()
        r = 18
        if not reduced_motion():
            pen = QPen(QColor(T.BORDER_ACTIVE), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(c.x() - r, c.y() - r - 16, 2 * r, 2 * r),
                      -self._angle * 16, 270 * 16)
        p.setPen(QColor(T.TEXT_PRIMARY))
        p.setFont(QFont(T.FONT_SANS, 11))
        p.drawText(QRectF(0, c.y() + r, self.width(), 30),
                   Qt.AlignmentFlag.AlignCenter, self._text)


def run_busy(widget: QWidget, work, done=None, text: str = "불러오는 중…"):
    """work()를 백그라운드에서 돌리고 끝나면 done(결과)을 메인 스레드에서 부른다."""
    if _sync():
        result = work()
        if done:
            done(result)
        return
    win = widget.window()
    overlay = BusyOverlay(win, text)
    worker = _Worker(work)

    def finish():
        overlay.close_overlay()
        worker.deleteLater()
        win._busy_worker = None
        if worker.error:
            print(worker.error)
            if hasattr(win, "statusBar"):
                win.statusBar().showMessage("처리 중 오류가 났어요: "
                                            + worker.error.strip().splitlines()[-1])
        elif done:
            done(worker.result)

    worker.finished.connect(finish)
    win._busy_worker = worker      # 실행 중 스레드 객체가 수거되지 않게 참조 유지
    worker.start()
