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

    def test_screen_switch_fades_old_snapshot_then_cleans_up(self):
        stack = anim.FadeStack()
        a, b = QWidget(), QWidget()
        stack.addWidget(a)
        stack.addWidget(b)
        stack.resize(400, 300)
        stack.show()
        stack.setCurrentWidget(b)
        snap = stack._snapshot
        self.assertIsNotNone(snap, "전환 스냅샷 없음")
        self.assertIs(stack.currentWidget(), b, "새 화면은 즉시 현재 화면(입력 가능)")
        self.assertTrue(snap.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        stack.setCurrentWidget(a)                     # 연달아 전환 — 이전 스냅샷 대신 새 스냅샷 하나
        self.assertIsNot(stack._snapshot, snap)
        QTest.qWait(anim.OUT_MS + anim.IN_MS + 150)
        self.assertIsNone(stack._snapshot, "전환 뒤 스냅샷이 남음")
        self.assertEqual([c for c in stack.children() if isinstance(c, anim._Snapshot)], [])
        self.app.setProperty("reduceMotion", True)    # 효과 축소 = 스냅샷 없이 즉시
        stack.setCurrentWidget(b)
        self.assertIsNone(stack._snapshot)

    def test_boxes_enter_in_order_after_old_screen_leaves(self):
        def delays(boxes):
            out = []
            for w in boxes:
                group = w._entry_animation
                first = group.animationAt(0)
                out.append(first.duration() if group.animationCount() == 2 else 0)
            return out
        holder = QWidget()                      # 자식 위젯이어야 '숨김' 여부가 명시 hide()로만 정해짐
        head, sub, card, hidden, btn = (QWidget(holder) for _ in range(5))
        hidden.hide()
        anim.stagger([(head, sub), card, hidden, btn])
        self.assertEqual(delays([head, sub, card, btn]), [0, 0, anim.STEP_MS, 2 * anim.STEP_MS],
                         "한 박스(튜플)는 같이, 박스끼리는 차례로, 숨은 박스는 건너뜀")
        self.assertIsNone(getattr(hidden, "_entry_animation", None))
        # 화면 전환 중이면 이전 화면이 사라진 뒤(OUT_MS)부터
        stack = anim.FadeStack()
        class Page(QWidget):
            def showEvent(self, e):
                anim.stagger([self.box])
        first, page = QWidget(), Page()
        box = page.box = QWidget(page)
        stack.addWidget(first)
        stack.addWidget(page)
        stack.resize(300, 200)
        stack.show()
        stack.setCurrentWidget(page)
        self.assertGreater(delays([box])[0], anim.OUT_MS - 40)
        self.assertEqual(box.graphicsEffect().opacity(), 0, "이전 화면이 사라지기 전에 새 박스가 보임")

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
