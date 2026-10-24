"""실데이터(토큰 jsonl)로 Markov 학습.

입력 jsonl: 한 줄 = {"grid":[..], "qfam":[per-step], "scale":[per-step]|str}
(prepare_phrases.py 가 WJazzD/MIDI에서 생성)

실행:
  venv\\Scripts\\python.exe -m ml.train.train_markov --data data/phrases.jsonl --out models/markov.json
"""
from __future__ import annotations
import argparse
import json
import hashlib
import math
from pathlib import Path

from ml.model import MarkovModel
from ml.representation import BOS, VOCAB, is_onset

TRAINING_VERSION = "tune-holdout-v1"


def load_examples(path):
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def split_by_tune(examples, seed=42, test_fraction=.2):
    """Whole tunes stay together, including multiple solos/performers of the same tune."""
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must lie between zero and one")
    if any(not ex.get("tune_id") for ex in examples):
        raise ValueError("tune_id is required; regenerate legacy phrases from their identified source")
    groups = sorted({str(ex["tune_id"]) for ex in examples}, key=lambda group:
                    (hashlib.sha256(f"{seed}|{group}".encode()).hexdigest(), group))
    if len(groups) < 2:
        raise ValueError("at least two tune_id groups are required")
    n_test = max(1, min(len(groups) - 1, int(round(len(groups) * test_fraction))))
    test_ids = set(groups[:n_test])
    return ([ex for ex in examples if str(ex["tune_id"]) not in test_ids],
            [ex for ex in examples if str(ex["tune_id"]) in test_ids])


def token_metrics(model, examples):
    """Teacher-forced conditional token log loss (nats), with 1e-3 smoothing.

    BOS is context only; predictions cover the 14 REST/HOLD/onset tokens.
    None is a uniform reference, not a probability distribution from the rule generator.
    """
    loss = onset_loss = 0.0
    count = onset_count = 0
    for ex in examples:
        order = model.order if model else 2
        prev = [BOS] * order
        scales = ex["scale"]
        for i, token in enumerate(ex["grid"]):
            scale = scales[i] if isinstance(scales, list) else scales
            dist = model.blended(ex["qfam"][i], scale, i % model.steps_per_bar,
                                 tuple(prev[-order:])) if model else {}
            mass = sum(v for k, v in dist.items() if k != BOS)
            probability = (dist.get(token, 0) + .001) / (mass + .001 * (VOCAB - 1))
            value = -math.log(probability)
            loss += value
            count += 1
            if is_onset(token):
                onset_loss += value
                onset_count += 1
            prev.append(token)
    return {"token_count": count, "token_log_loss": loss / count if count else None,
            "onset_count": onset_count,
            "onset_log_loss": onset_loss / onset_count if onset_count else None}


def train_model(examples, order=2, seed=42, test_fraction=.2, dataset_sha256=None):
    train, test = split_by_tune(examples, seed=seed, test_fraction=test_fraction)
    train_ids = sorted({str(e["tune_id"]) for e in train})
    test_ids = sorted({str(e["tune_id"]) for e in test})
    digest = dataset_sha256 or hashlib.sha256(json.dumps(
        examples, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    model = MarkovModel(order=order).fit(train)
    model.meta.update({"source": "train_markov_tune_split", "training_version": TRAINING_VERSION,
                       "dataset_sha256": digest,
                       "preparation_versions": sorted({e.get("preparation_version", "unspecified") for e in examples}),
                       "split": {"unit": "tune_id", "seed": seed, "test_fraction": test_fraction,
                                 "train_group_count": len(train_ids), "test_group_count": len(test_ids),
                                 "train_phrase_count": len(train), "test_phrase_count": len(test),
                                 "overlap_count": len(set(train_ids) & set(test_ids)),
                                 "train_group_ids": train_ids, "test_group_ids": test_ids},
                       "heldout_metrics": token_metrics(model, test)})
    return model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="토큰 jsonl 경로")
    ap.add_argument("--out", default="models/markov.json")
    ap.add_argument("--order", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--test-fraction", type=float, default=.2)
    args = ap.parse_args()

    examples = load_examples(args.data)
    model = train_model(examples, order=args.order, seed=args.seed, test_fraction=args.test_fraction,
                        dataset_sha256=hashlib.sha256(Path(args.data).read_bytes()).hexdigest())
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    model.save_json(args.out)
    print(f"[train_markov] {model.meta['phrases']}개 학습 / {model.meta['split']['test_phrase_count']}개 검증 → {args.out} "
          f"(컨텍스트 {len(model.table)}개)")


if __name__ == "__main__":
    main()
