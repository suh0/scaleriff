"""연주화면 상단 가운데 코드 표시 — 현재 코드(크게)·스케일명(작게), 다음 코드 예고·밀어내기."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QWidget

from gui import theme as T


class ChordHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(360, 150)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._chords = ("", "", "", "", 0.0, 1.0)
        self._detour: set[str] = set()   # 키 밖 코드 이름 — 옅은 주황으로

    def set_detour(self, names):
        self._detour = set(names)
        self.update()

    def set_chords(self, cur, kind, nxt, prev, grow, push):
        """cur/kind=현재 코드·스케일, nxt=다음 코드, prev=방금 밀려나는 코드.
        grow 0→1: 다음 코드가 커짐 · push 0→1: 바뀐 직후 새 코드가 내려오며 prev를 밀어냄."""
        self._chords = (cur, kind, nxt, prev, grow, push)
        self.update()

    def paintEvent(self, event):
        cur, kind, nxt, prev, grow, push = self._chords
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, w = self.height(), self.width()
        big = h * 0.42
        mid_y, top_y, low_y = h * 0.48, h * 0.12, h * 1.1
        ease = 1 - (1 - push) ** 3

        def text(name, size, y, alpha, spacing=0.0, bold=True):
            if not name or size < 1 or alpha <= 0:
                return
            f = QFont(T.FONT_SANS_EN)
            f.setBold(bold)
            f.setPixelSize(int(size))
            if spacing:
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
            p.setFont(f)
            c = QColor(T.DETOUR if name in self._detour else T.TEXT_PRIMARY)
            c.setAlphaF(alpha)
            p.setPen(c)
            p.drawText(QRectF(0, y - size, w, size * 2), Qt.AlignmentFlag.AlignCenter, name)

        small = big * (0.32 + 0.2 * grow)
        # 밀려나는 이전 코드: 중앙 → 아래로, 페이드
        text(prev, big, mid_y + (low_y - mid_y) * ease, 1 - ease)
        # 현재 코드: 다음 코드 자리(위·작게) → 중앙·크게
        size = small + (big - small) * ease if prev else big
        y = top_y + (mid_y - top_y) * ease if prev else mid_y
        text(cur, size, y, 0.55 + 0.45 * ease if prev else 1.0)
        if kind and ease >= 1:
            text(kind, big * 0.26, mid_y + big * 0.8, 0.8, spacing=1, bold=False)   # "근음 N번 · 스케일"
        # 다음 코드: 위에서 작게 → 점점 커짐(push 동안엔 숨김)
        if ease >= 1:
            text(nxt, small, top_y, 0.35 + 0.3 * grow)
