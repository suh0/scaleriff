"""채점 엔진 단위 테스트 (§7.5) — 수제 타임라인으로 존 판정/착지/패스/보정 검증.

실행: python tests_scoring.py
"""
from analyze.theory import parse_chord
from player.timeline import Timeline, Segment, ScaleOption
from player.scoring import ScoreEngine

C_MAJOR = [0, 2, 4, 5, 7, 9, 11]


def make_tl() -> Timeline:
    """120bpm 4/4(마디=2초), 4마디, 루프 2마디: C(0~4s) → F(4~8s)."""
    def seg(idx, s, e, sb, eb, name):
        opt = ScaleOption("이오니안", 0, "C 이오니안", C_MAJOR)
        return Segment(idx=idx, start_sec=s, end_sec=e, start_bar=sb, end_bar=eb,
                       chord=parse_chord(name), candidates=[opt])
    return Timeline(
        audio_ref="", bpm=120.0, time_sig="4/4", key="C major", key_root=0,
        loop_len=2, segments=[seg(0, 0, 4, 0, 2, "C"), seg(1, 4, 8, 2, 4, "F")],
        content_span=(0.0, 8.0), bar_times=[0.0, 2.0, 4.0, 6.0, 8.0],
    )


def test_serialization():
    tl = make_tl()
    tl.loop_override = 8
    tl.loops = [{"name": "인트로", "start_bar": 0, "end_bar": 1, "on": True}]
    d = Timeline.from_dict(tl.to_dict())
    assert d.bar_times == [0.0, 2.0, 4.0, 6.0, 8.0]
    assert d.loop_phase == 0 and d.loop_override == 8 and d.split_point == 48
    assert d.loops == tl.loops and d.loops is not tl.loops
    # 구 JSON(새 키 없음) → 기본값
    old = tl.to_dict()
    for k in ("bar_times", "loop_phase", "loop_override", "split_point", "loops"):
        del old[k]
    d2 = Timeline.from_dict(old)
    assert d2.bar_times == [] and d2.split_point == 48 and d2.loop_override == 0
    assert d2.loops == []
    print("직렬화 OK")


def test_zones_and_out():
    eng = ScoreEngine(make_tl())
    assert [w[:2] for w in eng.windows] == [(0.0, 4.0), (4.0, 8.0)]
    eng.tick(0.01)                       # 패스 0 진입(유효)
    eng.note_on(36, 0.5)                 # C2 왼손(<C3 고정 분할), pc0 ∈ C코드톤 → 적중
    eng.note_on(72, 0.6)                 # C5 오른손, pc0 ∈ 스케일 → 적중
    eng.note_on(38, 0.7, screen=True)    # 화면건반은 낮아도 오른손 존
    eng.note_on(61, 0.8)                 # C#4 오른손, 스케일 밖
    eng.note_on(48, 0.9)                 # C3 = 분할점 자체는 오른손 존
    s = eng.cur
    assert (s.left_hits, s.left_total) == (1, 1)
    assert (s.right_hits, s.right_total) == (3, 4)
    assert s.out_counts == {1: 1} and s.top_out_pc() == 1
    print("존 판정/스케일 밖 OK")


def test_landing():
    eng = ScoreEngine(make_tl())
    eng.tick(0.01)
    beat = 0.5                            # 착지 창 ±0.125s
    eng.note_on(64, 2.0 + 0.1)            # E4, 마디1 첫박 +0.1s → 착지
    eng.note_on(64, 2.0 + 0.2)            # +0.2s → 창 밖
    eng.note_on(60, 2.0 + 0.05)           # 같은 마디 중복 → 1회만
    eng.note_on(62, 0.02)                 # D4 코드톤 아님 → 착지 아님
    assert eng._landed == {1}
    s = eng.tick(4.01)                     # 패스 완료
    assert s is not None
    assert (s.landing_hits, s.landing_opps) == (1, 2)
    print("코드톤 착지 OK")


def test_pass_and_trend():
    eng = ScoreEngine(make_tl())
    eng.tick(0.01)
    eng.note_on(72, 0.5)                  # 적중
    eng.note_on(61, 0.6)                  # 스케일 밖
    s = eng.tick(4.01)                     # 패스 1 완료 + 패스 2 진입(유효)
    assert s.number == 1 and s.right_pct() == 50
    assert eng.trend == [50]
    eng.note_on(77, 4.5)                  # F5, pc5 ∈ 스케일
    s2 = eng.tick(8.01)                    # 패스 2 완료
    assert s2.number == 2 and s2.right_pct() == 100
    assert eng.trend == [50, 100]
    print("패스 요약/추이 OK")


def test_seek_invalidates():
    eng = ScoreEngine(make_tl())
    eng.tick(0.01)
    eng.note_on(72, 0.5)
    eng.on_seek(5.0)                       # 스크럽 → 무효화
    eng.tick(5.0)                          # 패스 1 중간 진입(무효)
    eng.note_on(72, 5.5)
    assert eng.tick(8.01) is None          # 무효 패스 → 요약 없음
    assert eng.trend == []
    eng.on_seek(0.0)
    eng.tick(0.01)                         # 처음부터 재진입(유효)
    eng.note_on(72, 0.5)
    assert eng.tick(4.01) is not None
    print("seek 무효화 OK")


def test_override_rebuild():
    tl = make_tl()
    eng = ScoreEngine(tl)
    tl.loop_override = 4
    eng.rebuild()
    assert [w[:2] for w in eng.windows] == [(0.0, 8.0)]
    tl.loop_override = 0
    tl.loop_len = 0                        # 루프 미검출 → 곡 전체 1패스
    eng.rebuild()
    assert [w[:2] for w in eng.windows] == [(0.0, 8.0)]
    print("루프 override/미검출 OK")


def test_levels():
    eng = ScoreEngine(make_tl())
    eng.set_level(1)                       # Lv1: 왼손 근음 / 오른손 코드톤
    eng.tick(0.01)
    eng.note_on(36, 0.5)                   # C2 근음 → 왼손 적중
    eng.note_on(40, 0.6)                   # E2 코드톤이지만 Lv1 왼손은 근음만 → 미적중
    eng.note_on(76, 0.7)                   # E5 코드톤 → 오른손 적중
    eng.note_on(74, 0.8)                   # D5 스케일음이지만 Lv1 오른손은 코드톤만 → 미적중
    s = eng.cur
    assert (s.left_hits, s.left_total) == (1, 2)
    assert (s.right_hits, s.right_total) == (1, 2)
    assert s.out_counts == {}              # 스케일 안 음 — "스케일 밖" 집계와 무관
    assert eng.window_span(0.5) == (0.0, 4.0)
    eng.set_level(2)                       # 기준 변경 → 진행 중 패스 무효화
    assert eng.cur.right_total == 0
    eng.tick(0.01)                         # 재진입(유효)
    eng.note_on(74, 0.5)                   # Lv2 오른손 = 스케일 → 적중
    assert (eng.cur.right_hits, eng.cur.right_total) == (1, 1)
    print("난이도 레벨 OK")


def test_riff_match():
    eng = ScoreEngine(make_tl())
    eng.set_riff_events([(0.5, 72), (1.0, 74), (5.0, 76)])   # 3번째는 패스 2
    eng.set_mode("practice")
    eng.tick(0.01)
    eng.note_on(72, 0.55)      # 허용창(±0.125s@120bpm) 안 → 일치
    eng.note_on(72, 0.56)      # 같은 리프 음 중복 매칭 금지
    eng.note_on(74, 1.3)       # 창 밖(0.3s) → 미일치
    eng.note_on(60, 2.0)       # 리프에 없는 음 → 무시(감점 없음)
    s = eng.tick(4.01)
    assert (s.riff_hits, s.riff_total) == (1, 2) and s.riff_pct() == 50
    assert s.right_total == 0 and eng.trend == []   # 존 집계·추이 없음
    eng.set_mode("guide")      # 가이드 복귀 → 존별 채점으로
    eng.tick(0.01)
    eng.note_on(72, 0.5)
    assert eng.cur.right_total == 1 and eng.cur.riff_hits == 0
    print("리프 일치도 OK")


def main():
    test_serialization()
    test_zones_and_out()
    test_landing()
    test_pass_and_trend()
    test_seek_invalidates()
    test_override_rebuild()
    test_levels()
    test_riff_match()
    print("전체 통과")


if __name__ == "__main__":
    main()
