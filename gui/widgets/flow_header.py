"""준비부터 연주까지 현재 위치를 알리는 읽기 전용 단계 표시."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from gui import theme as T


class FlowHeader(QWidget):
    steps = ("곡 선택", "분석", "박자 조정", "코드 편집", "리프 확인", "연주")

    def __init__(self, stage=0, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 6)
        row.setSpacing(10)
        self.labels = []
        for text in self.steps:
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(label, 1)
            self.labels.append(label)
        self.set_stage(stage)

    def set_stage(self, stage):
        self.stage = stage
        for index, (text, label) in enumerate(zip(self.steps, self.labels)):
            label.setText(f"{index + 1}  {text}")
            label.setToolTip(f"{text}: {'완료' if index < stage else '현재 단계' if index == stage else '다음 단계'}")
            label.setStyleSheet(
                f"color:{T.BORDER_ACTIVE if index == stage else T.TEXT_MUTED if index < stage else T.TEXT_DIM};"
                f"font-size:11px;font-weight:{700 if index == stage else 500};padding:5px 0;"
                f"border-bottom:2px solid {T.BORDER_ACTIVE if index == stage else T.BORDER_SUBTLE};")
        self.setAccessibleName(f"현재 단계: {self.steps[stage]}")
