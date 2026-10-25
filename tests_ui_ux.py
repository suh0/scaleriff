"""UI 공간·Qt 전환 수명·효과 축소·긴 목록의 동작 회귀."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
import tempfile
from unittest.mock import patch

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget, QGraphicsOpacityEffect
from gui import anim
from gui import theme as T
from gui.link_screen import LinkScreen
from gui.main_screen import MainScreen
from gui.setup_screen import SetupScreen
from gui.beat_screen import BeatScreen
from gui.widgets.scrub_bar import ScrubBar
from player.dummy_timeline import build_dummy_timeline


class UIUXTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        T.load_fonts()

    def tearDown(self):
        self.app.setProperty("reduceMotion", False)
        for w in self.app.topLevelWidgets():
            w.close()

    def test_reduced_motion_does_not_hide_new_content(self):
        self.app.setProperty("reduceMotion", True)
        w = QWidget()
        anim.fade_in(w, delay=500)
        self.assertIsNone(w.graphicsEffect(), "효과 축소 시 콘텐츠를 즉시 표시해야 함")

    def test_entry_preserves_existing_opacity_lock(self):
        w = QWidget()
        effect = QGraphicsOpacityEffect(w)
        effect.setOpacity(.35)
        w.setGraphicsEffect(effect)
        anim.fade_in(w)
        self.assertIs(w.graphicsEffect(), effect, "화면 진입 효과가 잠금을 덮어씀")

    def test_preference_saves_and_cancels_an_active_transition(self):
        w = QWidget()
        anim.fade_in(w)
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(os.path.join(directory, "ui.ini"), QSettings.Format.IniFormat)
            with patch("gui.anim.QSettings", return_value=settings):
                anim.set_reduced_motion(True)
            self.assertTrue(settings.value("reduce_motion", False, type=bool))
            self.assertTrue(anim.reduced_motion())
            self.assertIsNone(w.graphicsEffect())

    def test_repeated_entry_and_early_close_are_safe(self):
        w = QWidget()
        w.show()
        for _ in range(12):
            anim.fade_in(w, delay=10)
            self.app.processEvents()
        QTest.qWait(250)
        self.assertIsNone(w.graphicsEffect(), "전환이 끝나도 효과가 남음")
        anim.fade_in(w, delay=20)
        w.deleteLater()
        QTest.qWait(80)

    def test_input_fits_and_empty_submit_explains_next_action(self):
        screen = LinkScreen(show_onboarding=False)
        screen.resize(960, 700)
        screen.show()
        self.app.processEvents()
        field = screen.url_edit
        self.assertTrue(screen.rect().contains(field.mapTo(screen, field.rect().topLeft())))
        self.assertTrue(screen.rect().contains(field.mapTo(screen, field.rect().bottomRight())))
        screen._submit()
        self.assertFalse(screen.input_hint.text() == "", "빈 입력 시 다음 행동 안내")
        self.assertEqual(self.app.focusWidget(), field)

    def test_player_uses_width_and_keeps_controls_visible(self):
        screen = MainScreen()
        screen.set_timeline(build_dummy_timeline())
        for width, height in ((960, 700), (1040, 740), (1280, 800), (1600, 1000)):
            screen.resize(width, height)
            screen.show()
            self.app.processEvents()
            self.assertGreater(screen.content.width(), screen.width() * .9)
            self.assertLessEqual(screen.height(), height)
            for widget in (screen.piano, screen.play_btn, screen.scrub):
                self.assertTrue(screen.content.rect().contains(widget.geometry()), widget.objectName())
            screen._place_falling_notes()
            geo = screen.piano._geometry()
            self.assertAlmostEqual(screen.riff.y() + screen.riff.height(), screen.piano.y() + geo[2], delta=1)

    def test_setup_screen_fits_and_landing_options_follow_method(self):
        screen = SetupScreen()
        screen.set_timeline(build_dummy_timeline())
        screen.resize(1040, 740)
        screen.show()
        self.app.processEvents()
        self.assertTrue(screen.rect().contains(screen.go_btn.mapTo(screen, screen.go_btn.rect().bottomRight())))
        self.assertFalse(screen.landing_box.isVisible())
        screen._pick_method("landing")
        self.assertTrue(screen.landing_box.isVisible())

    def test_long_loop_lists_stay_within_window(self):
        tl = build_dummy_timeline()
        tl.loops = [{"name": "긴 루프 이름" * 12, "start_bar": 0, "end_bar": 0, "on": False}
                    for _ in range(20)]
        screen = MainScreen()
        screen.set_timeline(tl)
        screen.resize(1040, 740)
        screen.show()
        screen.loop_btn.click()
        self.app.processEvents()
        self.assertGreater(screen.loop_scroll.verticalScrollBar().maximum(), 0)
        self.assertTrue(screen.content.rect().contains(screen.play_btn.geometry()))
        beat = BeatScreen()
        beat.set_timeline(tl)
        beat._set_locked(True)
        beat.resize(1040, 740)
        beat.show()
        self.app.processEvents()
        self.assertGreater(beat.loops_scroll.horizontalScrollBar().maximum(), 0)
        self.assertLessEqual(beat.width(), 1040)

    def test_keyboard_scrub_clamps_at_track_ends(self):
        scrub = ScrubBar()
        scrub.set_timeline(build_dummy_timeline())
        seeks = []
        scrub.seekRequested.connect(seeks.append)
        scrub.show()
        QTest.keyClick(scrub, Qt.Key.Key_Left)
        self.assertEqual(seeks[-1], 0)
        QTest.keyClick(scrub, Qt.Key.Key_End)
        self.assertEqual(seeks[-1], scrub._total())

    def test_capture_keeps_session_destination_in_temporary_directory(self):
        from tools import capture_ui
        destinations = []
        def record_destination(window, _timeline):
            destinations.append(window.link_screen.save_dir())
            return True
        with tempfile.TemporaryDirectory() as directory, \
                patch("sys.argv", ["capture_ui.py", "--output", directory, "--sizes", "1040x740"]), \
                patch.object(capture_ui.AppWindow, "_save_session", record_destination), \
                patch.object(capture_ui.QTest, "qWait"):
            capture_ui.main()
        self.assertTrue(destinations)
        for destination in destinations:
            self.assertTrue(os.path.abspath(destination).startswith(os.path.abspath(tempfile.gettempdir()) + os.sep), destination)


    def test_falling_beat_lines_use_adjusted_and_variable_grid(self):
        screen = MainScreen()
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [.25, 2.6, 4.6]
        tl.beat_times = [.25, .75, 1.4, 2.1, 2.6, 3.1, 3.6, 4.1]
        screen.set_timeline(tl)
        screen.riff.resize(800, 80)
        screen.riff.set_position(.25)
        expected = [80 * (1 - (t - .25) / screen.riff._lead) for t in tl.beat_grid() if .25 <= t <= .25 + screen.riff._lead]
        self.assertEqual(screen.riff._beat_lines(), expected)
        screen.riff.set_position(2.2, [(1.4, 2.6)])
        # 다음 반복의 루프 안 첫 실제 박은 루프 길이 1.2초 뒤에 예고된다.
        first = min(t for t in tl.beat_grid() if t >= 1.4)
        y = 80 * (1 - (first + 1.2 - 2.2) / screen.riff._lead)
        self.assertTrue(any(abs(v - y) < 1e-6 for v in screen.riff._beat_lines()))


if __name__ == "__main__":
    unittest.main()
