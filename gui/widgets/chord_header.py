"""연주화면 상단 가운데 코드 표시 — 현재 코드(크게), 다음 코드 예고·밀어내기."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from gui import theme as T

BASE = 100                   # 글자 외곽선을 이 크기로 한 번 만들고 배율로 키운다(정수 px 글꼴은 커질 때 1px씩 튐)
NEXT_MIN, NEXT_MAX = 0.32, 0.52   # 다음 코드 크기(큰 글자 대비): 예고 시작 → 바뀌기 직전 = 밀어내기 시작 크기
NEXT_ALPHA = (0.35, 0.65)         # 다음 코드 불투명도: 예고 시작 → 바뀌기 직전


class ChordHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(360, 150)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._chords = ("", "", "", 0.0, 1.0)
        self._detour: set[str] = set()   # 키 밖 코드 이름 — 옅은 주황으로
        self._paths = {}                 # (글자, 굵게, 자간) → BASE 크기 외곽선(가운데 정렬)
        self.mirror = None               # GL 무대가 대신 그릴 때 바뀜 알림() — 이 위젯 자체는 투명(HUD 창 갱신 없음)

    def set_detour(self, names):
        self._detour = set(names)
        self.update()

    def set_chords(self, cur, nxt, prev, grow, push):
        """cur=현재 코드, nxt=다음 코드, prev=방금 밀려나는 코드.
        grow 0→1: 다음 코드가 커짐 · push 0→1: 바뀐 직후 새 코드가 내려오며 prev를 밀어냄."""
        chords = (cur, nxt, prev, grow, push)
        if chords != self._chords:          # 바뀔 때만(재생 틱마다 같은 값이면 HUD 창을 다시 그리지 않음)
            self._chords = chords
            self.update()

    def update(self, *args):
        if self.mirror is not None:      # GL 무대가 그림 → HUD 창(레이어드 창)을 다시 그리지 않는다
            self.mirror()
        else:
            super().update(*args)

    def paintEvent(self, event):
        if self.mirror is None:
            self.paint(QPainter(self))

    def paint(self, p):
        """코드 표시를 p(위젯 크기 좌표)에 — 위젯 paintEvent와 GL 무대(그림으로 떠서 붙임)가 같이 쓴다."""
        cur, nxt, prev, grow, push = self._chords
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, w = self.height(), self.width()
        big = h * 0.42
        mid_y, top_y, low_y = h * 0.48, h * 0.12, h * 1.1
        ease = 1 - (1 - push) ** 3

        def text(name, size, y, alpha, spacing=0.0, bold=True):
            """가운데 (w/2, y)에 size px 글자 — 외곽선을 배율로 그려 크기·위치가 소수점까지 매끄럽다."""
            if not name or size < 1 or alpha <= 0:
                return
            c = QColor(T.DETOUR if name in self._detour else T.TEXT_PRIMARY)
            c.setAlphaF(min(1.0, alpha))
            p.save()
            p.translate(w / 2, y)
            p.scale(size / BASE, size / BASE)
            p.fillPath(self._path(name, bold, spacing * BASE / size), c)
            p.restore()

        small = big * (NEXT_MIN + (NEXT_MAX - NEXT_MIN) * grow)
        # 밀려나는 이전 코드: 중앙 → 아래로, 페이드
        text(prev, big, mid_y + (low_y - mid_y) * ease, 1 - ease)
        # 현재 코드: 다음 코드가 있던 자리·크기·밝기(바뀌기 직전 그대로)에서 → 중앙·크게. 끊김 없이 이어진다
        size = big * NEXT_MAX + big * (1 - NEXT_MAX) * ease if prev else big
        y = top_y + (mid_y - top_y) * ease if prev else mid_y
        text(cur, size, y, NEXT_ALPHA[1] + (1 - NEXT_ALPHA[1]) * ease if prev else 1.0)
        # 다음 코드: 위에서 작게 → 점점 커짐. 밀어내기 동안엔 위 자리가 비워진 뒤 서서히 나타남
        text(nxt, small, top_y, (NEXT_ALPHA[0] + (NEXT_ALPHA[1] - NEXT_ALPHA[0]) * grow) * ease ** 2)

    def _path(self, name, bold, spacing):
        key = (name, bold, round(spacing, 2))
        path = self._paths.get(key)
        if path is None:
            if len(self._paths) > 64:
                self._paths.clear()
            f = QFont(T.FONTS)
            f.setBold(bold)
            f.setPixelSize(BASE)
            if spacing:
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
            fm = QFontMetricsF(f)
            path = self._paths[key] = QPainterPath()
            # 글자 줄 상자의 세로 가운데 = (0, 0) — 예전 AlignCenter와 같은 자리
            path.addText(-fm.horizontalAdvance(name) / 2, (fm.ascent() - fm.descent()) / 2, f, name)
        return path
