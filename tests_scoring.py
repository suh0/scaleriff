"""과제별 점수의 정당성: 중복음/무연주/시킹/경과음."""
import unittest
from player.dummy_timeline import build_dummy_timeline
from ml.generate import bake_examples


class ScoringTest(unittest.TestCase):
    def test_fast_repeated_notes_maximize_valid_matches_before_timing_cost(self):
        from player.scoring import score_performance
        self.tl.bpm = 120
        self.tl.bar_times = [0, 2, 4]
        self.tl.beat_times = []
        self.tl.segments[0].example = [
            {"midi": 65, "beat_pos": .24 * i, "dur_beats": .1} for i in range(4)]
        notes = [{"midi": 65, "start_sec": .12 * i + .11, "duration_sec": .05}
                 for i in range(4)]
        result = score_performance(self.tl, notes, "riff", start=0, end=1)
        self.assertEqual(result["matched"], 4)
        self.assertEqual(result["missing"], 0)
        self.assertEqual(result["extra"], 0)
        self.assertLess(result["rhythm"], .2)

    def test_unavailable_seventh_does_not_penalize_scale_task(self):
        from analyze.theory import parse_chord
        from player.scoring import score_performance
        self.tl.segments[0].chord = parse_chord("C")
        notes = [{"midi": 60, "start_sec": 0, "duration_sec": .3}]
        result = score_performance(self.tl, notes, "scale", level=2, start=0, end=2.4, goal="seventh")
        self.assertEqual(result["landing_targets"], 0)
        self.assertEqual(result["score"], 100, "코드에 없는 7도를 놓쳤다고 감점함")

    def setUp(self):
        self.tl = build_dummy_timeline()
        bake_examples(self.tl, None)

    def reference(self):
        from player.scoring import reference_notes
        return reference_notes(self.tl, 0, 2.4)

    def test_perfect_copy_and_missing_extra_penalties(self):
        from player.scoring import score_performance
        notes = self.reference()
        perfect = score_performance(self.tl, notes, "riff", start=0, end=2.4)
        self.assertAlmostEqual(perfect["score"], 100)
        missing = score_performance(self.tl, notes[:1], "riff", start=0, end=2.4)
        extra = score_performance(self.tl, notes + notes, "riff", start=0, end=2.4)
        self.assertLess(missing["score"], perfect["score"])
        self.assertLess(extra["score"], perfect["score"])
        self.assertEqual(extra["matched"], len(notes))

    def test_no_notes_is_not_zero_and_zero_reference_is_not_perfect(self):
        from player.scoring import score_performance
        self.assertIsNone(score_performance(self.tl, [], "riff", start=0, end=2.4)["score"])
        for s in self.tl.segments:
            s.example = []
        self.assertIsNone(score_performance(self.tl, [{"midi": 60, "start_sec": 0,
                            "duration_sec": .2}], "riff", start=0, end=2.4)["score"])

    def test_free_passing_note_does_not_reduce_landing_goal(self):
        from player.scoring import score_performance
        anchor = [{"midi": 65, "start_sec": 0, "duration_sec": .4}]
        passing = anchor + [{"midi": 66, "start_sec": .7, "duration_sec": .1}]
        a = score_performance(self.tl, anchor, "free", start=0, end=2.4, goal="third")
        b = score_performance(self.tl, passing, "free", start=0, end=2.4, goal="third")
        self.assertEqual(a["score"], b["score"])
        self.assertGreater(b["outside_scale"], a["outside_scale"])

    def test_rhythm_delay_reduces_copy_score(self):
        from player.scoring import score_performance
        notes = self.reference()
        delayed = [dict(n, start_sec=n["start_sec"] + .4) for n in notes]
        self.assertLess(score_performance(self.tl, delayed, "riff", start=0, end=2.4)["score"], 90)

    def test_recorder_repeated_pitch_pedal_and_cancel(self):
        from player.performance import PerformanceRecorder
        rec = PerformanceRecorder()
        rec.begin(0)
        rec.event({"type": "note", "pitch": 60, "is_on": True, "velocity": 80}, 0)
        rec.event({"type": "note", "pitch": 60, "is_on": True, "velocity": 90}, .2)
        rec.event({"type": "pedal", "down": True}, .3)
        rec.event({"type": "note", "pitch": 60, "is_on": False}, .4)
        rec.event({"type": "pedal", "down": False}, .8)
        notes = rec.finish(1)
        self.assertEqual([n["velocity"] for n in notes], [80, 90])
        self.assertAlmostEqual(notes[0]["duration_sec"], .2)
        self.assertAlmostEqual(notes[1]["duration_sec"], .6)
        self.assertAlmostEqual(notes[1]["key_duration_sec"], .2)
        rec.begin(0)
        rec.event({"type": "note", "pitch": 64, "is_on": True}, .1)
        rec.cancel()
        self.assertEqual(rec.finish(1), [])


if __name__ == "__main__":
    unittest.main()
