"""[1] 분석 중 화면 — ScaleRiff (디자인 스펙 §6 [1]).

타임라인 빌드를 백그라운드 스레드로 실행하고 진행 단계를 모노 라벨로 표시.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from gui import theme as T
from gui.anim import stagger


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

        self.err_btn = QPushButton("← 돌아가기")
        self.err_btn.setStyleSheet(f"color:{T.TEXT_MUTED};border:none;")
        self.err_btn.clicked.connect(self.backRequested.emit)
        self.err_btn.hide()
        lay.addWidget(self.err_btn)
        lay.addStretch(2)

    def showEvent(self, e):
        super().showEvent(e)
        stagger([self.title, self.msg, self.bar, self.log])

    def start(self, build_fn, source):
        self.bar.setValue(0)
        self.log.clear()
        self.err_btn.hide()
        self.title.setText("분석 중…")
        self._worker = BuildWorker(build_fn, source)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self.timelineReady.emit)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, pct, msg):
        self.bar.setValue(pct)
        self.msg.setText(msg)
        self.log.append(f"[{pct:3d}%] {msg}")

    def _on_failed(self, err):
        self.title.setText("분석에 실패했어요")
        self.msg.setText("링크나 파일을 확인해 주세요")
        self.log.append("\n" + err)
        self.err_btn.show()
