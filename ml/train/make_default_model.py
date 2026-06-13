"""기본(부트스트랩) Markov 모델 생성 — 데이터 없이 이론 프라이어로.

규칙 기반 생성기(generate.rule_based_grid)로 다양한 (스케일·코드군) 컨텍스트의
프레이즈를 합성해 그걸로 Markov를 학습 → models/default_markov.json.
실데이터(WJazzD)로 학습하기 전, 앱이 바로 example_phrase를 굽도록 부트스트랩.

실행: venv\\Scripts\\python.exe -m ml.train.make_default_model
"""
from __future__ import annotations
import os
import random

from ml.representation import PHRASE_STEPS, STEPS_PER_BAR, SCALE_DEGREES
from ml.generate import rule_based_grid, _enforce_min_tones
from ml.model import MarkovModel

# 스케일 종류별로 함께 등장할 법한 코드군 (7다이아토닉 모드 전체)
_SCALE_QFAMS = {
    "메이저": ["maj", "dom"], "아이오니안": ["maj"], "리디안": ["maj"],
    "마이너": ["min", "dim"], "에올리안": ["min"],
    "도리안": ["min"], "프리지안": ["min"],
    "믹솔리디안": ["dom"], "로크리안": ["dim"],
}
_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "models", "default_markov.json")


def _random_plan(qfam_choices, rng):
    """2마디(32칸) 동안 1~2개 코드군 배치 → 칸별 qfam/scale-friendly."""
    n = PHRASE_STEPS
    if rng.random() < 0.5:                      # 마디마다 코드 바뀜
        a, b = rng.choice(qfam_choices), rng.choice(qfam_choices)
        return [a] * STEPS_PER_BAR + [b] * (n - STEPS_PER_BAR)
    q = rng.choice(qfam_choices)
    return [q] * n


def build_examples(per_context=400, seed=0):
    rng = random.Random(seed)
    examples = []
    for scale_kind in SCALE_DEGREES:
        qfam_choices = _SCALE_QFAMS[scale_kind]
        for _ in range(per_context):
            qfams = _random_plan(qfam_choices, rng)
            grid = rule_based_grid(qfams, scale_kind, PHRASE_STEPS, rng)
            # 학습 데이터에도 코드톤·스케일음 ≥2씩 제약 반영(§구성)
            grid = _enforce_min_tones(grid, qfams, scale_kind, rng)
            examples.append({"grid": grid, "qfam": qfams,
                             "scale": [scale_kind] * PHRASE_STEPS})
    return examples


def main():
    examples = build_examples()
    model = MarkovModel(order=2)
    model.fit(examples)
    model.meta["source"] = "theory_prior"
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    model.save_json(_OUT)
    print(f"[make_default_model] {len(examples)}개 합성 프레이즈로 학습 → {_OUT}")
    print(f"  컨텍스트 키 {len(model.table)}개, phrases={model.meta['phrases']}")


if __name__ == "__main__":
    main()
