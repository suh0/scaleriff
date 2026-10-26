"""연주화면 첫 진입 가이드 — 화면을 어둡게 덮고 한 부분씩 밝혀 설명, [다음]으로 넘긴다.

steps: [(제목, 본문, 대상 영역 함수 | None)] — 대상 함수는 오버레이 좌표 QRect 목록을 돌려준다
(None이면 가운데 카드만). 끝까지 넘기거나 건너뛰면 finished 후 스스로 닫힌다.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from gui import theme as T

CARD_W = 400
HOLE_PAD = 10      # 밝힌 영역 여백
GAP = 18           # 밝힌 영역과 카드 사이


class PlayGuide(QWidget):
    finished = pyqtSignal()

    def __init__(self, parent: QWidget, steps):
        super().__init__(parent)
        self._steps = steps
        self._i = 0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.card = QFrame(self)
        self.card.setObjectName("guideCard")
        self.card.setFixedWidth(CARD_W)
        self.card.setStyleSheet(
            f"QFrame#guideCard{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_DEFAULT};"
            f"border-radius:14px;}} QFrame#guideCard QLabel{{font-family:'{T.FONT_SANS}';}}")
        v = QVBoxLayout(self.card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(10)
        self.count_lbl = QLabel()
        self.count_lbl.setStyleSheet(f"color:{T.TEXT_DIM};font-size:11px;letter-spacing:2px;border:none;")
        self.title_lbl = QLabel()
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:17px;font-weight:700;border:none;")
        self.body_lbl = QLabel()
        self.body_lbl.setWordWrap(True)
        self.body_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.body_lbl.setStyleSheet(f"color:{T.TEXT_BODY};font-size:13px;line-height:150%;border:none;")
        for w in (self.count_lbl, self.title_lbl, self.body_lbl):
            v.addWidget(w)
        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        self.skip_btn = QPushButton("건너뛰기")
        self.skip_btn.setStyleSheet(T.qss_ghost_btn())
        self.skip_btn.clicked.connect(self.finish)
        self.next_btn = QPushButton()
        self.next_btn.setStyleSheet(T.qss_primary_btn())
        self.next_btn.clicked.connect(self.next)
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        row.addWidget(self.next_btn)
        v.addLayout(row)
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        self._show_step()

    # ── 진행 ─────────────────────────────────────────────────────
    def next(self):
        if self._i + 1 >= len(self._steps):
            self.finish()
            return
        self._i += 1
        self._show_step()

    def finish(self):
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def _show_step(self):
        title, body, _ = self._steps[self._i]
        last = self._i + 1 == len(self._steps)
        self.count_lbl.setText(f"{self._i + 1} / {len(self._steps)}")
        self.title_lbl.setText(title)
        self.body_lbl.setText(body)
        self.next_btn.setText("연주 시작" if last else "다음 →")
        self.skip_btn.setVisible(not last)
        self.relayout()
        self.next_btn.setFocus()

    def _holes(self) -> list[QRect]:
        target = self._steps[self._i][2]
        return [r.adjusted(-HOLE_PAD, -HOLE_PAD, HOLE_PAD, HOLE_PAD) for r in (target() if target else [])]

    def relayout(self):
        """창 크기 변화·단계 변경 시 카드를 밝힌 영역 아래(공간 없으면 위, 대상 없으면 가운데)에 둔다."""
        self.setGeometry(self.parentWidget().rect())
        self.card.adjustSize()
        cw, ch = self.card.width(), self.card.height()
        holes = self._holes()
        if not holes:
            x, y = (self.width() - cw) // 2, (self.height() - ch) // 2
        else:
            box = holes[0]
            for r in holes[1:]:
                box = box.united(r)
            x = box.center().x() - cw // 2
            y = box.bottom() + GAP if box.bottom() + GAP + ch <= self.height() - 12 else box.top() - GAP - ch
            if y < 12:             # 위아래 모두 좁으면(큰 대상) 대상 안쪽 위에 얹는다
                y = box.top() + GAP
        self.card.move(max(12, min(x, self.width() - cw - 12)), max(12, min(y, self.height() - ch - 12)))
        self.update()

    # ── 그리기·입력 ──────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        holes = QPainterPath()
        for r in self._holes():
            holes.addRoundedRect(QRectF(r), 12, 12)
        p.fillPath(shade.subtracted(holes), QColor(5, 8, 12, 190))
        p.setPen(QPen(QColor(T.BORDER_ACTIVE), 2))
        p.drawPath(holes)

    def mousePressEvent(self, e):
        e.accept()        # 가이드 중에는 아래 화면을 조작하지 않는다

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Right, Qt.Key.Key_Space):
            self.next()
        elif e.key() == Qt.Key.Key_Escape:
            self.finish()
        else:
            e.accept()
