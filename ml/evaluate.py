"""Reproducible generation checks and a separate tune-disjoint Markov evaluation.

Run: .venv/Scripts/python.exe -m ml.evaluate --out document/AI_EVALUATION.md
Original datasets and models are read only. Derived data/model/results live in cache.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from analyze.theory import parse_chord
from ml.generate import bake_progression
from ml.model import MarkovModel
from ml.train.prepare_phrases import PREPARATION_VERSION, _read_wjazzd
from ml.train.train_markov import load_examples, split_by_tune, token_metrics, train_model
from player.timeline import ScaleOption, Segment, Timeline

EVALUATION_VERSION = "progression-reference-v1"
_ROOT = Path(__file__).resolve().parent.parent


def reference_fixtures():
    """Hand-authored reference progressions, independent of WJazzD/model training."""
    specs = [
        ("ii-V-I", "4/4", [0, 2, 4], [], [(0, 1, "Dm7"), (1, 2, "G7"), (2, 4, "Cmaj7")]),
        ("secondary", "4/4", [0, 2, 4], [], [(0, .7, "F#7"), (.7, 2.4, "Bm7"), (2.4, 4, "E7")]),
        ("dim-aug", "4/4", [0, 2, 4], [], [(0, 1.25, "Cdim7"), (1.25, 2.5, "Caug"), (2.5, 4, "Fmaj7")]),
        ("variable-3/4", "3/4", [0, 1.5, 3.6], [0, .4, .9, 1.5, 2.1, 2.9, 3.6],
         [(0, .8, "Dm7"), (.8, 1.7, "G7"), (1.7, 3.6, "Cmaj7")]),
        ("unsupported-goals", "4/4", [0, 2, 4], [], [(0, 1, "Csus4"), (1, 4, "C6")]),
    ]
    fixtures = []
    kinds = {"maj7": "메이저", "maj6": "메이저", "m7": "도리안", "dom7": "믹솔리디안",
             "dim7": "디미니시드", "aug": "온음", "sus4": "믹솔리디안"}
    for name, meter, bars, beats, chords in specs:
        tl = Timeline("", 120, meter, "C", 0, 2, bar_times=bars, beat_times=beats)
        for i, (start, end, name_chord) in enumerate(chords):
            chord = parse_chord(name_chord)
            kind = kinds[chord.quality]
            tl.segments.append(Segment(i, start, end, 0, 2, chord,
                                       [ScaleOption(kind, chord.root, kind, chord.chord_scale())]))
        fixtures.append((name, tl))
    return fixtures


def _reference_target(seg, goal):
    # Independent goal checks: a sixth is never scored as a seventh.
    thirds = {"maj": 4, "maj7": 4, "maj6": 4, "min": 3, "m7": 3, "m6": 3,
              "dom7": 4, "7": 4, "dim": 3, "dim7": 3, "m7b5": 3, "aug": 4}
    sevenths = {"maj7": 11, "m7": 10, "dom7": 10, "7": 10, "dim7": 9, "m7b5": 10}
    degree = (thirds if goal == "third" else sevenths).get(seg.chord.quality)
    pc = None if degree is None else (seg.chord.root + degree) % 12
    return pc if pc in seg.note_set else None


def _signature(notes):
    return [(n["midi"], n["start_sec"], n["duration_sec"], n["velocity"]) for n in notes]


def compare_generators(models, variants=(0, 1, 2, 3)):
    """The same fixed references, goals and variants for rule/bootstrap/legacy models."""
    fixtures = reference_fixtures()
    report = {"reference_fixture_count": len(fixtures), "fixture_names": [n for n, _ in fixtures],
              "variants": list(variants), "models": {}}
    for label, model in models.items():
        totals = Counter()
        sparse_notes = dense_notes = density_beats = 0
        for fixture_index in range(len(fixtures)):
            for goal in ("third", "seventh"):
                signatures = []
                for variant in variants:
                    _, tl = reference_fixtures()[fixture_index]
                    start, end = tl.segments[0].start_sec, tl.segments[-1].end_sec
                    result = bake_progression(tl, model, start, end, goal, variant)
                    notes = result["notes"]
                    totals["phrases"] += 1
                    totals["notes"] += len(notes)
                    totals["deterministic"] += result == bake_progression(tl, model, start, end, goal, variant)
                    signatures.append(_signature(notes))
                    for n in notes:
                        seg = tl.segment_at(n["start_sec"])
                        totals["scale_hits"] += n["midi"] % 12 in seg.note_set
                        totals["boundary_violations"] += n["start_sec"] + n["duration_sec"] > min(end, seg.end_sec) + 1e-8
                        totals["invalid_notes"] += not (start <= n["start_sec"] < end and
                            math.isfinite(n["duration_sec"]) and n["duration_sec"] > 0 and
                            0 <= n["midi"] <= 127 and 1 <= n["velocity"] <= 127)
                    checks = [(s, next((n for n in notes if abs(n["start_sec"] - s.start_sec) < 1e-8), None))
                              for s in tl.segments[1:]]
                    checks.append((tl.segments[-1], notes[-1] if notes else None))
                    for seg, note in checks:
                        target = _reference_target(seg, goal)
                        if target is None:
                            totals["unsupported_landings"] += 1
                        else:
                            totals["supported_landings"] += 1
                            totals["landing_hits"] += note is not None and note["midi"] % 12 == target
                totals["variation_checks"] += max(0, len(signatures) - 1)
                totals["variation_changes"] += sum(s != signatures[0] for s in signatures[1:])
            for variant in variants:
                _, tl = reference_fixtures()[fixture_index]
                end = tl.segments[-1].end_sec
                low = bake_progression(tl, model, 0, end, "third", variant, .6)
                high = bake_progression(tl, model, 0, end, "third", variant, 1.4)
                totals["density_checks"] += 1
                totals["density_increases"] += len(high["notes"]) > len(low["notes"])
                sparse_notes += len(low["notes"])
                dense_notes += len(high["notes"])
                density_beats += tl.beats_between(0, end)
        report["models"][label] = {
            **dict(totals), "scale_gate_rate": totals["scale_hits"] / max(1, totals["notes"]),
            "supported_landing_rate": totals["landing_hits"] / max(1, totals["supported_landings"]),
            "deterministic_rate": totals["deterministic"] / max(1, totals["phrases"]),
            "variation_rate": totals["variation_changes"] / max(1, totals["variation_checks"]),
            "density_increase_rate": totals["density_increases"] / max(1, totals["density_checks"]),
            "notes_per_beat_sparse": sparse_notes / max(1, density_beats),
            "notes_per_beat_dense": dense_notes / max(1, density_beats),
            "model_info": model.identity() if model else {"source": "rule", "sha256": None, "artifact": None},
        }
    return report


def _heldout_evaluation(db_path, cache_dir, bootstrap, seed):
    if not db_path.exists():
        return {"status": "unavailable", "reason": "WJazzD source database not available"}
    db_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    manifest = {"source_sha256": db_hash, "preparation_version": PREPARATION_VERSION}
    prepared = cache_dir / "phrases_identified.jsonl"
    manifest_path = cache_dir / "preparation_manifest.json"
    if prepared.exists() and manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8")) == manifest:
        examples = load_examples(prepared)
    else:
        examples = _read_wjazzd(db_path)
        prepared.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in examples), encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    data_hash = hashlib.sha256(prepared.read_bytes()).hexdigest()
    model = train_model(examples, seed=seed, dataset_sha256=data_hash)
    model_path = cache_dir / "markov_tune_holdout.json"
    model.save_json(model_path)
    model = MarkovModel.load_json(model_path)
    _, heldout = split_by_tune(examples, seed=seed)
    solo_instruments = {e["solo_id"]: e["instrument"] for e in examples}
    return {"status": "measured", "source_database_sha256": db_hash, "prepared_data": str(prepared),
            "dataset_sha256": data_hash, "preparation_version": PREPARATION_VERSION,
            "phrase_count": len(examples), "solo_count": len(solo_instruments),
            "instrument_solo_counts": dict(sorted(Counter(solo_instruments.values()).items())),
            "model_info": model.identity(),
            "conditional_metrics": {"uniform_reference": token_metrics(None, heldout),
                                    "bootstrap": token_metrics(bootstrap, heldout) if bootstrap else None,
                                    "tune_holdout_retrained": model.meta["heldout_metrics"]}}


def _markdown(report):
    comparison = report["generation_comparison"]
    lines = ["# ScaleRiff AI 평가", "", "재현 명령: `.venv/Scripts/python.exe -m ml.evaluate --out document/AI_EVALUATION.md`", "",
             f"평가 버전 `{EVALUATION_VERSION}`, 곡 분리 seed={report['seed']}. 고정 수작업 진행 "
             f"{comparison['reference_fixture_count']}개 × 3도/7도 목표 × 변주 {len(comparison['variants'])}개.", "",
             "이 진행은 WJazzD의 홀드아웃 정답 프레이즈가 아닌 독립적인 규칙 점검용 기준이다.", "",
             "| 생성 방식 | 프레이즈/음 수 | 스케일 게이트 | 경계 위반 | 지원 목표 착지 | 재현성 | 변주 변화 | 희박→조밀 음/박 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for label, row in comparison["models"].items():
        lines.append(f"| {label} | {row['phrases']}/{row['notes']} | {row['scale_gate_rate']:.1%} | "
                     f"{row.get('boundary_violations', 0)} | {row['supported_landing_rate']:.1%} | "
                     f"{row['deterministic_rate']:.1%} | {row['variation_rate']:.1%} | "
                     f"{row['notes_per_beat_sparse']:.3f}→{row['notes_per_beat_dense']:.3f} |")
    lines += ["", "목표 착지는 코드 변화 첫 음과 마지막 음으로 판정한다. 실제 코드와 배정 스케일에 없는 3도/7도는 "
              "지원 목표 분모에서 제외한다. C6의 6도를 7도로 취급하지 않는다.", ""]
    for label, row in comparison["models"].items():
        identity = row["model_info"]
        lines.append(f"- {label}: source=`{identity['source']}`, phrases={identity.get('phrases', 0)}, "
                     f"artifact=`{identity.get('artifact')}`, SHA256=`{identity.get('sha256')}`; "
                     f"미지원 착지 {row.get('unsupported_landings', 0)}건, 밀도 증가 "
                     f"{row['density_increases']}/{row['density_checks']}, 유효하지 않은 음 {row.get('invalid_notes', 0)}건.")
    if report["unavailable_models"]:
        lines += ["", "설치되지 않은 모델: " + ", ".join(report["unavailable_models"])]
    heldout = report["heldout_evaluation"]
    lines += ["", "## 곡 단위 재학습 평가", ""]
    if heldout["status"] == "measured":
        split = heldout["model_info"]["split"]
        lines += [f"WJazzD 읽기 전용 원본 SHA256: `{heldout['source_database_sha256']}`.", "",
                  f"준비 버전 `{heldout['preparation_version']}`; {heldout['phrase_count']}개 4/4 프레이즈, "
                  f"{heldout['solo_count']}개 솔로. 동일 composition ID의 모든 솔로·프레이즈를 한쪽에만 배치한다. "
                  f"곡 {split['train_group_count']}개 학습/{split['test_group_count']}개 검증, 겹침 {split['overlap_count']}개. "
                  f"프레이즈 {split['train_phrase_count']}개 학습/{split['test_phrase_count']}개 검증.", "",
                  f"준비 데이터 SHA256: `{heldout['dataset_sha256']}`; 재학습 모델 SHA256: "
                  f"`{heldout['model_info']['sha256']}`.", "",
                  "| 확률 모델 | 검증 토큰 수 | 조건부 토큰 log loss (nats) | 온셋 수 | 온셋 log loss (nats) |",
                  "|---|---:|---:|---:|---:|"]
        for label, metrics in heldout["conditional_metrics"].items():
            if metrics:
                lines.append(f"| {label} | {metrics['token_count']} | {metrics['token_log_loss']:.6f} | "
                             f"{metrics['onset_count']} | {metrics['onset_log_loss']:.6f} |")
        lines += ["", "모든 수치는 정답 이전 토큰과 코드군·스케일·박 위치를 조건으로 계산한 평균 음의 로그확률이며 낮을수록 좋다. "
                  "BOS를 제외한 14개 토큰에 0.001 평활화를 사용한다. uniform_reference는 규칙 생성기의 확률이 아닌 균등 확률 기준이다.", "",
                  "기존 15,512개 학습 모델은 원래 곡 분리 정보가 없어 일반화 log loss를 보고하지 않았다. "
                  "위 재학습 모델은 cache에 별도로 저장했으며 models/markov.json을 교체하지 않았다."]
    else:
        lines.append("홀드아웃 평가 미실행: " + heldout["reason"])
    lines += ["", "## 해석과 한계", "",
              "- 스케일 게이트·목표 착지·밀도·경계 준수는 생성 제약의 검사다. 세 방식의 음악적 우열, 자연스러움, 학습 효과를 증명하지 않는다.",
              "- 실연자 청취 평가와 학습자 전후 비교, 실제 MIDI 기기 검증은 수행하지 않았다.",
              "- 재학습은 4/4의 16분음표 양자화다. 3/4·가변 템포는 런타임 배치만 점검했으며 해당 미터의 학습 품질과 스윙은 검증하지 않았다.",
              "- WJazzD j7/o/- 표기를 지원 코드로 축약한다. altered/확장 화성 전체와 미세 리듬을 보존하지 않는다.",
              "- 스케일 라벨은 해당 프레이즈의 관측 음에서 유도한다. 조건부 log loss는 자동 스케일 추정이나 실제 앱 전체의 성능이 아니다.",
              "- 곡 분리는 제공된 composition ID에 의존한다. 동일 진행·인용구·곡명 변형을 넘어서는 음악적 유사성까지 제거한 것은 아니다.", "",
              f"기계 판독 결과: `{report['results_json']}`. 원본 data/phrases.jsonl과 models/*.json은 읽기만 했다.", ""]
    return "\n".join(lines)


def run_evaluation(out, wjazzd=None, cache_dir=None, seed=42):
    out = Path(out).resolve()
    cache_dir = Path(cache_dir or _ROOT / "cache" / "ai_evaluation").resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    models, unavailable = {"rule": None}, []
    for label, filename in (("bootstrap", "default_markov.json"), ("trained_legacy", "markov.json")):
        path = _ROOT / "models" / filename
        if path.exists():
            models[label] = MarkovModel.load_json(path)
        else:
            unavailable.append(label)
    report = {"evaluation_version": EVALUATION_VERSION, "seed": seed,
              "generation_comparison": compare_generators(models), "unavailable_models": unavailable,
              "heldout_evaluation": _heldout_evaluation(Path(wjazzd or _ROOT / "data" / "wjazzd.db"),
                                                        cache_dir, models.get("bootstrap"), seed),
              "results_json": str(cache_dir / "results.json")}
    Path(report["results_json"]).write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_markdown(report), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="document/AI_EVALUATION.md")
    parser.add_argument("--wjazzd", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    report = run_evaluation(args.out, args.wjazzd, args.cache_dir, args.seed)
    print(f"AI evaluation → {args.out}; heldout={report['heldout_evaluation']['status']}")


if __name__ == "__main__":
    main()
