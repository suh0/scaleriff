"""리프 생성 창 — 곡 스케일 2마디 리프 + 디투어 마디용 1마디 리프를 만든다(학습 설정 조건 적용).

리프 수 = 패턴 수(최소) + 사용자가 늘린 만큼 자주 나오는 패턴에 변형 추가.
패턴 목록 클릭 = 공유 롤의 음표만 교체, 듣기 = 선택 리프를 원곡 템포로 재생,
다시 만들기 = 선택 리프만 다른 변주, 확정 = 모든 등장 구간에 변형을 순환 배정(코드 근음에 맞춰 스케일 도수 이동), 취소 = 이전 리프 복원.
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QSpinBox, QListWidget)

from ml.generate import bake_progression, chord_patterns, allocate, write_examples, transpose_riff
from gui import theme as T
from gui.widgets.riff_roll import RiffRoll
from player.note_synth import shared_player

GOAL_KR = {"root": "1도", "third": "3도", "seventh": "7도", "chord_tone": "코드톤"}


class RiffDialog(QDialog):
    def __init__(self, tl, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("리프 생성")
        self.setStyleSheet(f"QDialog{{background:{T.BG_BASE};}}")
        self.setMinimumWidth(640)
        self.tl, self.model = tl, model
        self.patterns = chord_patterns(tl)
        self.riffs: list[dict] = []   # {pattern, variant, notes, landings(절대초, 패턴 첫 등장 기준)}
        self._play_id = 0
        self.note_player = shared_player()
        self._saved = [list(seg.example) for seg in tl.segments]
        lay = QVBoxLayout(self)
        p = tl.practice
        if p.get("method") == "landing":
            count = p.get("count")
            cond = f"착지음 {GOAL_KR[p['goal']]}" + (
                "" if not count else f" · 리프당 {count[0]}음" if count[0] == count[1]
                else f" · 리프당 {count[0]}~{count[1]}음")
        else:
            cond = "자유연습 · 스케일 안의 음"
        scale = p.get("scale", {}).get("name", "")
        self.info = QLabel(f"{scale} · {cond}")
        self.info.setStyleSheet(f"color:{T.TEXT_BODY};font-size:13px;")
        lay.addWidget(self.info)
        need = len(self.patterns)
        top = QHBoxLayout()
        self.need_lbl = QLabel(f"스케일 패턴 {need}종(곡 스케일 2마디 + 디투어 1마디) → 최소 리프 {need}개")
        self.need_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        top.addWidget(self.need_lbl)
        top.addStretch(1)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(need, max(need, sum(len(pt["spans"]) for pt in self.patterns)))
        self.count_spin.setSuffix(" 개")
        top.addWidget(self.count_spin)
        self.make_btn = QPushButton("생성")
        self.make_btn.setStyleSheet(T.qss_ghost_btn())
        self.make_btn.clicked.connect(self.make_riffs)
        top.addWidget(self.make_btn)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setFixedHeight(110)
        self.list.setStyleSheet(
            f"QListWidget{{background:{T.BG_INSET};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_SUBTLE};border-radius:6px;}}"
            f"QListWidget::item:selected{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_PRIMARY};}}")
        self.list.currentRowChanged.connect(self._show)
        lay.addWidget(self.list)
        self.roll = RiffRoll()
        lay.addWidget(self.roll)
        row = QHBoxLayout()
        self.listen_btn = QPushButton("듣기 ▶")
        self.listen_btn.setStyleSheet(T.qss_ghost_btn())
        self.listen_btn.clicked.connect(self.toggle_listen)
        row.addWidget(self.listen_btn)
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
        self.make_riffs()

    def _goal(self):
        p = self.tl.practice
        return p.get("goal") if p.get("method") == "landing" else None

    def _bake(self, pattern: int, variant: int) -> dict:
        count = self.tl.practice.get("count")
        a, b = self.patterns[pattern]["spans"][0]
        res = bake_progression(self.tl, self.model, a, b, self._goal(), variant,
                               count=tuple(count) if count else None)
        return {"notes": res["notes"], "landings": [x["at_sec"] for x in res["landings"]]}

    def make_riffs(self):
        """리프 수만큼 생성 — 패턴별로 첫 등장 구간에서 한 번씩만 굽는다."""
        self.stop_listen()
        self.riffs = [{"pattern": i, "variant": v, **self._bake(i, v)}
                      for i, n in enumerate(allocate(self.patterns, self.count_spin.value()))
                      for v in range(n)]
        self.list.clear()
        for r in self.riffs:
            pt = self.patterns[r["pattern"]]
            total = sum(x["pattern"] == r["pattern"] for x in self.riffs)
            self.list.addItem(f"{pt['label']}  ×{len(pt['spans'])}  · {r['variant'] % total + 1}/{total}"
                              if total > 1 else f"{pt['label']}  ×{len(pt['spans'])}")
        if self.riffs:
            self.list.setCurrentRow(0)
            self._show(0)

    def _show(self, row: int):
        self.stop_listen()
        if not 0 <= row < len(self.riffs):
            return
        r = self.riffs[row]
        a, b = self.patterns[r["pattern"]]["spans"][0]
        b0 = self.tl.beat_at(a)
        bpb = self.tl.time_sig_beats()
        notes = [{"midi": n["midi"], "beat_pos": self.tl.beat_at(n["start_sec"]) - b0,
                  "dur_beats": self.tl.beats_between(n["start_sec"], n["start_sec"] + n["duration_sec"])}
                 for n in r["notes"]]
        self.note_player.preload({n["midi"] for n in r["notes"]})
        scale = self.tl.practice.get("scale") or {}
        bars = max(1, round(self.tl.beats_between(a, b) / bpb))
        self.roll.set_riff(notes, scale.get("note_set", []), [], bpb, bars, scale.get("root", 0))

    def _current(self) -> dict | None:
        row = self.list.currentRow()
        return self.riffs[row] if 0 <= row < len(self.riffs) else None

    def toggle_listen(self):
        if self._play_id % 2:
            self.stop_listen()
            return
        r = self._current()
        if r is None:
            return
        self._play_id += 1   # 홀수 = 재생 중; 바뀌면 남은 타이머는 무시된다
        pid = self._play_id
        t0, t1 = self.patterns[r["pattern"]]["spans"][0]
        self.note_player.warmup()
        for n in r["notes"]:
            QTimer.singleShot(max(0, round((n["start_sec"] - t0) * 1000)),
                              lambda n=n: pid == self._play_id and self.note_player.play_note(
                                  n["midi"], n["duration_sec"]))
        QTimer.singleShot(round((t1 - t0) * 1000),
                          lambda: pid == self._play_id and self.stop_listen())
        self.listen_btn.setText("정지 ■")

    def stop_listen(self):
        if self._play_id % 2:
            self._play_id += 1
            self.note_player.stop_all()
        self.listen_btn.setText("듣기 ▶")

    def regenerate(self):
        r = self._current()
        if r is None:
            return
        r["variant"] += len(self.riffs)   # 같은 패턴의 다른 변형과 겹치지 않는 새 번호
        r.update(self._bake(r["pattern"], r["variant"]))
        self._show(self.list.currentRow())

    def _apply(self):
        """패턴의 k번째 등장 구간 ← 그 패턴 변형 k % n을 그 구간 코드에 맞춰 도수 이동해 기록.

        기본(2마디) 패턴을 먼저 깔고, 디투어 1마디 패턴(overlay)을 그 마디에 덧씌운다.
        """
        for i, pt in sorted(enumerate(self.patterns), key=lambda x: x[1]["overlay"]):
            mine = [r for r in self.riffs if r["pattern"] == i]
            src = pt["spans"][0][0]
            for k, (a, b) in enumerate(pt["spans"]):
                r = mine[k % len(mine)]
                write_examples(self.tl, a, b, transpose_riff(self.tl, r["notes"], src, a,
                                                             self._goal(), r["landings"]))

    def done(self, result):
        self.stop_listen()
        if result == QDialog.DialogCode.Accepted:
            self._apply()
        else:
            for seg, ex in zip(self.tl.segments, self._saved):
                seg.example = ex
        super().done(result)
