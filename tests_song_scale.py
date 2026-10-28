"""곡 전체 스케일 · 착지 목표 가능 판정 · 리프당 음 개수 리프."""
import unittest

from analyze.theory import parse_chord, song_scale_options, scale_pcs
from ml import generate
from player.timeline import ScaleOption, Segment, Timeline


def am_f_c_g(names=("Am", "F", "C", "G")):
    tl = Timeline("", 120, "4/4", "A minor", 9, 4, bar_times=[0, 2, 4, 6, 8])
    for i, name in enumerate(names):
        ch = parse_chord(name)
        tl.segments.append(Segment(i, 2 * i, 2 * i + 2, i, i + 1, ch,
                                   [ScaleOption("에올리안", ch.root, name, scale_pcs(9, "minor"))]))
    return tl


class SongScaleTest(unittest.TestCase):
    def test_options_recommend_pentatonic_first(self):
        pent, seven, blues = song_scale_options(9, "minor")
        self.assertEqual(set(pent["note_set"]), {9, 0, 2, 4, 7})
        self.assertEqual(set(seven["note_set"]), set(scale_pcs(9, "minor")))
        self.assertEqual(set(blues["note_set"]), {9, 0, 2, 3, 4, 7})
        self.assertEqual(song_scale_options(0, "major")[2]["root"], 9)   # 나란한조 블루스

    def test_apply_keeps_detour_and_clears_examples(self):
        tl = am_f_c_g()
        tl.segments[1].is_detour = True
        tl.segments[0].example = [{"midi": 69, "beat_pos": 0, "dur_beats": 1}]
        pent = song_scale_options(9, "minor")[0]
        tl.apply_song_scale(pent)
        self.assertEqual(tl.segments[0].note_set, pent["note_set"])
        self.assertNotEqual(tl.segments[1].note_set, pent["note_set"])
        self.assertEqual(tl.segments[0].example, [])
        self.assertEqual(Timeline.from_dict(tl.to_dict()).practice["scale"], pent)

    def test_landing_blockers_follow_scale(self):
        from gui.setup_screen import landing_blocker
        tl = am_f_c_g()
        pent, seven, _ = song_scale_options(9, "minor")
        self.assertIn("F", landing_blocker(tl, pent, "root"))
        self.assertIn("G", landing_blocker(tl, pent, "third"))
        self.assertIsNone(landing_blocker(tl, pent, "chord_tone"))
        self.assertIsNone(landing_blocker(tl, seven, "third"))
        self.assertIsNotNone(landing_blocker(tl, seven, "seventh"))   # 3화음엔 7도 없음

    def test_fit_recommends_by_chord_tones_and_disables_clashing_scale(self):
        from gui.setup_screen import scale_fit, recommend, landing_blocker
        tl = am_f_c_g()
        options = song_scale_options(9, "minor")
        self.assertAlmostEqual(scale_fit(tl, options[0]), 10 / 12)
        self.assertEqual(scale_fit(tl, options[1]), 1.0)
        self.assertEqual(recommend(tl, options), 1)                      # 7음
        self.assertEqual(recommend(am_f_c_g(("Am", "C", "Am", "C")), options), 0)   # 펜타
        clash = {"kind": "테스트", "root": 1, "name": "C# 테스트", "note_set": [1, 3, 6, 8, 10]}
        self.assertIn("Am", landing_blocker(tl, clash, "chord_tone"))
        self.assertEqual(recommend(tl, [clash, options[1]]), 1)

    def test_every_scale_option_has_a_guide(self):
        from gui.setup_screen import SCALE_GUIDE
        for root, mode in ((9, "minor"), (0, "major")):
            for option in song_scale_options(root, mode):
                self.assertIn(option["kind"], SCALE_GUIDE)

    def test_count_per_riff_and_landing(self):
        tl = am_f_c_g()
        tl.apply_song_scale(song_scale_options(9, "minor")[1])
        # 1마디 코드 2개 = 진입음 간격 4박 → 4박 공백 금지 때문에 최소 4음(3음은 보정으로 늘어남)
        for lo, hi in ((4, 4), (4, 6)):
            for variant in range(5):
                result = generate.bake_progression(tl, None, 0, 4, "third", variant, count=(lo, hi))
                self.assertTrue(lo <= len(result["notes"]) <= hi, len(result["notes"]))
                entry = next(n for n in result["notes"] if n["start_sec"] == 2)
                self.assertEqual(entry["midi"] % 12, generate._landing_pc(tl.segments[1], "third"))

    def test_riff_rules(self):
        tl = am_f_c_g()
        tl.apply_song_scale(song_scale_options(9, "minor")[1])
        for goal, count in ((None, None), ("third", (3, 3)), ("chord_tone", (4, 8))):
            for variant in range(10):
                result = generate.bake_progression(tl, None, 0, 4, goal, variant, count=count)
                notes = result["notes"]
                moved = generate.transpose_riff(tl, notes, 0, 4, goal)
                # 이론 규칙(착지음은 목표 고정이라 제외): 비화성음 순차·도약 후 반대 순차·정점 반복 금지
                land = {x["at_sec"] for x in result["landings"]}
                m = [n["midi"] for n in notes]
                for i in range(1, len(m)):
                    if notes[i]["start_sec"] in land:
                        continue
                    seg, prev = tl.segment_at(notes[i]["start_sec"]), tl.segment_at(notes[i - 1]["start_sec"])
                    step = generate._step(m[i - 1], m[i], seg.note_set)
                    if m[i] % 12 not in seg.chord_tones() or m[i - 1] % 12 not in prev.chord_tones():
                        self.assertTrue(step, (goal, variant, m))
                    if i >= 2 and abs(m[i - 1] - m[i - 2]) >= 5:
                        self.assertTrue(step and (m[i] - m[i - 1]) * (m[i - 1] - m[i - 2]) < 0, (goal, variant, m))
                    self.assertNotEqual(m[i], max(m[:i]), (goal, variant, m))
                    self.assertNotEqual(m[i], m[i - 1], (goal, variant, m))           # 같은 음 반복 금지
                    if i + 1 < len(m) and notes[i + 1]["start_sec"] in land:          # 착지 직전 ≠ 목표음
                        self.assertNotEqual(m[i] % 12, m[i + 1] % 12, (goal, variant, m))
                for ns in (notes, moved):
                    beats = [tl.beat_at(n["start_sec"]) - tl.beat_at(ns[0]["start_sec"]) for n in ns]
                    midis = [n["midi"] for n in ns]
                    self.assertTrue(all(b * 2 == int(b * 2) for b in beats), beats)        # 8분 격자
                    self.assertTrue(all(y - x < 4 for x, y in zip(beats, beats[1:] + [8])), beats)
                    off = [b % 1 != 0 for b in beats]
                    self.assertFalse(any(p and q for p, q in zip(off, off[1:])), beats)      # 엇박 연속
                    self.assertTrue(all(abs(y - x) < 12 for x, y in zip(midis, midis[1:])), midis)
                    if ns is notes:   # 도수 이동 후 같은 음 3연속은 미보장(README Todo)
                        self.assertFalse(any(a == b == c for a, b, c in zip(midis, midis[1:], midis[2:])),
                                         midis)

    def test_free_goal_stays_in_scale(self):
        tl = am_f_c_g()
        pent = song_scale_options(9, "minor")[0]
        tl.apply_song_scale(pent)
        result = generate.bake_progression(tl, None, 0, 8, None)
        self.assertTrue(result["notes"])
        self.assertEqual(result["landings"], [])
        self.assertTrue(all(n["midi"] % 12 in pent["note_set"] for n in result["notes"]))


if __name__ == "__main__":
    unittest.main()
