"""실데이터(토큰 jsonl)로 Markov 학습.

입력 jsonl: 한 줄 = {"grid":[..], "qfam":[per-step], "scale":[per-step]|str}
(prepare_phrases.py 가 WJazzD/MIDI에서 생성)

실행:
  venv\\Scripts\\python.exe -m ml.train.train_markov --data data/phrases.jsonl --out models/markov.json
"""
from __future__ import annotations
import argparse
import json

from ml.model import MarkovModel


def load_examples(path):
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="토큰 jsonl 경로")
    ap.add_argument("--out", default="models/markov.json")
    ap.add_argument("--order", type=int, default=2)
    args = ap.parse_args()

    examples = load_examples(args.data)
    model = MarkovModel(order=args.order)
    model.fit(examples)
    model.meta["source"] = "train_markov"
    model.save_json(args.out)
    print(f"[train_markov] {len(examples)}개 프레이즈 학습 → {args.out} "
          f"(컨텍스트 {len(model.table)}개)")


if __name__ == "__main__":
    main()
