"""[1] 분석 중 화면 — ScaleRiff (디자인 스펙 §6 [1]).

타임라인 빌드를 별도 프로세스로 실행하고 단계 체크리스트로 진행 표시.
'연습하며 기다리기' — 분석은 그대로 두고 링크 화면(세션 열기만 활성)으로 복귀.
"""
from __future__ import annotations

import math
import multiprocessing
import os
import shutil
import signal
import tempfile
import threading
import time

from gui.analysis_job import run_analysis
from player.timeline import Timeline

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal

from gui import theme as T
from gui.anim import stagger
from gui.widgets.flow_header import FlowHeader

_ESTIMATED_SECONDS = 10 * 60  # 일반 곡의 다운로드·분석에 여유를 둔 예상 시간

# 단계 체크리스트 — (이름, 해당 단계가 끝나는 pct 경계)
_STEPS = [
    ("오디오 가져오기", 42),
    ("비트·코드 인식", 78),
    ("구조·화성 분석", 99),
    ("세션 굽기", 101),
]


class BuildWorker(QThread):
    progress = pyqtSignal(int, str)

    def __init__(self, build_fn, source):
        super().__init__()
        self._build_fn = build_fn
        self._source = source
        cache = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
        os.makedirs(cache, exist_ok=True)
        self.work_dir = tempfile.mkdtemp(prefix="analysis_", dir=cache)
        self.cancelled = threading.Event()
        self.result = None
        self.error = None

    def discard(self):
        if os.path.isdir(self.work_dir):
            shutil.rmtree(self.work_dir)

    def _remove_unused_files(self):
        keep = {os.path.abspath(self.result.audio_ref)} if self.result.audio_ref else set()   # 분석 WAV 등은 삭제
        for directory, _, files in os.walk(self.work_dir, topdown=False):
            for name in files:
                path = os.path.join(directory, name)
                if os.path.abspath(path) not in keep:
                    os.remove(path)
            if not os.listdir(directory):
                os.rmdir(directory)

    def _stop_process(self, process):
        if not process.is_alive():
            return
        if os.name == "nt":
            process.kill()  # Job Object가 ffmpeg/Deno 등 자식까지 종료한다.
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                process.kill()
        process.join()

    def run(self):
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=run_analysis,
            args=(sender, self._build_fn, self._source, self.work_dir))
        started = False
        try:
            if self.cancelled.is_set():
                return
            process.start()
            started = True
            sender.close()
            while not self.cancelled.is_set():
                if receiver.poll(0.05):
                    kind, data = receiver.recv()
                    if kind == "progress":
                        self.progress.emit(*data)
                    elif kind == "ready":
                        self.result = Timeline.from_dict(data)
                        break
                    else:
                        self.error = data
                        break
                elif not process.is_alive():
                    raise RuntimeError("분석 프로세스가 예기치 않게 종료됐어요")
        except Exception as error:
            import traceback
            self.error = f"{error}\n\n{traceback.format_exc()}"
        finally:
            try:
                if started:
                    if not self.cancelled.is_set():
                        process.join(timeout=1)
                    self._stop_process(process)
                if self.cancelled.is_set() or self.error:
                    self.discard()
                elif self.result is not None:
                    self._remove_unused_files()
            except Exception as error:
                self.error = f"분석 정리 실패: {error}"
            finally:
                receiver.close()
                sender.close()
                if started and not process.is_alive():
                    process.close()


class AnalyzingScreen(QWidget):
    timelineReady = pyqtSignal(object)
    backRequested = pyqtSignal()
    backgroundRequested = pyqtSignal()      # 연습하며 기다리기
    progressChanged = pyqtSignal(int)       # 상단 알약(분석중 N%) 갱신용
    analysisFailed = pyqtSignal()
    analysisCancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._display_progress = 0.0
        self._last_progress_tick = 0.0
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(100)
        self._progress_timer.timeout.connect(self._tick_progress)
        content = T.compact_content(self, max_width=860)
        lay = QVBoxLayout(content)
        lay.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        lay.addWidget(FlowHeader(1))
        lay.addStretch(1)

        self.title = QLabel("분석 중…")
        self.title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:24px;font-weight:700;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.title)

        self.msg = QLabel("준비 중")
        self.msg.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-size:13px;")
        self.msg.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.msg.setTextFormat(Qt.TextFormat.PlainText)
        self.msg.setWordWrap(True)
        self.msg.setMinimumWidth(0)
        self.msg.setMaximumHeight(76)
        lay.addWidget(self.msg)
        lay.addSpacing(20)

        # ── 단계 체크리스트 ──────────────────────────────────────
        steps_row = QVBoxLayout()
        steps_row.setContentsMargins(0, 0, 0, 0)
        steps_row.setSpacing(12)
        self._step_lbls = []
        for name, _ in _STEPS:
            sl = QLabel(f"대기   {name}")
            sl.setStyleSheet(
                f"color:{T.TEXT_DIM};font-family:'{T.FONT_MONO}';font-size:12px;")
            steps_row.addWidget(sl)
            sl.setMinimumHeight(24)
            self._step_lbls.append(sl)
        self._steps_wrap = QWidget()
        self._steps_wrap.setLayout(steps_row)
        lay.addWidget(self._steps_wrap)
        lay.addSpacing(12)

        self.bar = QProgressBar()
        self.bar.setRange(0, 10000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:{T.BG_SURFACE};border:none;border-radius:5px;}}"
            f"QProgressBar::chunk{{background:{T.BORDER_ACTIVE};border-radius:5px;}}")
        self.percent_label = QLabel("0.0%")
        self.percent_label.setFixedWidth(86)
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight |
                                        Qt.AlignmentFlag.AlignVCenter)
        self.percent_label.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_MONO}';font-size:20px;")
        self.percent_label.setToolTip("예상 진행률 — 실제 분석 완료 시 100%")
        self._progress_wrap = QWidget()
        progress_row = QHBoxLayout(self._progress_wrap)
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(12)
        progress_row.addWidget(self.bar, 1)
        progress_row.addWidget(self.percent_label)
        lay.addWidget(self._progress_wrap)
        estimate = QLabel("예상 진행률 · 곡 길이와 분석 단계에 따라 진행 속도가 달라집니다.")
        estimate.setStyleSheet(f"color:{T.TEXT_DIM};font-size:11px;")
        estimate.setWordWrap(True)
        lay.addWidget(estimate)

        bg_row = QHBoxLayout()
        bg_row.addStretch(1)
        self.bg_btn = QPushButton("연습하며 기다리기")
        self.bg_btn.setStyleSheet(T.qss_ghost_btn())
        self.bg_btn.clicked.connect(self.backgroundRequested.emit)
        bg_row.addWidget(self.bg_btn)
        self.cancel_btn = QPushButton("분석 중단")
        self.cancel_btn.setStyleSheet(T.qss_ghost_btn())
        self.cancel_btn.clicked.connect(self.cancel)
        bg_row.addWidget(self.cancel_btn)
        bg_row.addStretch(1)
        lay.addSpacing(16)
        lay.addLayout(bg_row)

        self.err_btn = QPushButton("← 돌아가기")
        self.err_btn.setStyleSheet(T.qss_ghost_btn())
        self.err_btn.clicked.connect(self.backRequested.emit)
        self.err_btn.hide()
        lay.addWidget(self.err_btn)
        lay.addStretch(2)

    def showEvent(self, e):
        super().showEvent(e)
        stagger([self.title, self.msg, self._steps_wrap, self._progress_wrap,
                 self.bg_btn, self.cancel_btn])

    def start(self, build_fn, source):
        if self._worker is not None:
            return
        self._display_progress = 0.0
        self._last_progress_tick = time.monotonic()
        self._render_progress()
        self.err_btn.hide()
        self.bg_btn.show()
        self.bg_btn.setEnabled(True)
        self.cancel_btn.show()
        self.cancel_btn.setEnabled(True)
        self.msg.setText("준비 중")
        self.msg.setToolTip("")
        self.title.setText("분석 중…")
        self._set_steps(0)
        self._worker = BuildWorker(build_fn, source)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()
        self._progress_timer.start()

    def cancel(self):
        if self._worker is None:
            return
        self._progress_timer.stop()
        self._worker.cancelled.set()
        self.cancel_btn.setEnabled(False)
        self.bg_btn.setEnabled(False)
        self.title.setText("분석 중단 중…")
        self.msg.setText("작업을 종료하고 파일을 정리하고 있어요")

    def shutdown(self):
        self._progress_timer.stop()
        if self._worker is not None:
            self._worker.cancelled.set()
            self._worker.wait()
            self._worker.discard()

    def _on_worker_finished(self):
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        self._progress_timer.stop()
        self.cancel_btn.hide()
        if worker.cancelled.is_set():
            try:
                worker.discard()
            except OSError as error:
                self._on_failed(f"파일 정리 실패: {error}")
                return
            if worker.error and worker.error.startswith("분석 정리 실패:"):
                self._on_failed(worker.error)
                return
            self.analysisCancelled.emit()
        elif worker.error:
            self._on_failed(worker.error)
        else:
            self._display_progress = 100.0
            self._render_progress()
            self._set_steps(101)
            self.timelineReady.emit(worker.result)

    def _set_steps(self, pct):
        prev_end = 0
        for (name, end), sl in zip(_STEPS, self._step_lbls):
            if pct >= end:          # 완료
                sl.setText(f"완료   {name}")
                sl.setStyleSheet(
                    f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
            elif pct >= prev_end:   # 진행 중
                sl.setText(f"진행   {name}")
                sl.setStyleSheet(
                    f"color:{T.BORDER_ACTIVE};font-family:'{T.FONT_MONO}';"
                    "font-size:12px;font-weight:700;")
            else:                   # 대기
                sl.setText(f"대기   {name}")
                sl.setStyleSheet(
                    f"color:{T.TEXT_DIM};font-family:'{T.FONT_MONO}';font-size:12px;")
            prev_end = end

    def _render_progress(self):
        # 소수점 단위로 바를 갱신하고, 실제 완료 전에는 100%로 반올림하지 않는다.
        value = math.floor(self._display_progress * 100)
        self.bar.setValue(value)
        percent = math.floor(self._display_progress * 10) / 10
        self.percent_label.setText(f"{percent:.1f}%")
        self.progressChanged.emit(int(self._display_progress))

    def _tick_progress(self):
        if self._worker is None or self._worker.cancelled.is_set():
            return
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_progress_tick)
        self._last_progress_tick = now
        # 예상 시간에 따라 전진하고, 초과 시에는 100%까지 남은 폭을 천천히 줄인다.
        rate = 100 / _ESTIMATED_SECONDS
        linear_time = min(elapsed, max(0.0, (90 - self._display_progress) / rate))
        self._display_progress += rate * linear_time
        tail_time = elapsed - linear_time
        if tail_time:
            self._display_progress = 100 - (100 - self._display_progress) * math.exp(
                -tail_time / 60)
        self._display_progress = min(self._display_progress, 99.999999)
        self._render_progress()

    def _on_progress(self, pct, msg):
        if self._worker is not None and self._worker.cancelled.is_set():
            return
        self._display_progress = max(self._display_progress, min(float(pct), 95.0))
        self._render_progress()
        self.msg.setText(msg)
        self._set_steps(pct)

    def _on_failed(self, err):
        self._progress_timer.stop()
        self.title.setText("분석에 실패했어요")
        detail = next((line.strip() for line in err.splitlines() if line.strip()), "")
        self.msg.setText(detail.removeprefix("ERROR: ") or "링크나 파일을 확인해 주세요")
        self.msg.setToolTip(err)
        self.bg_btn.hide()
        self.cancel_btn.hide()
        self.err_btn.show()
        self.analysisFailed.emit()
