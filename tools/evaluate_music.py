"""Local MIR benchmark: known source timing, real build, riff baking and session roundtrip.

Run from repository root: .venv/Scripts/python.exe tools/evaluate_music.py
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import soundfile as sf

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analyze.theory import parse_chord

BENCHMARK_VERSION = "source-overlap-v1"
SR, BPM, SEED = 22050, 100, 42


def synth_fixture(percussive=False):
    beat_samples = SR * 60 // BPM
    bar_samples = beat_samples * 4
    progression = ["C", "Am", "F", "G"] * 2
    voicings = {"C": [60, 64, 67], "Am": [57, 60, 64], "F": [53, 57, 60], "G": [55, 59, 62]}
    t = np.arange(bar_samples) / SR
    envelope = np.ones(bar_samples)
    attack = int(.02 * SR)
    envelope[:attack] = np.linspace(0, 1, attack)
    envelope[-attack:] = np.linspace(1, 0, attack)
    blocks = []
    for chord in progression:
        block = np.zeros(bar_samples)
        for midi in voicings[chord]:
            frequency = 440 * 2 ** ((midi - 69) / 12)
            block += np.sin(2 * np.pi * frequency * t) + .3 * np.sin(4 * np.pi * frequency * t)
        blocks.append(block * envelope / 3)
    harmony = np.concatenate(blocks)
    harmony *= .65 / np.max(np.abs(harmony))
    percussion = np.zeros(len(harmony))
    if percussive:
        rng = np.random.default_rng(SEED)
        pt = np.arange(int(.12 * SR)) / SR
        frequencies = np.fft.rfftfreq(len(pt), 1 / SR)
        for i in range(32):
            spectrum = np.fft.rfft(rng.normal(size=len(pt)))
            spectrum[(frequencies < 1800) | (frequencies > 7000)] = 0
            noise = np.fft.irfft(spectrum, n=len(pt))
            noise /= max(1e-9, np.max(np.abs(noise)))
            noise *= np.exp(-pt / .018)
            kick_phase = 2 * np.pi * (55 * pt + 70 * .018 * (1 - np.exp(-pt / .018)))
            kick = np.sin(kick_phase) * np.exp(-pt / .035)
            accent = 1.35 if i % 4 == 0 else 1.0
            pulse = accent * (.13 * kick + .075 * noise)
            start = i * beat_samples
            percussion[start:start + len(pt)] += pulse
    beat = beat_samples / SR
    truth = {"bpm": BPM, "key": "C major", "duration_sec": len(harmony) / SR,
             "chords": [(i * 4 * beat, (i + 1) * 4 * beat, c) for i, c in enumerate(progression)],
             "beats": [i * beat for i in range(32)], "downbeats": [i * 4 * beat for i in range(8)],
             "harmonic_rms": float(np.sqrt(np.mean(harmony ** 2))),
             "percussion_rms": float(np.sqrt(np.mean(percussion ** 2)))}
    return (harmony + percussion).astype(np.float32), truth


def _chord_signature(name):
    if not name or name in ("N", "N.C.", "NC", "none"):
        return None
    chord = parse_chord(name)
    return chord.root, chord.quality


def chord_metrics(reference, predicted):
    """Duration-weighted exact/root accuracy on original source seconds, including gaps.

    Atomic intervals count once even for duplicate predicted spans. For overlapping
    predictions the first listed label wins; normal MIR output is nonoverlapping.
    """
    boundaries = sorted({t for rows in (reference, predicted) for start, end, _ in rows for t in (start, end)})
    total = exact = root = covered = 0.0
    for start, end in zip(boundaries, boundaries[1:]):
        midpoint = (start + end) / 2
        gold = next((name for a, b, name in reference if a <= midpoint < b), None)
        if gold is None:
            continue
        guess = next((name for a, b, name in predicted if a <= midpoint < b), None)
        duration = end - start
        gold_label, guess_label = _chord_signature(gold), _chord_signature(guess)
        total += duration
        covered += duration if guess_label is not None else 0
        exact += duration if guess_label is not None and guess_label == gold_label else 0
        root += duration if guess_label is not None and gold_label is not None and guess_label[0] == gold_label[0] else 0
    return {"reference_sec": total, "covered_sec": covered, "exact_correct_sec": exact,
            "root_correct_sec": root, "exact_accuracy": exact / total if total else 0,
            "root_accuracy": root / total if total else 0, "coverage": covered / total if total else 0}


def event_metrics(reference, predicted, tolerance=.07):
    """Maximum chronological one-to-one matches at an explicit absolute tolerance."""
    gold, guesses = sorted(reference), sorted(predicted)
    i = j = matches = 0
    errors = []
    while i < len(gold) and j < len(guesses):
        delta = guesses[j] - gold[i]
        if abs(delta) <= tolerance:
            matches += 1
            errors.append(abs(delta))
            i += 1
            j += 1
        elif delta < 0:
            j += 1
        else:
            i += 1
    precision = matches / len(guesses) if guesses else 0
    recall = matches / len(gold) if gold else 0
    return {"reference_count": len(gold), "predicted_count": len(guesses), "matches": matches,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "tolerance_sec": tolerance, "mean_abs_error_sec": sum(errors) / matches if matches else None}


def timing_metrics(truth, tracked_beats, tracked_downbeats, pipeline_beats, pipeline_downbeats, tolerance):
    """Keep detected timing separate from a synthetic grid inserted after tracking fails."""
    return {"uniform_grid_fallback": len(tracked_beats) < 2,
            "beats": [float(t) for t in tracked_beats], "downbeats": [float(t) for t in tracked_downbeats],
            "pipeline_beats": [float(t) for t in pipeline_beats],
            "pipeline_downbeats": [float(t) for t in pipeline_downbeats],
            "beat_metrics": event_metrics(truth["beats"], tracked_beats, tolerance),
            "downbeat_metrics": event_metrics(truth["downbeats"], tracked_downbeats, tolerance),
            "pipeline_beat_metrics": event_metrics(truth["beats"], pipeline_beats, tolerance),
            "pipeline_downbeat_metrics": event_metrics(truth["downbeats"], pipeline_downbeats, tolerance)}


def riff_statistics(timeline):
    invalid = sum(n["dur_beats"] <= 0 or n["beat_pos"] < -1e-7 or
                  n["beat_pos"] + n["dur_beats"] > timeline.beats_between(s.start_sec, s.end_sec) + 1e-7
                  for s in timeline.segments for n in s.example)
    return {"riff_note_count": sum(len(s.example) for s in timeline.segments), "invalid_riff_notes": int(invalid)}


def _measure_clip(path, truth, cache_dir, tolerance, model):
    from build.real_builder import build_real_timeline
    import ingest.mir_extract as mir_extract
    from ingest.mir_extract import get_backend
    from ml.generate import bake_examples, bake_progression
    from player.timeline import Timeline

    backend = get_backend("librosa")
    actual_analyze = backend.analyze
    actual_track = mir_extract.track_beats_downbeats
    captured, tracking = [], []

    def analyze_and_capture(*args, **kwargs):
        result = actual_analyze(*args, **kwargs)
        captured.append(result)
        return result

    def track_and_capture(*args, **kwargs):
        result = actual_track(*args, **kwargs)
        tracking.append(result)
        return result

    # Select the fixed backend while executing real audio analysis and the real builder.
    with patch("build.real_builder.get_backend", return_value=backend), \
            patch("ingest.mir_extract._HAS_MADMOM", False), \
            patch("ingest.mir_extract.track_beats_downbeats", side_effect=track_and_capture), \
            patch.object(backend, "analyze", side_effect=analyze_and_capture):
        timeline = build_real_timeline(str(path))
    mir = captured[0]
    bake_examples(timeline, model)
    if timeline.segments:
        start = max(0.0, timeline.segments[0].start_sec)
        end = min(timeline.total_sec(), timeline.time_at_beat(timeline.beat_at(start) + 8))
        if end > start:
            bake_progression(timeline, model, start, end)
    session_path = cache_dir / (path.stem + "_session.json")
    timeline.save_json(str(session_path))
    restored = Timeline.load_json(str(session_path))
    roundtrip = restored.to_dict() == timeline.to_dict()
    if not roundtrip:
        raise AssertionError("real build/bake/save/load changed session contents")
    return {"audio": str(path), "audio_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "truth": truth, "estimated_bpm": mir.bpm, "bpm_absolute_error": abs(mir.bpm - BPM),
            "bpm_error_percent": abs(mir.bpm - BPM) / BPM * 100,
            "estimated_key": mir.key, "key_matches_reference": mir.key == truth["key"],
            "estimated_duration_sec": mir.duration, "content_span": list(mir.content_span),
            "beat_source": mir.beat_source, "chord_source": "librosa", "chord_vocabulary": "maj/min",
            "beat_detected": mir.beat_detected, "timeline_bar_times": list(timeline.bar_times),
            "raw_chords": [(c.start_sec, c.end_sec, c.name) for c in mir.chords],
            "raw_chord_metrics": chord_metrics(truth["chords"], [(c.start_sec, c.end_sec, c.name) for c in mir.chords]),
            "timeline_chord_metrics": chord_metrics(truth["chords"], [(s.start_sec, s.end_sec, s.chord.name) for s in timeline.segments]),
            **timing_metrics(truth, tracking[0][0], tracking[0][1], mir.beat_times, mir.downbeat_times, tolerance),
            "session": str(session_path), "session_roundtrip": roundtrip,
            **riff_statistics(timeline), "timeline_segment_count": len(timeline.segments)}


def _report_markdown(report):
    lines = ["# ScaleRiff 음악 분석 평가", "",
             "재현 명령: `.venv/Scripts/python.exe tools/evaluate_music.py --out cache/music_evaluation/report.md`", "",
             f"버전 `{BENCHMARK_VERSION}`. 동일한 C–Am–F–G × 2, 4/4, 100 BPM, 8마디(19.2초)를 "
             "22,050 Hz로 합성했다. 기준 키는 C major다. 코드 어택/릴리즈는 20 ms, 음색은 기음+약한 2차 배음이다.", "",
             "타악 조건은 같은 화성에 4분음표마다 감쇠 킥과 1.8–7 kHz 대역 잡음을 더한다. "
             "첫 박을 1.35배 강조했으며 seed=42, 화성 최대 진폭 0.65다.", "",
             "| 조건 | 추정 BPM | 절대 BPM 오차 | 추정 키 | 코드 정확도(원시) | 근음 정확도(원시) | 코드 정확도(세션) | 검출 비트 F1 | 검출 다운비트 F1 |",
             "|---|---:|---:|---|---:|---:|---:|---:|---:|"]
    for name, row in report["clips"].items():
        raw, final = row["raw_chord_metrics"], row["timeline_chord_metrics"]
        fallback = " (폴백)" if row["uniform_grid_fallback"] else ""
        lines.append(f"| {name} | {row['estimated_bpm']:.1f}{fallback} | {row['bpm_absolute_error']:.1f} "
                     f"({row['bpm_error_percent']:.1f}%) | {row['estimated_key']} | {raw['exact_accuracy']:.1%} | "
                     f"{raw['root_accuracy']:.1%} | {final['exact_accuracy']:.1%} | "
                     f"{row['beat_metrics']['f1']:.3f} | {row['downbeat_metrics']['f1']:.3f} |")
    lines += ["", "코드 정확도는 추정 마디로 정답을 다시 배치하거나 반복을 접지 않고 원본 시간 구간의 "
              "교집합 길이로 가중한다. 정답 19.2초 전체가 분모이며 검출 누락 구간도 오답이다. "
              "exact는 근음과 maj/min 품질 모두, root는 근음만 비교한다. 중복 스팬도 같은 시간을 한 번만 센다.", "",
              f"비트·다운비트는 ±{report['tolerance_sec'] * 1000:.0f} ms 이내의 시간순 1:1 매칭으로 precision/recall/F1을 계산한다. "
              "정답 비트 32개와 다운비트 8개에는 t=0을 포함하고 곡 끝 t=19.2는 제외한다. 중복 검출은 분모에 남아 F1을 높이지 못한다.", ""]
    for name, row in report["clips"].items():
        beats, downbeats = row["beat_metrics"], row["downbeat_metrics"]
        lines += [f"- {name}: beat/chord source=`{row['beat_source']}/{row['chord_source']}`, "
                  f"실제 분석 길이 {row['estimated_duration_sec']:.3f}초, 콘텐츠 구간 "
                  f"{row['content_span'][0]:.3f}–{row['content_span'][1]:.3f}초. "
                  f"비트 {beats['matches']}/{beats['reference_count']} 정답 매칭, {beats['predicted_count']}개 검출 "
                  f"(P={beats['precision']:.3f}, R={beats['recall']:.3f}); 다운비트 "
                  f"{downbeats['matches']}/{downbeats['reference_count']} 매칭, {downbeats['predicted_count']}개 검출 "
                  f"(P={downbeats['precision']:.3f}, R={downbeats['recall']:.3f}).",
                  f"- {name} 실제 빌드→리프 굽기→원자 저장→복원: {'통과' if row['session_roundtrip'] else '실패'}, "
                  f"리프 {row['riff_note_count']}음, 리프 경계/길이 위반 {row['invalid_riff_notes']}건. "
                  f"화성/타악 RMS={row['truth']['harmonic_rms']:.4f}/{row['truth']['percussion_rms']:.4f}. "
                  f"WAV SHA256=`{row['audio_sha256']}`."]
        if row["uniform_grid_fallback"]:
            lines += [f"- {name}: 원검출 비트 {len(row['beats'])}개로 트래킹에 실패해 기본값 100 BPM의 균등 격자를 "
                      f"{len(row['pipeline_beats'])}개 생성했다. 그 격자의 F1={row['pipeline_beat_metrics']['f1']:.3f}은 "
                      "기준 템포와 기본값이 우연히 같아서 나온 값이며 100 BPM 복원 성공의 근거가 아니다. 위 표는 폴백 이전 실제 검출 F1이다."]
    lines += ["", "## 해석과 한계", "",
              "- 지속 코드 조건에는 4분음표마다 공격음이 없다. 100 BPM은 합성 설계의 박자이며 파형만으로 고유하게 "
              "복원된다고 보장할 수 없다. 해당 BPM 오차와 F1은 이 명목 기준에 대한 결과다.",
              "- 타악 조건도 이 한 음색·한 진행·한 템포에서 측정한 사례다. 실제 음악 전체의 정확도, 다양한 박자·스윙·악기에서의 성능으로 일반화할 수 없다.",
              "- librosa beat_track 및 4박 onset 강도 위상으로 다운비트를 추정한다. 전용 다운비트 모델과 같지 않으며, "
              "코드 전환 경계·첫 박·키·콘텐츠 구간 모두 추정값이다.",
              "- get_backend('librosa')와 실제 build_real_timeline을 사용했다. 백엔드 선택만 고정했고 오디오 분석 결과를 대체하지 않았다. "
              "madmom, YouTube 다운로드, 실제 MIDI 기기, 사람의 청취/학습 효과는 평가하지 않았다.",
              "- 원본 데이터·기존 합성 fixtures·models는 수정하지 않았다. 이번 WAV/세션/원시 검출값은 cache/music_evaluation에 저장한다.", "",
              f"환경: Python {report['environment']['python']}, librosa {report['environment']['librosa']}, "
              f"numpy {report['environment']['numpy']}, soundfile {report['environment']['soundfile']}. "
              f"전체 수치와 정답/검출 시각: `{report['results_json']}`.", ""]
    percussion = report["clips"]["quarter_beat_percussion"]
    if percussion["content_span"][0] > report["tolerance_sec"]:
        lines.insert(lines.index("## 해석과 한계") + 2,
                     f"타악 조건의 비트 F1={percussion['beat_metrics']['f1']:.3f}에 비해 다운비트 F1="
                     f"{percussion['downbeat_metrics']['f1']:.3f}이다. 실제 화성 시작은 0초지만 다운비트 위상에 스냅하면서 "
                     f"시작 {percussion['content_span'][0]:.3f}초가 콘텐츠 밖으로 분류되었다. 그 결과 원시 코드 정확도 "
                     f"{percussion['raw_chord_metrics']['exact_accuracy']:.1%}가 세션에서 "
                     f"{percussion['timeline_chord_metrics']['exact_accuracy']:.1%}로 낮아졌다. "
                     "자동 다운비트·콘텐츠 시작 정확도는 남은 개선 항목이다.\n")
    else:
        first_bar_end = percussion["timeline_bar_times"][1]
        lines.insert(lines.index("## 해석과 한계") + 2,
                     f"타악 조건의 비트 F1={percussion['beat_metrics']['f1']:.3f}에 비해 다운비트 F1="
                     f"{percussion['downbeat_metrics']['f1']:.3f}이다. 현재 파이프라인은 화성 시작 0초를 보존하고 "
                     f"첫 검출 다운비트 앞의 0–{first_bar_end:.3f}초를 부분 마디로 남긴다. "
                     "실제 첫 마디 끝 2.400초를 찾은 결과는 아니므로 다운비트 위상과 부분 마디의 박 배치는 여전히 추정이다.\n")
    return "\n".join(lines)


def run_benchmark(out, tolerance=.07):
    from ml.model import load_model
    cache_dir = _ROOT / "cache" / "music_evaluation"
    cache_dir.mkdir(parents=True, exist_ok=True)
    report = {"benchmark_version": BENCHMARK_VERSION, "tolerance_sec": tolerance,
              "environment": {"python": sys.version.split()[0], **{p: version(p) for p in ("librosa", "numpy", "soundfile")}},
              "clips": {}, "results_json": str(cache_dir / "results.json")}
    model = load_model()
    report["model_info"] = model.identity() if model else {"source": "rule"}
    for name, percussive in (("sustained", False), ("quarter_beat_percussion", True)):
        y, truth = synth_fixture(percussive)
        path = cache_dir / f"{name}_100bpm.wav"
        sf.write(path, y, SR, subtype="PCM_24")
        print(f"Measuring {name}…", flush=True)
        report["clips"][name] = _measure_clip(path, truth, cache_dir, tolerance, model)
    Path(report["results_json"]).write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_report_markdown(report), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(_ROOT / "cache" / "music_evaluation" / "report.md"))
    parser.add_argument("--tolerance", type=float, default=.07)
    args = parser.parse_args()
    if not math.isfinite(args.tolerance) or args.tolerance < 0:
        parser.error("--tolerance must be a finite nonnegative number of seconds")
    run_benchmark(args.out, args.tolerance)
    print(f"Music evaluation → {args.out}")


if __name__ == "__main__":
    main()
