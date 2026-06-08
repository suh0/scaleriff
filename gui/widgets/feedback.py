"""피드백 영역 — ScaleRiff (디자인 스펙). 채점 없음.

마지막 친 음: 음이름 + 분류(코드톤/스케일음/스케일 밖) + 기능 라벨.
"틀린 음 없어요" 톤 상시 노출. 분류색은 히트 램프와 맞춤.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from analyze.theory import function_label, pc_name
from gui import theme as T

CHORD_TONE = ("코드톤 — 가장 안정적", T.HEAD)
SCALE_TONE = ("스케일음 — 잘 어울려요", T.GOLD_LIGHT)
OUT_TONE = ("스케일 밖 — 색다른 맛, 다음 음으로 풀어주면 멋져요", "#c8642a")


def _classify(pc, note_set, chord_tones):
    if pc in chord_tones:
        return CHORD_TONE
    if pc in note_set:
        return SCALE_TONE
    return OUT_TONE


class FeedbackPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        self.title = QLabel("쳐 보세요 — 틀린 음은 없어요 🎵")
        self.title.setStyleSheet(f"color:{T.TEXT_BODY};font-size:12px;")
        lay.addWidget(self.title)

        row = QHBoxLayout()
        self.note_lbl = QLabel("—")
        self.note_lbl.setStyleSheet(
            f"color:{T.HEAD};font-family:'{T.FONT_MONO}';font-size:22px;font-weight:bold;")
        self.note_lbl.setMinimumWidth(64)
        row.addWidget(self.note_lbl)

        self.kind_lbl = QLabel("")
        self.kind_lbl.setStyleSheet("font-size:15px;font-weight:bold;")
        row.addWidget(self.kind_lbl, 1)
        lay.addLayout(row)

        self.func_lbl = QLabel("")
        self.func_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
        lay.addWidget(self.func_lbl)

    def show_note(self, midi, chord, note_set, chord_tones):
        pc = midi % 12
        self.note_lbl.setText(pc_name(pc))
        text, color = _classify(pc, set(note_set), set(chord_tones))
        self.kind_lbl.setText(text)
        self.kind_lbl.setStyleSheet(f"color:{color};font-size:15px;font-weight:bold;")
        if chord is not None:
            self.func_lbl.setText(f"기능: {function_label(pc, chord)}  (코드 {chord.name})")

    def reset(self):
        self.note_lbl.setText("—")
        self.kind_lbl.setText("")
        self.func_lbl.setText("")
