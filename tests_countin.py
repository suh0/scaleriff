"""0마디, 음수 격자 및 무음 프리롤 회귀 테스트."""
import os
import tempfile
import unittest
import wave
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtTest import QTest
from PyQt6.QtCore import QUrl, QPoint, Qt
from gui.beat_screen import BeatScreen
from player.dummy_timeline import build_dummy_timeline
from player.timeline import Timeline
from player.playhead import Playhead
from build.real_builder import regrid_timeline


class CountInTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_negative_grid_and_blank_zero_bar(self):
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [0, 2, 4, 6, 8]
        tl.chord_spans = [[0, 4, "Dm7"], [4, 8, "G7"]]
        screen = BeatScreen()
        screen.set_timeline(tl)
        screen._on_drag(0, -0.7)
        self.assertAlmostEqual(screen.anchor, -0.7)
        self.assertLessEqual(screen.zoom_l._t0, -2.7)
        screen._on_confirm()
        self.assertEqual(tl.bar_times[0], -0.7)
        self.assertEqual([x.text() for x in screen._cells[-1].findChildren(QLabel)],
                         ["0", "", ""])
        screen._loop_press(0)
        screen._loop_drag_to(-1)
        self.assertFalse(screen._drag_loop)
        screen._reset_drag()
        self.assertIsNone(tl.segment_at(-0.1))
        self.assertEqual(tl.segment_index_at(-0.1), -1)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "session.json")
            tl.save_json(path)
            restored = Timeline.load_json(path)
        self.assertEqual(restored.bar_times, tl.bar_times)
        self.assertEqual(restored.audio_ref, tl.audio_ref)
        screen.pause()

    def test_wholly_negative_regular_bars_have_no_chords(self):
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [0, 2, 4, 6]
        tl.chord_spans = [[0, 6, "C"]]
        self.assertTrue(regrid_timeline(tl, anchor_sec=-4.5))
        self.assertIsNone(tl.segment_for_bar(0))
        self.assertIsNone(tl.segment_for_bar(1))
        self.assertGreaterEqual(tl.segments[0].start_sec, 0)

    def test_left_extension_keeps_waveform_scale(self):
        screen = BeatScreen()
        screen.set_timeline(build_dummy_timeline())
        zoom = screen.zoom_l
        zoom.resize(400, 96)
        spacing = zoom._sec_to_x(1) - zoom._sec_to_x(0)
        for anchor in (-1, -5, -20):
            screen._on_drag(0, anchor)
            self.assertAlmostEqual(zoom._sec_to_x(1) - zoom._sec_to_x(0), spacing)
            self.assertAlmostEqual(zoom._t1 - zoom._t0, 10)
            self.assertAlmostEqual(zoom._t0, max(-10, anchor - screen.bar_len))

    def test_countin_cannot_extend_before_minus_ten(self):
        screen = BeatScreen()
        screen.set_timeline(build_dummy_timeline())
        for bar in (-1, 0, 8):
            for _ in range(3):
                screen._on_drag(bar, -100)
                self.assertAlmostEqual(screen.anchor - screen.bar_len, -10)
                self.assertEqual(screen.zoom_l._t0, -10)
        screen.bpm_edit.setText("20")
        screen._on_bpm_edited()
        self.assertAlmostEqual(screen.anchor - screen.bar_len, -10)
        screen.sig_box.setCurrentIndex(screen.sig_box.findData("3/4"))
        self.assertGreaterEqual(screen.anchor - screen.bar_len, -10)

    def test_stationary_drag_does_not_keep_expanding(self):
        screen = BeatScreen()
        screen.set_timeline(build_dummy_timeline())
        zoom = screen.zoom_l
        zoom.resize(400, 96)
        QTest.mousePress(zoom, Qt.MouseButton.LeftButton, pos=QPoint(120, 40))
        QTest.mouseMove(zoom, QPoint(20, 40))
        anchor = screen.anchor
        for _ in range(5):
            QTest.mouseMove(zoom, QPoint(20, 40))
            self.assertAlmostEqual(screen.anchor, anchor)
        QTest.mouseRelease(zoom, Qt.MouseButton.LeftButton, pos=QPoint(20, 40))
        screen.pause()

    def test_virtual_preroll_pause_and_resume(self):
        head = Playhead(2)
        head.seek(-0.2)
        self.assertEqual(head.position_sec(), -0.2)
        head.play()
        QTest.qWait(50)
        head.pause()
        paused = head.position_sec()
        self.assertTrue(-0.2 < paused < 0)
        QTest.qWait(30)
        self.assertEqual(head.position_sec(), paused)
        head.play()
        QTest.qWait(250)
        self.assertGreater(head.position_sec(), 0)
        head.pause()

    def test_audio_waits_for_zero(self):
        head = Playhead(2)
        head._use_audio = True
        head._player = Mock()
        head._player.position.return_value = 0
        head.seek(-0.08)
        self.assertEqual(head.position_sec(), -0.08)
        head.play()
        self.assertFalse(head._player.play.called)
        QTest.qWait(150)
        self.assertTrue(head._player.play.called)
        self.assertGreaterEqual(head._player.setPosition.call_args.args[0], 0)
        head.pause()

    def test_real_audio_preroll(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "audio.wav")
            with wave.open(path, "wb") as wav:
                wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * 16000)
            head = Playhead(2, path)
            self.assertTrue(head._use_audio)
            head._audio_out.setVolume(0)
            QTest.qWait(300)
            head.seek(-0.2)
            head.play()
            QTest.qWait(60)
            self.assertLess(head.position_sec(), 0)
            QTest.qWait(400)
            self.assertGreater(head.position_sec(), 0)
            head.stop()
            head._player.setSource(QUrl())


if __name__ == "__main__":
    unittest.main()
