"""리프 생성 창 — 학습 설정 조건(자유: 스케일 안 / 착지음: 목표·음 개수)으로 구간 리프 생성.

다시 만들기 = 다른 변주, 확정 = seg.example 유지(리프연습), 취소 = 이전 리프 복원.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from ml.generate import bake_progression
from gui import theme as T
from gui.widgets.riff_roll import RiffRoll

GOAL_KR = {"root": "1도", "third": "3도", "seventh": "7도", "chord_tone": "코드톤"}


class RiffDialog(QDialog):
    def __init__(self, tl, model, start_sec: float, end_sec: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("리프 생성")
        self.setStyleSheet(f"QDialog{{background:{T.BG_BASE};}}")
        self.setMinimumWidth(640)
        self.tl, self.model = tl, model
        self.span = (start_sec, end_sec)
        self.variant = 0
        self._saved = [list(seg.example) for seg in tl.segments]
        lay = QVBoxLayout(self)
        p = tl.practice
        if p.get("method") == "landing":
            count = p.get("count")
            cond = f"착지음 {GOAL_KR[p['goal']]}" + (
                "" if not count else f" · 코드당 {count[0]}음" if count[0] == count[1]
                else f" · 코드당 {count[0]}~{count[1]}음")
        else:
            cond = "자유연습 · 스케일 안의 음"
        scale = p.get("scale", {}).get("name", "")
        self.info = QLabel(f"{scale} · {cond}")
        self.info.setStyleSheet(f"color:{T.TEXT_BODY};font-size:13px;")
        lay.addWidget(self.info)
        self.roll = RiffRoll()
        lay.addWidget(self.roll)
        row = QHBoxLayout()
        row.addStretch(1)
        self.regen_btn = QPushButton("다시 만들기")
        self.cancel_btn = QPushButton("취소")
        self.ok_btn = QPushButton("확정 ▶")
        for btn in (self.regen_btn, self.cancel_btn):
            btn.setStyleSheet(T.qss_ghost_btn())
            row.addWidget(btn)
        self.ok_btn.setStyleSheet(T.qss_primary_btn())
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self.regen_btn.clicked.connect(self.regenerate)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)
        self._generate()

    def _generate(self):
        p = self.tl.practice
        goal = p.get("goal") if p.get("method") == "landing" else None
        count = p.get("count")
        result = bake_progression(self.tl, self.model, *self.span, goal, self.variant,
                                  count=tuple(count) if count else None)
        b0 = self.tl.beat_at(self.span[0])
        bpb = self.tl.time_sig_beats()
        notes = [{"midi": n["midi"], "beat_pos": self.tl.beat_at(n["start_sec"]) - b0,
                  "dur_beats": self.tl.beats_between(n["start_sec"], n["start_sec"] + n["duration_sec"])}
                 for n in result["notes"]]
        scale = p.get("scale") or {}
        bars = max(1, round(self.tl.beats_between(*self.span) / bpb))
        self.roll.set_riff(notes, scale.get("note_set", []), [], bpb, bars, scale.get("root", 0))

    def regenerate(self):
        self.variant += 1
        self._generate()

    def reject(self):
        for seg, ex in zip(self.tl.segments, self._saved):
            seg.example = ex
        super().reject()
