"""[1] 분석 중 화면 — ScaleRiff (디자인 스펙 §6 [1]).

타임라인 빌드를 백그라운드 스레드로 실행하고 단계 체크리스트로 진행 표시.
'연습하며 기다리기' — 분석은 그대로 두고 링크 화면(세션 열기만 활성)으로 복귀.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from gui import theme as T
from gui.anim import stagger

# 단계 체크리스트 — (이름, 해당 단계가 끝나는 pct 경계)
_STEPS = [
    ("오디오 가져오기", 42),
    ("비트·코드 인식", 78),
    ("구조·화성 분석", 99),
    ("세션 굽기", 101),
]


class BuildWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, build_fn, source):
        super().__init__()
        self._build_fn = build_fn
        self._source = source

    def run(self):
        try:
            def cb(pct, msg):
                self.progress.emit(int(pct), msg)
            tl = self._build_fn(self._source, cb)
            self.finished_ok.emit(tl)
        except Exception as e:
            import traceback
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class AnalyzingScreen(QWidget):
    timelineReady = pyqtSignal(object)
    backRequested = pyqtSignal()
    backgroundRequested = pyqtSignal()      # 연습하며 기다리기
    progressChanged = pyqtSignal(int)       # 상단 알약(분석중 N%) 갱신용
    analysisFailed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(80, 0, 80, 0)
        lay.addStretch(1)

        self.title = QLabel("분석 중…")
        self.title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:24px;font-weight:700;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)

        self.msg = QLabel("준비 중")
        self.msg.setStyleSheet(
            f"color:{T.TEXT_DIM};font-family:'{T.FONT_MONO}';"
            "font-size:12px;letter-spacing:2px;")
        self.msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.msg)
        lay.addSpacing(20)

        # ── 단계 체크리스트 ──────────────────────────────────────
        steps_row = QHBoxLayout()
        steps_row.addStretch(1)
        self._step_lbls = []
        for name, _ in _STEPS:
            sl = QLabel(f"○ {name}")
            sl.setStyleSheet(
                f"color:{T.TEXT_DIM};font-family:'{T.FONT_MONO}';font-size:12px;")
            steps_row.addWidget(sl)
            steps_row.addSpacing(18)
            self._step_lbls.append(sl)
        steps_row.addStretch(1)
        self._steps_wrap = QWidget()
        self._steps_wrap.setLayout(steps_row)
        lay.addWidget(self._steps_wrap)
        lay.addSpacing(12)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:{T.BG_SURFACE};border:none;border-radius:5px;}}"
            f"QProgressBar::chunk{{background:{T.WHITE};border-radius:5px;}}")
        lay.addWidget(self.bar)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)
        self.log.setStyleSheet(
            f"QTextEdit{{background:{T.BG_INSET};color:{T.TEXT_DIM};border:none;"
            f"border-radius:8px;font-family:'{T.FONT_MONO}';font-size:11px;}}")
        lay.addSpacing(16)
        lay.addWidget(self.log)

        bg_row = QHBoxLayout()
        bg_row.addStretch(1)
        self.bg_btn = QPushButton("연습하며 기다리기")
        self.bg_btn.setStyleSheet(T.qss_ghost_btn())
        self.bg_btn.clicked.connect(self.backgroundRequested.emit)
        bg_row.addWidget(self.bg_btn)
        bg_row.addStretch(1)
        lay.addSpacing(16)
        lay.addLayout(bg_row)

        self.err_btn = QPushButton("← 돌아가기")
        self.err_btn.setStyleSheet(f"color:{T.TEXT_MUTED};border:none;")
        self.err_btn.clicked.connect(self.backRequested.emit)
        self.err_btn.hide()
        lay.addWidget(self.err_btn)
        lay.addStretch(2)

    def showEvent(self, e):
        super().showEvent(e)
        stagger([self.title, self.msg, self._steps_wrap, self.bar,
                 self.log, self.bg_btn])

    def start(self, build_fn, source):
        self.bar.setValue(0)
        self.log.clear()
        self.err_btn.hide()
        self.bg_btn.show()
        self.title.setText("분석 중…")
        self._set_steps(0)
        self._worker = BuildWorker(build_fn, source)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self.timelineReady.emit)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _set_steps(self, pct):
        prev_end = 0
        for (name, end), sl in zip(_STEPS, self._step_lbls):
            if pct >= end:          # 완료
                sl.setText(f"✓ {name}")
                sl.setStyleSheet(
                    f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
            elif pct >= prev_end:   # 진행 중
                sl.setText(f"● {name}")
                sl.setStyleSheet(
                    f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_MONO}';"
                    "font-size:12px;font-weight:700;")
            else:                   # 대기
                sl.setText(f"○ {name}")
                sl.setStyleSheet(
                    f"color:{T.TEXT_DIM};font-family:'{T.FONT_MONO}';font-size:12px;")
            prev_end = end

    def _on_progress(self, pct, msg):
        self.bar.setValue(pct)
        self.msg.setText(msg)
        self.log.append(f"[{pct:3d}%] {msg}")
        self._set_steps(pct)
        self.progressChanged.emit(pct)

    def _on_failed(self, err):
        self.title.setText("분석에 실패했어요")
        self.msg.setText("링크나 파일을 확인해 주세요")
        self.log.append("\n" + err)
        self.bg_btn.hide()
        self.err_btn.show()
        self.analysisFailed.emit()
