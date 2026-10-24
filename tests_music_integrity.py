"""음악 데이터 손실과 원본 시간축의 회귀 검사."""
import unittest

from analyze.structure import structure_from_grid
from ingest.mir_extract import ChordSpan
from build.real_builder import regrid_timeline
from player.dummy_timeline import build_dummy_timeline
from player.timeline import Timeline


class MusicIntegrityTest(unittest.TestCase):
    def test_content_start_never_discards_harmonic_attack_for_downbeat(self):
        import numpy as np
        from ingest.mir_extract import detect_content_span
        sr = 22050
        y = .1 * np.sin(2 * np.pi * 220 * np.arange(4 * sr) / sr)
        start, _ = detect_content_span(y, sr, 4, [1.8, 4.0],
                                       [ChordSpan(0, 4, "C")], 2.4,
                                       log=lambda _: None, y_harm=y)
        self.assertLess(start, .05)

    def test_music_before_first_downbeat_is_kept(self):
        from ingest.mir_extract import MirResult
        from analyze.structure import analyze_structure
        mir = MirResult(100, [.03, .63, 1.23, 1.83, 2.43, 3.03, 3.63],
                        "C major", 0, "major", chords=[ChordSpan(0, 4, "C")],
                        duration=4, downbeat_times=[1.83, 4], content_span=(0, 4))
        st = analyze_structure(mir)
        self.assertEqual(st.segments[0].start_sec, 0)

    def test_chord_edit_after_negative_preroll_has_no_negative_notes(self):
        from build.real_builder import apply_chord_edit
        tl = build_dummy_timeline()
        tl.bpm, tl.bar_times, tl.chord_spans = 120, [0, 2, 4], [[0, 4, "C"]]
        regrid_timeline(tl, anchor_sec=-2)
        apply_chord_edit(tl, 0, 2, "F")
        self.assertTrue(all(s.start_sec >= 0 for s in tl.segments))
        self.assertIsNone(tl.segment_at(-1))

    def test_named_scale_matches_guide_and_generated_riff(self):
        from analyze.harmony import analyze_harmony
        from analyze.structure import RawSegment
        from analyze.theory import diatonic_option
        from ml.representation import SCALE_DEGREES
        from ml.generate import generate_scale_riff
        for name in ("Cdim7", "Caug"):
            h = analyze_harmony([RawSegment(0, 1, 0, 2, name)], 0, "major", 1, True)[0]
            o = diatonic_option(h.chord, h.home_root, h.home_mode, h.is_detour, h.note_set)
            allowed = set(SCALE_DEGREES[o["kind"]])
            self.assertEqual(set(o["note_set"]), allowed, name)
            self.assertLessEqual(set(h.chord.chord_tones()), allowed, name)
            self.assertTrue(all(n["midi"] % 12 in allowed
                                for n in generate_scale_riff(None, o["kind"])))

    def test_two_chords_inside_one_bar(self):
        st = structure_from_grid([0, 2], [ChordSpan(0, 1, "Dm7"),
                                         ChordSpan(1, 2, "G7")], 2, 4)
        self.assertEqual([(s.start_sec, s.end_sec, s.chord_name) for s in st.segments],
                         [(0, 1, "Dm7"), (1, 2, "G7")])

    def test_manual_chord_survives_regrid_and_roundtrip(self):
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [0, 2, 4, 6]
        tl.chord_spans = [[0, 6, "C"]]
        tl.chord_overrides = [[1, 3, "Fmaj7"]]
        tl = Timeline.from_dict(tl.to_dict())
        self.assertTrue(regrid_timeline(tl, anchor_sec=0.2))
        self.assertEqual(tl.segment_at(1.5).chord.name, "Fmaj7")
        self.assertEqual(tl.segment_at(3.5).chord.name, "C")
        self.assertEqual(tl.chord_spans, [[0, 6, "C"]])

    def test_variable_grid_beat_roundtrip(self):
        tl = build_dummy_timeline()
        tl.bar_times = [0, 2, 5]
        tl.beat_times = [0, .4, 1, 1.5, 2, 2.6, 3.3, 4.1, 5]
        self.assertAlmostEqual(tl.time_at_beat(5), 2.6)
        self.assertAlmostEqual(tl.beat_at(4.1), 7)
        self.assertAlmostEqual(tl.beats_between(1, 4.1), 5)
        for sec in (-1, 0, .7, 2.6, 4.8, 6):
            self.assertAlmostEqual(tl.time_at_beat(tl.beat_at(sec)), sec)

    def test_regrid_preserves_loop_audio_interval(self):
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [0, 2, 4, 6, 8]
        tl.chord_spans = [[0, 8, "C"]]
        tl.loops = [{"name": "연습", "start_bar": 1, "end_bar": 2, "on": True}]
        regrid_timeline(tl, anchor_sec=.5)
        self.assertEqual((tl.loops[0].get("start_sec"), tl.loops[0].get("end_sec")), (2, 6))

    def test_three_quarter_riff_stays_in_segment(self):
        from ml.generate import bake_examples
        tl = build_dummy_timeline()
        tl.time_sig = "3/4"
        tl.bpm = 120
        tl.bar_times = [0, 1.5, 3, 4.5, 6, 7.5, 9]
        tl.beat_times = []
        for s in tl.segments:
            s.start_sec, s.end_sec = tl.bar_times[s.start_bar], tl.bar_times[s.end_bar]
        bake_examples(tl, None)
        for s in tl.segments:
            for n in s.example:
                self.assertLessEqual(n["beat_pos"] + n["dur_beats"],
                                     tl.beats_between(s.start_sec, s.end_sec) + 1e-7)


if __name__ == "__main__":
    unittest.main()
