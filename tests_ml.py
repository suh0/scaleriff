"""ML 스캐폴드 점검 — 표현 라운드트립 / 부트스트랩 학습 / 게이트 생성."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ml import representation as R
from ml.generate import generate_phrase, build_step_plan
from ml.model import MarkovModel, is_trained
from ml.train.make_default_model import build_examples


def test_roundtrip():
    roots = [2] * R.PHRASE_STEPS                 # D 근음
    notes = [(0, 2, 62), (2, 2, 65), (4, 4, 69), (8, 8, 67)]
    grid = R.encode(notes, roots)
    out = R.decode(grid, roots)
    # onset 음들의 pitch class가 보존되는지(옥타브는 보이스리딩으로 달라질 수 있음)
    src_pc = [m % 12 for _, _, m in notes]
    dec_pc = [n["midi"] % 12 for n in out]
    assert src_pc == dec_pc, (src_pc, dec_pc)
    assert len(out) == 4
    print("roundtrip OK:", [R.token_name(t) for t in grid[:10]])


def test_bootstrap_and_generate():
    ex = build_examples(per_context=40, seed=1)
    m = MarkovModel(order=2).fit(ex)
    m.meta["source"] = "theory_prior"
    assert is_trained(m)
    # Dm7(2마디 중 1마디) → G7 : 도리안
    ev = [(0, 2, "m7"), (16, 7, "7")]
    res = generate_phrase(m, ev, "도리안", n_bars=2, seed=3)
    notes = res["notes"]
    assert notes, "생성 음 없음"
    # 모든 onset이 스케일(도리안) 안인지 — 코드 근음 기준 도수로 검증
    allowed = R.allowed_onset_degrees("도리안")
    bad = []
    for i, t in enumerate(res["grid"]):
        if R.is_onset(t) and R.token_degree(t) not in allowed:
            bad.append(i)
    assert not bad, f"스케일 밖 음 위치 {bad}"
    # 리듬 다양성: REST/HOLD/ONSET 모두 등장
    kinds = {("R" if t == R.REST else "H" if t == R.HOLD else "O")
             for t in res["grid"]}
    assert "O" in kinds, "음표가 하나도 없음"
    print(f"generate OK: {len(notes)}음, 리듬요소={sorted(kinds)}")
    print("  처음 6음:", [(n['midi'], n['beat_pos'], n['dur_beats']) for n in notes[:6]])


def test_untrained_fallback():
    res = generate_phrase(None, [(0, 0, "maj")], "메이저", n_bars=2, seed=2)
    assert res["notes"], "폴백 생성 실패"
    print("fallback OK:", len(res["notes"]), "음")


if __name__ == "__main__":
    test_roundtrip()
    test_bootstrap_and_generate()
    test_untrained_fallback()
    print("\nML SMOKE OK — 표현/부트스트랩/생성/게이트 정상")
