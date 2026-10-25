"""실제 WAV 분석→수동 보정→느린 연습→MIDI 이벤트→채점→자동 저장/복원.

실기기 대신 원본 시각에 맞춘 MIDI 이벤트를 주입한다. MIR/변환/저장은 실제 수행한다.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import soundfile as sf
from PyQt6.QtCore import QCoreApplication, QEvent, QSettings
from PyQt6.QtWidgets import QApplication

from build.real_builder import apply_chord_edit, build_real_timeline, regrid_timeline
from gui.app import AppWindow
from ingest.mir_extract import get_backend
from player.timeline import Timeline
from tools.evaluate_music import SR, synth_fixture


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_audio_edit_riff_practice_and_autosave(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio, _ = synth_fixture(percussive=True)
            source = root / "source.wav"
            sf.write(source, audio, SR)
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("save_dir", str(root / "sessions"))
            with patch("ingest.audio_source._CACHE_DIR", str(root)), \
                    patch("build.real_builder.get_backend", return_value=get_backend("librosa")), \
                    patch("gui.app.QSettings", return_value=settings), \
                    patch.object(AppWindow, "_try_start_midi"):
                timeline = build_real_timeline(str(source))
                self.assertTrue(timeline.analysis_info["beat_detected"])
                window = AppWindow()
                try:
                    screen = window.main_screen
                    screen.note_player.set_volume(0)
                    window._on_timeline_ready(timeline)
                    self.assertIs(window.stack.currentWidget(), window.beat)
                    apply_chord_edit(timeline, 0, 2.4, "Dm7")
                    apply_chord_edit(timeline, 2.4, 4.8, "G7")
                    timeline.loops = [{"name": "통합 검사", "start_bar": 0, "end_bar": 1,
                                       "start_sec": 0, "end_sec": 4.8, "on": True}]
                    timeline.bpm = 100
                    self.assertTrue(regrid_timeline(timeline, anchor_sec=0))
                    self.assertEqual(timeline.segment_at(.5).chord.name, "Dm7")
                    self.assertEqual(timeline.segment_at(3.0).chord.name, "G7")
                    window._enter_setup()
                    window._enter_main()
                    from gui.riff_dialog import RiffDialog
                    RiffDialog(timeline, screen._ml_model, screen).accept()   # 리프학습모드 확정
                    screen._select_practice("riff")
                    window._save_session(timeline)
                    saved = Timeline.load_json(window._session_path(timeline))
                    self.assertEqual(saved.chord_overrides, timeline.chord_overrides)
                    self.assertEqual(saved.loops[0]["end_sec"], 4.8)
                    self.assertEqual(saved.model_info["sha256"], screen._ml_model.identity()["sha256"])
                    screen.set_timeline(saved)
                    self.assertTrue(screen._riff_events)
                finally:
                    window.main_screen.pause()
                    window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
