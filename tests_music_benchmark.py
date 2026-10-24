"""Independent benchmark metrics must not overcount time or duplicate beat detections."""
import unittest


class MusicBenchmarkMetricsTest(unittest.TestCase):
    def test_duration_weighted_chords_use_source_overlap(self):
        from tools.evaluate_music import chord_metrics
        truth = [(0, 1, "C"), (1, 3, "Am"), (3, 4, "F")]
        predicted = [(0, 2, "C"), (2, 3, "Am"), (3, 4, "Fm")]
        result = chord_metrics(truth, predicted)
        self.assertEqual(result["reference_sec"], 4)
        self.assertEqual(result["exact_correct_sec"], 2)
        self.assertEqual(result["root_correct_sec"], 3)
        self.assertEqual(result["exact_accuracy"], .5)
        self.assertEqual(result["root_accuracy"], .75)

    def test_duplicate_spans_do_not_inflate_accuracy_and_gaps_count_as_misses(self):
        from tools.evaluate_music import chord_metrics
        truth = [(0, 2, "C"), (2, 4, "Am")]
        duplicate = chord_metrics(truth, [(0, 2, "C"), (0, 2, "C")])
        self.assertEqual(duplicate["exact_accuracy"], .5)
        self.assertEqual(duplicate["coverage"], .5)
        self.assertEqual(duplicate["exact_correct_sec"], 2)
        unknown = chord_metrics([(0, 1, "C")], [(0, 1, "N")])
        self.assertEqual(unknown["root_accuracy"], 0)

    def test_duplicate_beats_cannot_match_one_reference_twice(self):
        from tools.evaluate_music import event_metrics
        result = event_metrics([0], [0, .01], tolerance=.07)
        self.assertEqual(result["matches"], 1)
        self.assertEqual(result["precision"], .5)
        self.assertEqual(result["recall"], 1)
        self.assertAlmostEqual(result["f1"], 2 / 3)

    def test_event_tolerance_and_empty_detections(self):
        from tools.evaluate_music import event_metrics
        result = event_metrics([0, 1, 2], [0, 1.08, 2.06], tolerance=.07)
        self.assertEqual(result["matches"], 2)
        self.assertAlmostEqual(result["f1"], 2 / 3)
        self.assertEqual(event_metrics([0, 1], [], .07)["f1"], 0)

    def test_synthesis_has_exact_source_times_and_reproducible_percussion(self):
        import numpy as np
        from tools.evaluate_music import synth_fixture
        sustained, truth = synth_fixture(percussive=False)
        percussive, second_truth = synth_fixture(percussive=True)
        repeated, _ = synth_fixture(percussive=True)
        self.assertEqual(truth["chords"][0], (0, 2.4, "C"))
        self.assertAlmostEqual(truth["chords"][-1][1], 19.2)
        self.assertEqual(len(truth["beats"]), 32)
        self.assertEqual(len(truth["downbeats"]), 8)
        self.assertEqual(truth["chords"], second_truth["chords"])
        self.assertEqual(len(sustained), 423360)
        self.assertFalse(np.array_equal(sustained, percussive))
        self.assertTrue(np.array_equal(percussive, repeated))
        self.assertLess(np.max(np.abs(percussive)), 1)

    def test_uniform_fallback_is_not_counted_as_detected_beats(self):
        from tools.evaluate_music import timing_metrics
        truth = {"beats": [0, .6, 1.2], "downbeats": [0]}
        result = timing_metrics(truth, [], [], [0, .6, 1.2], [0], .07)
        self.assertTrue(result["uniform_grid_fallback"])
        self.assertEqual(result["beat_metrics"]["f1"], 0)
        self.assertEqual(result["pipeline_beat_metrics"]["f1"], 1)
        self.assertEqual(result["downbeat_metrics"]["f1"], 0)

    def test_riff_counts_handle_numpy_scalar_times_and_remain_json_serializable(self):
        import json
        import numpy as np
        from tools.evaluate_music import riff_statistics
        from player.timeline import Timeline, Segment
        from analyze.theory import parse_chord
        tl = Timeline("", 120, "4/4", "C", 0, 1)
        tl.segments = [Segment(0, 0, 1, 0, 1, parse_chord("C"), example=[
            {"midi": 60, "beat_pos": np.float64(0), "dur_beats": np.float64(.5)},
            {"midi": 64, "beat_pos": np.float64(0), "dur_beats": np.float64(3)},
        ])]
        result = riff_statistics(tl)
        self.assertEqual(result["riff_note_count"], 2)
        self.assertEqual(result["invalid_riff_notes"], 1)
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
