"""리프 음표의 낙하·건반 정렬·구간 이동 검사."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage as _QImage, QRegion
from PyQt6.QtWidgets import QApplication
from gui.main_screen import MainScreen
from player.dummy_timeline import build_dummy_timeline


def main():
    app = QApplication([])
    screen = MainScreen()
    tl = build_dummy_timeline()
    screen.set_timeline(tl)
    for seg in tl.segments:
        seg.example = []
    tl.segments[0].example = [
        {"midi": 62, "beat_pos": 2, "dur_beats": 0.5},
        {"midi": 66, "beat_pos": 3, "dur_beats": 1.0},
    ]
    screen.resize(1040, 740)
    screen.show()
    app.processEvents()
    screen._select_practice("riff")
    screen._on_seek(0)
    before = screen.riff._nodes()
    assert len(before) == 2
    assert abs(before[1][3] - before[0][3] * 2) < 1e-6, "1박 막대는 반 박 막대의 두 배 길이"
    screen._on_seek(0.6)
    after = screen.riff._nodes()
    assert all(b[1] > a[1] for a, b in zip(before, after)), "박자 진행에 따라 아래로 낙하"
    app.processEvents()
    assert screen.riff._nodes() == after, "일시정지 중 노드 정지"
    screen.piano.set_pressed({62, 66})
    assert screen.riff._nodes() == after, "눌린 건반도 리프 예고 유지"
    screen._on_seek(1.2)
    node = screen.riff._nodes()[0]
    assert abs(node[1] + node[3] - screen.riff.height()) < 1e-6, "해당 박자에 막대 아래 끝 도착"
    stage = screen.stage
    for x, _, _, _, _ in screen.riff._nodes():
        lane_end = stage._xf.map(QPointF(x, screen.riff.height()))
        key_top = stage._kxf.map(QPointF(x, stage._lane_h))
        assert (lane_end - key_top).manhattanLength() <= 1.5, "원근 레인 끝이 건반 윗선과 이어짐"
        assert stage._midi_at(stage._kxf.map(QPointF(x, stage._lane_h + 2))) in (62, 66), \
            "흰 건반·흑건의 실제 위치와 노드 정렬(역변환 클릭 판정)"
    # 실제 건반 기하: C#은 경계보다 왼쪽·D#은 오른쪽, 흑건은 솟아 있고 옆면, 눌리면 앞만 내려감
    whites, x0, _, kw, _ = screen.piano._geometry()
    boundary = lambda m: x0 + (whites.index(m - 1) + 1) * kw
    assert stage._key_rect(61).center().x() < boundary(61) < stage._key_rect(63).center().x() - kw
    w_top, w_front, _ = stage._faces(62)
    b_top, _, b_sides = stage._faces(61)
    assert b_top[3].y() < stage._kxf.map(stage._key_rect(61).bottomLeft()).y() and len(b_sides) == 2
    p_top, p_front, _ = stage._faces(62, pressed=True)
    assert p_top[0] == w_top[0] and p_top[3].y() > w_top[3].y(), "뒤 축 고정, 앞이 내려감"
    assert p_front.boundingRect().height() < w_front.boundingRect().height(), "눌리면 앞면이 짧아짐"
    screen._on_seek(1.21)
    assert len(screen.riff._nodes()) == 2, "음표 길이 동안 막대 유지"
    assert screen.riff._nodes()[0][1] > node[1], "음표 길이에 맞춰 건반 안으로 내려감"
    screen._on_seek(1.5)
    assert len(screen.riff._nodes()) == 1, "끝난 음표는 제거"
    screen._on_seek(0)
    assert screen.riff._nodes() == before, "되감기 시 노드 초기화"
    screen._on_seek(2.3)
    assert len(screen.riff._nodes()) == 1, "긴 음표는 종료까지 유지"
    screen._on_seek(2.41)
    assert not screen.riff._nodes()
    # 타격 판정: ±60ms PERFECT, ±180ms EARLY/LATE, 밖·다른 음은 판정 없음, 맞힌 노드는 사라짐
    riff = screen.riff
    t62 = next(w for w, m, _, _ in riff._events if m == 62)
    screen._on_seek(t62 - 0.5)
    assert riff.judge(62, t62 - 0.3) is None and riff.judge(60, t62) is None
    assert riff.judge(62, t62 - 0.1)[0] == "EARLY"
    assert riff.judge(62, t62) is None, "같은 노드 두 번 판정 안 함"
    assert all(abs(x - riff._x(62)) > 1 for x, *_ in riff._nodes()), "맞힌 노드 사라짐"
    screen._on_seek(t62 - 1.0)                       # 되감기 → 다시 나타남
    assert any(abs(x - riff._x(62)) < 1 for x, *_ in riff._nodes())
    assert riff.judge(62, t62 + 0.03)[0] == "PERFECT"
    screen._on_seek(t62 - 1.5)
    label, x = riff.judge(62, t62 + 0.1)
    assert label == "LATE" and abs(x - riff._x(62)) < 1e-6
    screen.stage.splash(label, x)
    screen.stage.render(_QImage(screen.stage.size(), _QImage.Format.Format_ARGB32_Premultiplied))
    assert screen.stage._splash_areas and screen.stage._sparkle_timer.isActive(), "스플래시 동작"
    screen.stage._splashes = [(c, r, t - 1.0, l) for c, r, t, l in screen.stage._splashes]
    screen.stage.render(_QImage(screen.stage.size(), _QImage.Format.Format_ARGB32_Premultiplied))
    assert not screen.stage._splashes, "수명 지나면 정리"
    screen._on_seek(2.41)
    screen._select_practice("riff")
    screen._render_at(1.0)
    assert screen.riff.show_notes
    screen._select_practice("free")
    screen._render_at(1.0)
    assert screen.stage.isVisible() and not screen.riff.show_notes
    assert not screen.riff._nodes(), "자유모드: 모니터박스는 있되 노드 없음"
    # 모니터박스 코드: 경계 4박 전부터 다음 코드가 커지고, 재생 중 바뀌면 이전 코드를 밀어냄
    seg0, seg1 = tl.segments[1], tl.segments[2]
    beat = tl.beat_sec()
    screen._render_at(seg0.start_sec)
    cur, _, nxt, prev, grow, push = screen.chord_hdr._chords
    assert (cur, nxt, prev, grow, push) == (seg0.chord.name, seg1.chord.name, "", 0.0, 1.0)
    screen._render_at(seg1.start_sec - 2 * beat)
    assert abs(screen.chord_hdr._chords[4] - 0.5) < 1e-6, "4박 창 절반에서 grow 0.5"
    screen.playhead.is_playing = lambda: True
    screen._render_at(seg1.start_sec + 0.25 * beat)
    cur, _, _, prev, _, push = screen.chord_hdr._chords
    assert (cur, prev) == (seg1.chord.name, seg0.chord.name) and abs(push - 0.5) < 1e-6
    screen._render_at(seg1.start_sec + beat)
    assert screen.chord_hdr._chords[3] == "" and screen.chord_hdr._chords[5] == 1.0, "push 끝나면 이전 코드 제거"
    del screen.playhead.is_playing
    # 코드 전환선: 경계 4박 전부터 낙하, 경계에서 레인 끝 도착(자유모드에서도)
    lane_h = screen.riff.height()
    screen._render_at(seg1.start_sec - 2 * beat)
    lines = screen.riff._chord_lines()
    assert len(lines) == 1 and abs(lines[0] - lane_h * 0.5) < 1, lines
    screen._render_at(seg1.start_sec)
    assert any(abs(y - lane_h) < 1e-6 for y in screen.riff._chord_lines()), "경계 시각에 레인 끝"
    assert screen.riff._beat_lines(), "자유모드에도 박자선"
    # 원근 클릭: 각 건반 윗면(화면 좌표) 클릭 → 그 음
    for midi in range(60, 84):
        r = stage._key_rect(midi)
        y = r.top() + r.height() * (0.3 if midi % 12 in (1, 3, 6, 8, 10) else 0.85)
        assert stage._midi_at(stage._kxf.map(QPointF(r.center().x(), y))) == midi, midi
    # 스케일 표시 = 건반 앞면 색(일반모드), 리프모드에선 없음
    from gui import theme as T
    from gui.widgets.stage import TONE_CHORD, TONE_ROOT, TONE_SCALE
    screen._select_practice("free")
    colors = {stage._state_color(m).name() for m in range(60, 84) if stage._state_color(m)}
    assert colors == {TONE_ROOT, TONE_CHORD, TONE_SCALE}, colors
    assert [stage._node_color(c).name() for c in (T.BADGE_ROOT, T.BADGE_CHORD, T.BADGE_SCALE)] ==         [TONE_ROOT, TONE_CHORD, TONE_SCALE], "노드도 같은 파란 계열 진하기"
    screen._select_practice("riff")
    assert all(stage._state_color(m) is None for m in range(60, 84)), "리프모드는 스케일 표시 없음"
    screen._select_practice("free")
    # 근음 반짝이: 일반모드엔 근음 건반 앞면에서 타이머 동작, 근음 없으면 정지
    from PyQt6.QtGui import QImage as _Img
    probe = _Img(stage.size(), _Img.Format.Format_ARGB32_Premultiplied)
    stage.render(probe)
    assert stage._sparkle_areas and stage._sparkle_timer.isActive(), "근음 반짝이 동작"
    import time as _t
    t0 = _t.perf_counter()
    for area in stage._sparkle_areas * 10:
        stage.render(probe, sourceRegion=QRegion(area))
    print(f"  sparkle tick {(_t.perf_counter() - t0) / 10 * 1000:.2f}ms")
    saved = screen.piano._chord_root
    screen.piano._chord_root = None                  # 코드 근음 없음(예비박 등) → 반짝이 없음
    stage.render(probe)
    assert not stage._sparkle_areas and not stage._sparkle_timer.isActive(), "근음 없으면 타이머 정지"
    screen.piano._chord_root = saved
    # 양 끝 건반(앞면 포함)까지 화면 안
    for midi in (60, 83):
        area = stage._kxf.mapRect(stage._key_rect(midi)).adjusted(0, 0, 0, stage._lip())
        assert stage.rect().toRectF().contains(area), (midi, area)
    # 스페이스 = 재생 토글 + 재생바 잠깐 표시
    assert screen.scrub_row.isHidden(), "재생바 기본 숨김"
    playing = screen.playhead.is_playing()
    screen._on_space()
    assert screen.playhead.is_playing() != playing and not screen.scrub_row.isHidden()
    assert screen.play_btn.isHidden() == screen.playhead.is_playing(), "가운데 재생 아이콘은 멈춤일 때만"
    screen.playhead.pause()
    screen._hide_scrub()
    assert screen.scrub_row.isHidden(), "타이머 만료 후 재생바 숨김"
    # 비용: 정적 레이어는 캐시, 프레임·연타는 캐시 재생성 없음
    import time
    from PyQt6.QtGui import QImage
    screen._select_practice("riff")
    img = QImage(stage.size(), QImage.Format.Format_ARGB32_Premultiplied)
    stage.render(img)
    builds = stage.cache_builds
    seg = tl.segments[1]
    t0 = time.perf_counter()
    for i in range(60):
        screen._render_at(seg.start_sec + i * 0.02)
        stage.render(img)
    frame_ms = (time.perf_counter() - t0) / 60 * 1000
    t0 = time.perf_counter()
    for i in range(200):
        midi = 60 + i % 24
        screen.on_midi_note(midi, i % 2 == 0)
        stage.render(img, sourceRegion=QRegion(stage._screen_rect(midi)))
    key_ms = (time.perf_counter() - t0) / 200 * 1000
    print(f"  frame {frame_ms:.2f}ms · key {key_ms:.2f}ms · cache builds +{stage.cache_builds - builds}")
    assert frame_ms < 16 and key_ms < 16, "프레임 예산 16ms 초과"
    screen.close()
    print("FALLING NOTES OK")


if __name__ == "__main__":
    main()
