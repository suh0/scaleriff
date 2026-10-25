"""Progression conditioning and reproducible, tune-separated evaluation."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from analyze.theory import parse_chord
from ml import generate
from ml.model import MarkovModel
from ml.train import prepare_phrases, train_markov
from ml.train.make_default_model import build_examples
from player.timeline import ScaleOption, Segment, Timeline


def progression_fixture():
    tl = Timeline("", 120, "4/4", "C", 0, 2, bar_times=[0, 2, 4, 6])
    for i, (start, end, chord, kind, pcs) in enumerate([
        (0, 1, "Dm7", "도리안", [0, 2, 4, 5, 7, 9, 11]),
        (1, 2, "G7", "믹솔리디안", [0, 2, 4, 5, 7, 9, 11]),
        (2, 4, "Cmaj7", "메이저", [0, 2, 4, 5, 7, 9, 11]),
        (4, 6, "F#7", "믹솔리디안", [1, 3, 4, 6, 8, 10, 11]),
    ]):
        ch = parse_chord(chord)
        tl.segments.append(Segment(i, start, end, int(start // 2),
                                   int((end + 1.99) // 2), ch,
                                   [ScaleOption(kind, ch.root, kind, pcs)],
                                   example=[{"midi": 60 + ch.root, "beat_pos": 0,
                                             "dur_beats": .5}]))
    return tl


class ProgressionTest(unittest.TestCase):
    def test_progression_uses_actual_chords_and_target_landings(self):
        tl = progression_fixture()
        result = generate.bake_progression(tl, None, 0, 4, goal="third")
        notes = result["notes"]
        self.assertTrue(notes)
        self.assertEqual(next(n for n in notes if n["start_sec"] == 1)["midi"] % 12, 11)
        self.assertEqual(next(n for n in notes if n["start_sec"] == 2)["midi"] % 12, 4)
        self.assertEqual(notes[-1]["midi"] % 12, 4)
        self.assertEqual(result["goal"], "third")
        for n in notes:
            seg = tl.segment_at(n["start_sec"])
            self.assertIn(n["midi"] % 12, seg.note_set)
            self.assertGreater(n["duration_sec"], 0)
            self.assertLessEqual(n["start_sec"] + n["duration_sec"], seg.end_sec + 1e-8)
            self.assertLessEqual(n["start_sec"] + n["duration_sec"], 4 + 1e-8)
            self.assertTrue(1 <= n["velocity"] <= 127)

    def test_actual_note_set_gates_custom_scales_and_unsupported_targets(self):
        tl = progression_fixture()
        tl.segments[0].candidates[0].note_set = [2, 9]  # deliberately excludes F
        result = generate.bake_progression(tl, None, 0, 1, "third")
        self.assertTrue(all(n["midi"] % 12 in [2, 9] for n in result["notes"]))
        self.assertFalse(result["landings"][-1]["supported"])
        self.assertIsNone(result["landings"][-1]["target_pc"])
        tl.segments[0].chord = parse_chord("C6")
        tl.segments[0].candidates[0].note_set = [0, 4, 7, 9]
        result = generate.bake_progression(tl, None, 0, 1, "seventh")
        self.assertFalse(result["landings"][-1]["supported"], "sixth must not be treated as seventh")

    def test_seventh_landings_and_variable_tempo_use_source_seconds(self):
        tl = progression_fixture()
        tl.beat_times = [0, .4, 1, 1.6, 2, 2.6, 3.1, 3.6, 4, 4.5, 5, 5.5, 6]
        result = generate.bake_progression(tl, None, .4, 4, "seventh")
        self.assertEqual(next(n for n in result["notes"] if n["start_sec"] == 1)["midi"] % 12, 5)
        self.assertEqual(result["notes"][-1]["midi"] % 12, 11)
        for seg in tl.segments[:3]:
            for note in seg.example:
                start = tl.time_at_beat(tl.beat_at(seg.start_sec) + note["beat_pos"])
                if .4 <= start < 4:
                    actual = next(n for n in result["notes"] if abs(n["start_sec"] - start) < 1e-7)
                    end = tl.time_at_beat(tl.beat_at(start) + note["dur_beats"])
                    self.assertAlmostEqual(end - start, actual["duration_sec"])

    def test_selected_interval_preserves_unselected_examples(self):
        tl = progression_fixture()
        tl.segments[2].example = [{"midi": 67, "beat_pos": 0, "dur_beats": .25},
                                   {"midi": 71, "beat_pos": 3, "dur_beats": .25}]
        original = copy.deepcopy([s.example for s in tl.segments])
        generate.bake_progression(tl, None, 2.5, 3.25)
        self.assertEqual(tl.segments[0].example, original[0])
        self.assertEqual(tl.segments[1].example, original[1])
        self.assertEqual(tl.segments[3].example, original[3])
        self.assertIn(original[2][0], tl.segments[2].example)
        self.assertIn(original[2][1], tl.segments[2].example)

    def test_density_variation_and_repeated_generation_are_deterministic(self):
        a = generate.bake_progression(progression_fixture(), None, 0, 4, variant=0, density=.6)
        again = generate.bake_progression(progression_fixture(), None, 0, 4, variant=0, density=.6)
        b = generate.bake_progression(progression_fixture(), None, 0, 4, variant=1, density=.6)
        dense = generate.bake_progression(progression_fixture(), None, 0, 4, variant=0, density=1.4)
        self.assertEqual(a, again)
        self.assertNotEqual(a["notes"], b["notes"])
        self.assertGreater(len(dense["notes"]), len(a["notes"]))

    def test_tiny_chord_segments_and_three_quarter_meter(self):
        tl = progression_fixture()
        tl.time_sig = "3/4"
        tl.bar_times = [0, 1.5, 3, 4.5, 6]
        tl.segments[0].end_sec = .03
        tl.segments[1].start_sec = .03
        result = generate.bake_progression(tl, None, 0, 3)
        self.assertTrue(any(n["start_sec"] == .03 for n in result["notes"]))
        self.assertLessEqual(result["notes"][0]["duration_sec"], .03)
        self.assertTrue(all(n["start_sec"] + n["duration_sec"] <= 3 + 1e-8
                            for n in result["notes"]))

    def test_fractional_beat_roundoff_does_not_duplicate_chord_entry(self):
        tl = progression_fixture()
        tl.beat_times = [0, .4, 1, 1.6, 2, 2.6, 3.1, 3.6, 4, 4.5, 5, 5.5, 6]
        tl.segments[0].end_sec = .3
        tl.segments[1].start_sec = .3
        result = generate.bake_progression(tl, None, 0, 4, density=3)
        near_entry = [n for n in result["notes"] if abs(n["start_sec"] - .3) < 1e-7]
        self.assertEqual(len(near_entry), 1)
        self.assertTrue(all(n["duration_sec"] > 1e-6 for n in result["notes"]))

    def test_bootstrap_covers_new_named_scales(self):
        examples = build_examples(per_context=1)
        self.assertGreaterEqual(len(examples), 11)


class ProvenanceTest(unittest.TestCase):
    def test_initial_riffs_save_generation_provenance(self):
        model = MarkovModel().fit(build_examples(per_context=1))
        timeline = progression_fixture()
        generate.bake_examples(timeline, model)
        self.assertEqual(timeline.model_info, model.identity())
        generate.bake_examples(timeline, None)
        self.assertEqual(timeline.model_info["source"], "rule")
        self.assertIsNone(timeline.model_info["sha256"])

    def test_loaded_model_fingerprint_tracks_actual_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "model.json"
            MarkovModel().fit([{"grid": [3, 2, 1], "qfam": ["maj"] * 3,
                                "scale": "메이저"}]).save_json(path)
            loaded = MarkovModel.load_json(path)
            info = loaded.identity()
            self.assertEqual(info["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(info["artifact"], str(path.resolve()))
            self.assertEqual(info["phrases"], 1)

    def test_tune_split_is_stable_and_rejects_unidentified_legacy_data(self):
        examples = [{"tune_id": tune, "solo_id": solo,
                     "grid": [3, 2, 1, 7], "qfam": ["maj"] * 4, "scale": "메이저"}
                    for tune in ("song-a", "song-b", "song-c", "song-d") for solo in (1, 2)]
        train, test = train_markov.split_by_tune(examples, seed=17, test_fraction=.25)
        again_train, again_test = train_markov.split_by_tune(list(reversed(examples)), seed=17, test_fraction=.25)
        self.assertFalse({e["tune_id"] for e in train} & {e["tune_id"] for e in test})
        self.assertEqual({e["tune_id"] for e in test}, {e["tune_id"] for e in again_test})
        self.assertEqual(len(again_train), 6)
        model = train_markov.train_model(examples, seed=17, test_fraction=.25)
        self.assertEqual(model.meta["split"]["train_group_count"], 3)
        self.assertEqual(model.meta["split"]["test_group_count"], 1)
        self.assertEqual(model.meta["split"]["overlap_count"], 0)
        self.assertEqual(model.meta["phrases"], 6)
        self.assertGreater(model.meta["heldout_metrics"]["token_count"], 0)
        self.assertEqual(len(model.meta["dataset_sha256"]), 64)
        with self.assertRaisesRegex(ValueError, "tune_id"):
            train_markov.split_by_tune([{"grid": [3]}, {"grid": [4]}])

    def test_wjazzd_preparation_retains_ids_and_chords_on_rest_steps(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "wjazzd.db"
            con = sqlite3.connect(path)
            con.executescript("CREATE TABLE melody(melid INTEGER,onset REAL,duration REAL,pitch REAL,bar INTEGER,beat INTEGER);"
                              "CREATE TABLE beats(melid INTEGER,bar INTEGER,beat INTEGER,onset REAL,chord TEXT,signature TEXT);"
                              "CREATE TABLE solo_info(melid INTEGER,compid INTEGER,title TEXT,performer TEXT,instrument TEXT);")
            con.execute("INSERT INTO solo_info VALUES(7,99,'Same Tune','Player','ts')")
            for bar in range(1, 4):
                for beat in range(1, 5):
                    t = (bar - 1) * 2 + (beat - 1) * .5
                    con.execute("INSERT INTO beats VALUES(?,?,?,?,?,?)",
                                (7, bar, beat, t, "Cj7" if t < 1 else "G7", "4/4"))
            for t in (0, .25, 2, 2.25):
                con.execute("INSERT INTO melody VALUES(?,?,?,?,?,?)",
                            (7, t, .1, 64, int(t // 2) + 1, 1))
            con.commit()
            con.close()
            examples = prepare_phrases._read_wjazzd(path)
            self.assertEqual(len(examples), 1)
            ex = examples[0]
            self.assertEqual(ex["solo_id"], 7)
            self.assertEqual(ex["tune_id"], "wjazzd:composition:99")
            self.assertEqual(ex["title"], "Same Tune")
            self.assertEqual(ex["performer"], "Player")
            self.assertEqual(ex["instrument"], "ts")
            self.assertEqual(ex["qfam"][7:10], ["maj", "dom", "dom"])
            self.assertEqual(prepare_phrases._wjazzd_chord("Cj7").quality, "maj7")
            self.assertEqual(prepare_phrases._wjazzd_chord("Bo7").quality, "dim7")
            self.assertEqual(prepare_phrases._wjazzd_chord("D-79").quality, "m7")


class PatternTest(unittest.TestCase):
    def _song(self):
        tl = Timeline("", 120, "4/4", "C", 0, 2, bar_times=[0, 2, 4, 6, 8, 10, 12])
        diatonic = [0, 2, 4, 5, 7, 9, 11]
        for i, (bar, name, detour) in enumerate([(0, "Dm7", 0), (1, "G7", 0), (2, "G7", 0), (3, "Cmaj7", 0),
                                                 (4, "Dm7", 0), (5, "F#7", 1)]):
            ch = parse_chord(name)
            pcs = [1, 3, 4, 6, 8, 10, 11] if detour else diatonic
            tl.segments.append(Segment(i, bar * 2, bar * 2 + 2, bar, bar + 1, ch,
                                       [ScaleOption("믹솔리디안" if detour else "메이저", ch.root,
                                                    "F# 믹솔리디안" if detour else "C 메이저", pcs)],
                                       is_detour=bool(detour)))
        return tl

    def test_patterns_follow_scale_changes_not_chords(self):
        patterns = generate.chord_patterns(self._song())
        self.assertEqual([(p["label"], len(p["spans"])) for p in patterns],
                         [("C 메이저", 2), ("C 메이저→F# 믹솔리디안", 1)])   # ii–V·V–I는 같은 패턴
        self.assertEqual(generate.allocate(patterns, 2), [1, 1])
        self.assertEqual(generate.allocate(patterns, 3), [2, 1])   # 자주 나오는 패턴부터
        self.assertEqual(generate.allocate(patterns, 9), [2, 1])   # 등장 횟수 상한

    def test_transpose_moves_by_scale_degree_and_keeps_landings(self):
        tl = self._song()
        riff = [{"midi": m, "start_sec": t, "duration_sec": .4, "velocity": 80}
                for m, t in ((62, 0), (65, .5), (69, 1), (71, 2))]   # Dm7: D F A | G7: B
        out = generate.transpose_riff(tl, riff, 0, 4, "third", landing_secs=[2])
        self.assertEqual([n["start_sec"] for n in out], [4, 4.5, 5, 6])
        self.assertEqual([n["midi"] for n in out], [67, 71, 74, 64])   # G7: G B D | Cmaj7: E
        self.assertTrue(all(n["midi"] % 12 in tl.segments[0].note_set for n in out))


class EvaluationTest(unittest.TestCase):
    def test_fixed_reference_metrics_check_gates_density_and_reproducibility(self):
        from ml import evaluate
        report = evaluate.compare_generators({"rule": None}, variants=(0, 1))
        self.assertGreater(report["reference_fixture_count"], 0)
        row = report["models"]["rule"]
        self.assertEqual(row["scale_gate_rate"], 1)
        self.assertEqual(row["boundary_violations"], 0)
        self.assertEqual(row["supported_landing_rate"], 1)
        self.assertEqual(row["deterministic_rate"], 1)
        self.assertEqual(row["density_increase_rate"], 1)
        self.assertGreater(row["notes_per_beat_dense"], row["notes_per_beat_sparse"])
        self.assertGreater(row["unsupported_landings"], 0)


if __name__ == "__main__":
    unittest.main()
