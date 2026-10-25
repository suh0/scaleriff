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
from player.scoring import reference_notes
from player.timeline import Timeline
from tools.evaluate_music import SR, synth_fixture


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_audio_edit_copy_score_autosave_and_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio, _ = synth_fixture(percussive=True)
            source = root / "source.wav"
            sf.write(source, audio, SR)
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("save_dir", str(root / "sessions"))
            with patch("ingest.audio_source._CACHE_DIR", str(root)), \
                    patch("player.audio_stretch._CACHE", root / "practice_audio"), \
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
                    apply_chord_edit(timeline, 0, 2.4, "Dm7", screen._ml_model)
                    apply_chord_edit(timeline, 2.4, 4.8, "G7", screen._ml_model)
                    timeline.loops = [{"name": "통합 검사", "start_bar": 0, "end_bar": 1,
                                       "start_sec": 0, "end_sec": 4.8, "on": True}]
                    timeline.bpm = 100
                    self.assertTrue(regrid_timeline(timeline, screen._ml_model, anchor_sec=0))
                    self.assertEqual(timeline.segment_at(.5).chord.name, "Dm7")
                    self.assertEqual(timeline.segment_at(3.0).chord.name, "G7")
                    window._enter_score()
                    window._enter_main()
                    screen._select_practice("riff")
                    self.assertTrue(screen.playhead.set_rate(.75))
                    slowed = screen.playhead._prepared[.75]
                    self.assertAlmostEqual(sf.info(slowed).duration, len(audio) / SR / .75, delta=.1)
                    start, end = timeline.loops[0]["start_sec"], timeline.loops[0]["end_sec"]
                    reference = reference_notes(timeline, start, end)
                    self.assertGreater(len(reference), 3)
                    screen._start_take(start)
                    events = []
                    for note in reference:
                        for is_on, sec in ((True, note["start_sec"]),
                                           (False, note["start_sec"] + note["duration_sec"])):
                            events.append((sec, {"type": "note", "pitch": note["midi"],
                                                "is_on": is_on, "velocity": 83, "channel": 2}))
                    for sec, event in sorted(events, key=lambda row: (row[0], row[1]["is_on"])):
                        with patch.object(screen.playhead, "position_sec", return_value=sec):
                            screen.on_midi_event(event)
                    self.assertFalse(screen.piano._pressed)
                    summary = screen._finish_take(end)
                    self.assertEqual(summary["score"], 100)
                    saved = Timeline.load_json(window._session_path(timeline))
                    self.assertEqual(saved.chord_overrides, timeline.chord_overrides)
                    self.assertEqual(saved.loops[0]["end_sec"], 4.8)
                    self.assertEqual(saved.practice_history[0]["summary"]["score"], 100)
                    self.assertEqual(saved.practice_history[0]["notes"][0]["velocity"], 83)
                    self.assertEqual(saved.model_info["sha256"], screen._ml_model.identity()["sha256"])
                    screen.set_timeline(saved)
                    self.assertFalse(screen.recorder.active)
                finally:
                    window.main_screen.pause()
                    window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
