"""UI 공간·Qt 전환 수명·효과 축소·긴 목록의 동작 회귀."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
import tempfile
from unittest.mock import patch

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget
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

    def test_screen_switch_opens_curtain_then_cleans_up(self):
        from PyQt6.QtWidgets import QStackedWidget
        stack = QStackedWidget()
        first, link = QWidget(), LinkScreen(show_onboarding=True)
        stack.addWidget(first)
        stack.addWidget(link)
        stack.resize(960, 700)
        stack.show()
        stack.setCurrentWidget(link)                  # 화면 전환 = 새 화면 전체를 덮은 커튼이 걷힘
        curtain = link._curtain
        self.assertIsNotNone(curtain, "전환 커튼 없음")
        self.assertIs(curtain.parentWidget(), link)
        self.assertEqual(curtain.size(), link.size())
        self.assertTrue(curtain.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        link.stack.setCurrentIndex(1)                 # 온보딩 → 입력도 커튼 — 이전 커튼 대신 새 커튼 하나
        self.assertIsNot(link._curtain, curtain)
        QTest.qWait(link._curtain.anim.totalDuration() + 150)
        self.assertIsNone(link._curtain, "전환 뒤 커튼이 남음")
        self.assertEqual([c for c in link.children() if isinstance(c, anim.Curtain)], [])
        self.app.setProperty("reduceMotion", True)    # 효과 축소 = 커튼 없이 즉시
        stack.setCurrentWidget(first)
        stack.setCurrentWidget(link)
        self.assertIsNone(link._curtain)

    def test_reduced_motion_preference_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(os.path.join(directory, "ui.ini"), QSettings.Format.IniFormat)
            with patch("gui.anim.QSettings", return_value=settings):
                anim.set_reduced_motion(True)
            self.assertTrue(settings.value("reduce_motion", False, type=bool))
            self.assertTrue(anim.reduced_motion())

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

    def test_backdrop_uses_physical_pixels(self):
        from PyQt6.QtGui import QPainter, QPixmap
        for name in ("backdrop.webp", "stage_backdrop.webp"):
            dev = QPixmap(1920, 1080)
            dev.setDevicePixelRatio(1.25)            # 배율 125% 노트북(논리 1536x864)
            p = QPainter(dev)
            T.paint_backdrop(p, 1536, 864, name)
            p.end()
            pix = T._BACKDROP[(name, 1921, 1081)]
            self.assertEqual(pix.devicePixelRatio(), 1.25, "배경은 화면 실제 픽셀 크기로(늘려 흐려지지 않게)")

    def test_backdrop_sprites_move_and_repaint_only_their_area(self):
        bd = T.Backdrop()
        bd.resize(1000, 700)
        bd.show()
        self.assertTrue(bd._timer.isActive())
        bd._tick(100.0)
        first = [r for _, r, _ in bd._scene()]
        bd._tick(100.5)
        moved = sum(a.center() != b.center() for a, b in zip(first, (r for _, r, _ in bd._scene())))
        self.assertGreater(moved, len(first) // 2, "시각이 흐르면 기둥·반딧불이 움직인다")
        dirty = sum(r.width() * r.height() for _, r, _ in bd._scene())
        self.assertLess(dirty, 1000 * 700 * 0.25, "다시 그리는 곳은 스프라이트 자리뿐(배경 전체 아님)")
        bd.set_running(False)
        self.assertFalse(bd._timer.isActive())
        self.assertTrue(bd._areas.isEmpty())
        bd.set_running(True)
        self.app.setProperty("reduceMotion", True)
        bd._tick(101.0)
        self.assertFalse(bd._show, "동작 줄이기 = 스프라이트 없음")
        self.assertEqual(bd._timer.interval(), 500)

    def test_stage_haze_pulses_on_beats(self):
        from PyQt6.QtGui import QImage
        screen = MainScreen()
        screen.set_timeline(build_dummy_timeline())
        screen.resize(1200, 800)
        screen.show()
        stage = screen.stage
        self.assertTrue(stage._haze_timer.isActive(), "멈춤 중에도 아지랑이는 숨 쉰다")
        self.assertEqual(stage._pulse(), 0.0)
        stage.beat = (8.0, 4)
        down = stage._pulse()
        stage.beat = (9.0, 4)
        self.assertGreater(down, stage._pulse(), "마디 첫 박이 더 세게")
        stage.beat = (9.6, 4)
        self.assertLess(stage._pulse(), 0.05, "박 사이엔 잦아듦")
        curtain = getattr(stage, "_curtain", None)    # 진입 커튼(불투명)이 덮고 있으면 무대는 안 그려짐 — 끝내고 확인
        if curtain is not None:
            curtain.anim.setCurrentTime(curtain.anim.totalDuration())
        img = QImage(stage.size(), QImage.Format.Format_ARGB32_Premultiplied)
        stage.render(img)
        self.assertIsNotNone(stage._haze)
        screen.hide()
        self.assertFalse(stage._haze_timer.isActive())

    def test_player_uses_width_and_keeps_controls_visible(self):
        screen = MainScreen()
        screen.set_timeline(build_dummy_timeline())
        for width, height in ((960, 700), (1040, 740), (1280, 800), (1600, 1000)):
            screen.resize(width, height)
            screen.show()
            self.app.processEvents()
            self.assertGreater(screen.content.width(), screen.width() * .9)
            self.assertLessEqual(screen.height(), height)
            for widget in (screen.stage, screen.play_btn, screen.riff_btn, screen.settings_btn, screen.scrub_row):
                top_left = widget.mapTo(screen.content, widget.rect().topLeft())
                self.assertTrue(screen.content.rect().contains(widget.rect().translated(top_left)), widget.objectName())

    def test_setup_screen_fits_with_scale_only(self):
        screen = SetupScreen()
        screen.set_timeline(build_dummy_timeline())
        screen.resize(1040, 740)
        screen.show()
        self.app.processEvents()
        self.assertTrue(screen.rect().contains(screen.go_btn.mapTo(screen, screen.go_btn.rect().bottomRight())))
        self.assertFalse(hasattr(screen, "method_btns"), "연습 방식은 고르지 않음(자유연습으로 시작)")

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


if __name__ == "__main__":
    unittest.main()
