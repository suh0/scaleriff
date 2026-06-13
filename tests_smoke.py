"""헤드리스 스모크 테스트 — 타임라인/후보 스케일/악보 흐름/플레이어 점검.

QT_QPA_PLATFORM=offscreen 으로 실행한다.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from gui.app import AppWindow
from player.dummy_timeline import build_dummy_timeline


def main():
    app = QApplication(sys.argv)
    win = AppWindow()

    tl = build_dummy_timeline()
    print(f"타임라인: {tl.title} | {tl.key} | 종류 {tl.available_scales}")

    # 코드별 단일 다이아토닉 스케일 — 7모드에서 한 코드=한 스케일(§3)
    DIATONIC_7 = {"아이오니안", "도리안", "프리지안", "리디안",
                  "믹솔리디안", "에올리안", "로크리안"}
    assert set(tl.available_scales) <= DIATONIC_7, \
        f"다이아토닉 외 스케일: {tl.available_scales}"
    assert tl.segments[0].scale_name == "D 도리안", tl.segments[0].scale_name   # Dm7=ii
    assert tl.segments[1].scale_name == "G 믹솔리디안", tl.segments[1].scale_name  # G7=V
    assert tl.segments[2].scale_name == "C 아이오니안", tl.segments[2].scale_name  # Cmaj7=I
    # 한 코드=한 스케일이므로 어떤 마디도 선택 가능하면 안 됨
    assert not any(s.has_options() for s in tl.segments), "마디가 선택 가능하면 안 됨"
    for s in tl.segments[:3]:
        print(f"  [{s.idx}] {s.chord.name:6} {s.degree:4} → {s.scale_name}")

    # 마디↔구간 매핑
    assert tl.total_bars() == len(tl.segments)
    assert tl.segment_for_bar(0) is tl.segments[0]

    # 화면 흐름: 분석완료 → 악보(디버그용) → 연습(메인)
    win._on_timeline_ready(tl)
    assert win.stack.currentWidget() is win.score
    # 악보 화면: 사용된 스케일 칩이 종류 수만큼 생성 + 첫 스케일이 기본 선택됐는지
    assert len(win.score._kind_btns) == len(tl.scale_riffs), "스케일 칩 수 불일치"
    assert win.score._sel_kind in tl.scale_riffs, "기본 선택 스케일 없음"
    win.score._show_riff(list(tl.scale_riffs)[-1])     # 다른 스케일 선택 → 리프 갱신
    assert win.score._sel_kind == list(tl.scale_riffs)[-1]
    win.score.practiceRequested.emit()
    assert win.stack.currentWidget() is win.main_screen

    # 렌더 + 입력 + 모드토글
    ms = win.main_screen
    ms._render_at(0.3)
    ms._render_at(tl.segments[1].start_sec + 0.1)
    ms.on_midi_note(64, True)
    ms.on_midi_note(64, False)

    # 리프연습 ON/OFF 토글 + 리프 뷰 표시 연동
    ms._toggle_riff(); assert ms._mode == "practice" and not ms.riff.isHidden()
    ms._toggle_riff(); assert ms._mode == "guide" and ms.riff.isHidden()

    # 카운트인: 구간 끝 4박 전부터 점등(매 틱 갱신 경로)
    s0 = tl.segments[0]
    ms._update_live(s0.end_sec - tl.beat_sec() * 2.0)   # 2박 남음
    assert ms.countin._lit == 2, ms.countin._lit

    # ML 리프: 스케일 '종류당 1개' (코드 등장마다가 아님, §8)
    assert tl.scale_riffs, "scale_riffs 미생성"
    assert set(tl.scale_riffs) == set(tl.available_scales), \
        f"종류당 1개 아님: {set(tl.scale_riffs)} vs {set(tl.available_scales)}"
    dorian_segs = [s for s in tl.segments if s.scale and s.scale.kind == "도리안"]
    assert len(dorian_segs) >= 2 and dorian_segs[0].example == dorian_segs[1].example, \
        "같은 종류·근음인데 리프가 다름(종류당 1개 위반)"
    assert all(s.example for s in tl.segments), "구간 이조 example 미생성"

    # 리프 구성 제약(§1·§2): 1마디 / 박당 단음 ≤1회 / 코드톤·스케일음 ≥2 /
    #   스케일음 3연속 금지 / 스케일 밖 음 없음
    from collections import Counter as _Counter
    for kind, d in tl.scale_riffs.items():
        assert d["n_bars"] == 1, f"{kind} 1마디 아님"
        cts, ns = set(d["chord_tones"]), set(d["note_set"])
        notes = sorted(d["notes"], key=lambda n: n["beat_pos"])
        assert all(n["beat_pos"] < 4 for n in notes), f"{kind} 1마디 초과"
        seq = ["C" if n["midi"] % 12 in cts else ("S" if n["midi"] % 12 in ns else "x")
               for n in notes]
        assert "x" not in seq, f"{kind} 스케일 밖 음: {seq}"
        assert seq.count("C") >= 2 and seq.count("S") >= 2, f"{kind} 코드톤/스케일음 부족 {seq}"
        run = 0
        for c in seq:
            run = run + 1 if c == "S" else 0
            assert run < 3, f"{kind} 스케일음 3연속: {seq}"
        per_beat = _Counter(int(n["beat_pos"]) for n in notes)
        singles = sum(1 for c in per_beat.values() if c == 1)
        assert singles <= 1, f"{kind} 단음 박 {singles}회: {sorted(per_beat.items())}"
        # 같은 음 연속 금지
        midis = [n["midi"] for n in notes]
        assert all(midis[i] != midis[i + 1] for i in range(len(midis) - 1)), \
            f"{kind} 같은 음 연속: {midis}"
        # §1 한 옥타브 안([60,71], 음역폭 ≤11반음)
        assert all(60 <= m <= 71 for m in midis), f"{kind} 옥타브 범위 밖: {midis}"
        assert max(midis) - min(midis) <= 11, f"{kind} 한 옥타브 초과: {midis}"
        # §2 음 길이 다양(서로 다른 dur_beats ≥2종)
        durs = {round(n["dur_beats"], 3) for n in notes}
        assert len(durs) >= 2, f"{kind} 음 길이 단조로움: {durs}"
        # §2(신규) 마디 첫 박(beat_pos<1)은 코드톤만
        first_beat = [n for n in notes if n["beat_pos"] < 1.0]
        assert first_beat and all(n["midi"] % 12 in cts for n in first_beat), \
            f"{kind} 첫 박에 비코드톤: {[(n['beat_pos'], n['midi']%12) for n in first_beat]}"

    # §3 같은 코드 2마디 → 리프 2회 반복(타일링)
    from ml.generate import bake_examples as _bake
    from player.timeline import Timeline as _TL, Segment as _Seg, ScaleOption as _SO
    from analyze.theory import parse_chord as _pc
    seg2 = _Seg(idx=0, start_sec=0.0, end_sec=4.0, start_bar=0, end_bar=2,  # 2마디
                chord=_pc("Dm7"),
                candidates=[_SO("도리안", 2, "D 도리안", [0, 2, 3, 5, 7, 9, 10])])
    tl2 = _TL(audio_ref="", bpm=120, time_sig="4/4", key="C major", key_root=0,
              loop_len=2, segments=[seg2])
    _bake(tl2, ms._ml_model)
    one = tl2.scale_riffs["도리안"]["notes"]
    assert len(seg2.example) == 2 * len(one), "2마디인데 리프 2회 반복 아님"
    assert any(n["beat_pos"] >= 4 for n in seg2.example), "둘째 마디에 리프 없음"
    # §3 타일 이음새 포함 스케일음 3연속 금지(전체 example 기준)
    #    example은 코드 근음으로 이조됨 → 코드톤도 같은 양만큼 이동해 비교
    root2 = seg2.chord.root; shift2 = root2 if root2 <= 6 else root2 - 12
    cts2 = {(c + shift2) % 12 for c in tl2.scale_riffs["도리안"]["chord_tones"]}
    seq2 = ["C" if n["midi"] % 12 in cts2 else "S"
            for n in sorted(seg2.example, key=lambda n: n["beat_pos"])]
    r = 0
    for c in seq2:
        r = r + 1 if c == "S" else 0
        assert r < 3, f"타일 후 스케일음 3연속: {seq2}"
    # §3 가이드는 2마디 반복 구간이어도 늘 1마디만 표시
    from gui.widgets.riff_view import RiffView as _RV
    _rv = _RV(); _rv.set_segment(seg2, tl2.bpm, tl2.time_sig_beats())
    assert _rv._total_beats == tl2.time_sig_beats(), f"가이드 1마디 아님: {_rv._total_beats}"
    assert all(n["beat_pos"] < tl2.time_sig_beats() for n in _rv._notes), "가이드에 2마디째 음"
    # §2 리프가 곡에 함께 구워짐(재생 헤드 동기) — 일시정지/시킹과 함께 동작
    ms._toggle_riff()                       # 연습 ON → 이벤트 생성
    assert ms._riff_events and ms._riff_times == sorted(ms._riff_times), "리프 이벤트 정렬"
    mid = tl.segments[1].start_sec
    ms._seek_riff_idx(mid)
    assert all(t < mid for t in ms._riff_times[:ms._riff_idx]), "시킹 커서 오류(앞)"
    assert all(t >= mid for t in ms._riff_times[ms._riff_idx:]), "시킹 커서 오류(뒤)"
    ms._toggle_riff()                       # OFF

    # §1 수동 코드 수정: 악보 화면에서 한 마디 코드를 바꾸면 스케일·리프 재계산
    win.score.set_timeline(tl, ms._ml_model)
    s0 = tl.segments[0]                      # Dm7 → Fmaj7로 수정
    win.score._apply_chord(s0, "Fmaj7")
    assert s0.chord.name == "Fmaj7" and s0.scale_name == "F 리디안", \
        f"수동 수정 실패: {s0.chord.name}/{s0.scale_name}"
    assert s0.example, "수정 후 리프 미생성"
    assert "리디안" in tl.scale_riffs, "새 스케일 종류 리프 미생성"
    print(f"  scale_riffs: {list(tl.scale_riffs)}  riff_events={len(ms._riff_events)}  "
          f"(모델 {'O' if ms._ml_model else 'X'})")

    print("\nSMOKE OK — 스케일/악보+수동수정/리프동기재생/구성제약(첫박·단음·3연속·옥타브) 정상")


if __name__ == "__main__":
    main()
