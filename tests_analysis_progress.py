"""예상 진행률: 무응답 구간·단계 점프·초과 시간·완료/중단 검증."""
import os
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from gui.analyzing_screen import AnalyzingScreen


def main():
    app = QApplication([])
    screen = AnalyzingScreen()
    with patch("gui.analyzing_screen.BuildWorker") as worker_type, \
            patch("gui.analyzing_screen.time.monotonic", return_value=0) as clock:
        worker = worker_type.return_value
        worker.cancelled.is_set.return_value = False
        worker.error = None
        worker.result = object()
        changes = []
        screen.progressChanged.connect(changes.append)
        screen.start(None, "test")
        assert screen.percent_label.text() == "0.0%"
        assert screen._progress_timer.isActive()
        previous = screen.bar.value()
        for seconds in range(1, 1201):
            clock.return_value = seconds
            screen._tick_progress()
            assert screen._display_progress > 0
            if seconds < 600:
                assert screen.bar.value() > previous, "진행 알림이 없는 구간에서 로딩바가 멈춤"
            assert screen._display_progress < 100
            previous = screen.bar.value()
        assert screen._step_lbls[0].text().startswith("진행"), "예상 진행률만으로 실제 단계를 완료 처리함"
        before = screen._display_progress
        screen._on_progress(20, "늦은 단계 알림")
        assert screen._display_progress >= before, "진행률이 후퇴함"
        screen._on_progress(100, "완료 알림 대기")
        assert screen._display_progress < 100
        screen._on_worker_finished()
        assert screen.percent_label.text() == "100.0%" and screen.bar.value() == 10000
        assert not screen._progress_timer.isActive()

        clock.return_value = 2000
        screen.start(None, "next")
        screen._on_progress(62, "화성 분석")
        assert screen.percent_label.text() == "62.0%"
        clock.return_value = 2001
        screen._tick_progress()
        assert screen._display_progress > 62
        screen._on_progress(42, "늦은 알림")
        assert screen._display_progress > 62
        screen.cancel()
        assert not screen._progress_timer.isActive()
        worker.cancelled.is_set.return_value = True
        screen._on_worker_finished()

        worker.cancelled.is_set.return_value = False
        screen.start(None, "failed")
        screen._on_failed("test failure")
        assert not screen._progress_timer.isActive()
    screen.close()
    print("ANALYSIS PROGRESS OK")


if __name__ == "__main__":
    main()
