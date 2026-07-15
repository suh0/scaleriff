"""패스 요약 카드 (정의서 §7.5·§6) — 패스 경계에서 수 초 표시 후 페이드아웃.

문구 원칙: 스케일 밖 음은 "스케일 밖"(중립) — "틀림" 금지.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation

from analyze.theory import pc_name
from gui import theme as T

SHOW_MS = 4500     # 표시 시간
FADE_MS = 400      # 페이드아웃


class PassCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()
        self.setStyleSheet(
            f"QFrame{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_DEFAULT};"
            f"border-radius:12px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(4)
        self.title_lbl = QLabel("")
        self.title_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:14px;font-weight:700;border:none;")
        lay.addWidget(self.title_lbl)
        self.body_lbl = QLabel("")
        self.body_lbl.setStyleSheet(
            f"color:{T.TEXT_BODY};font-family:'{T.FONT_MONO}';"
            "font-size:13px;border:none;")
        lay.addWidget(self.body_lbl)

        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(FADE_MS)
        self._anim.finished.connect(self.hide)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

    def show_summary(self, s, trend: list[int]):
        """s: player.scoring.PassSummary"""
        def pct(p, h, t):
            return f"{p}%  ({h}/{t})" if p is not None else "–"
        if s.riff_total:   # 리프연습 모드(§7.5 2차) = 리프 일치율만
            lines = [f"리프 일치율          {pct(s.riff_pct(), s.riff_hits, s.riff_total)}"]
        else:
            lines = [
                f"오른손 스케일 적중   {pct(s.right_pct(), s.right_hits, s.right_total)}",
                f"왼손 코드톤 적중     {pct(s.left_pct(), s.left_hits, s.left_total)}",
                f"코드톤 착지          {s.landing_hits}/{s.landing_opps}",
            ]
            if s.top_out_pc() is not None:
                lines.append(f"스케일 밖 최다        {pc_name(s.top_out_pc())}")
        if trend:
            lines.append("추이  " + " → ".join(f"{p}" for p in trend[-5:]) + "%")
        self.title_lbl.setText(f"패스 {s.number} 요약")
        self.body_lbl.setText("\n".join(lines))

        self._anim.stop()
        self._timer.stop()
        self._fx.setOpacity(1.0)
        self.adjustSize()
        p = self.parentWidget()
        if p:   # 부모 중앙 상단(HUD 아래쯤)에 띄움
            self.move((p.width() - self.width()) // 2, 120)
        self.raise_()
        self.show()
        self._timer.start(SHOW_MS)

    def _fade_out(self):
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()
