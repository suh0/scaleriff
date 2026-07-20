"""리듬 인지 조건부 Markov 모델 (베이스라인, torch 불필요).

다음 토큰 확률을 (코드 품질군, 스케일 종류, 마디 내 박위치, 직전 토큰들)로 조건화.
데이터가 희소하므로 **백오프**: 구체적 컨텍스트가 없으면 점점 일반화한 컨텍스트로.
JSON 직렬화(가중치=카운트 테이블). 추론은 ml/generate.py.
"""
from __future__ import annotations
import json
import os

from ml.representation import BOS, STEPS_PER_BAR

_MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")


class MarkovModel:
    def __init__(self, order: int = 2, steps_per_bar: int = STEPS_PER_BAR):
        self.order = order
        self.steps_per_bar = steps_per_bar
        self.table: dict[str, dict[str, int]] = {}
        self.meta = {"source": "empty", "order": order,
                     "steps_per_bar": steps_per_bar, "phrases": 0}

    # ── 컨텍스트 키 ──────────────────────────────────────────────
    @staticmethod
    def _key(qfam, scale, metric, prev) -> str:
        return f"{qfam}|{scale}|{metric}|{','.join(map(str, prev))}"

    def _backoff_keys(self, qfam, scale, metric, prev) -> list[str]:
        prev = tuple(prev)
        last1 = prev[-1:] if prev else ()
        return [
            self._key(qfam, scale, metric, prev),
            self._key(qfam, scale, metric, last1),
            self._key(qfam, scale, metric, ()),
            self._key("*", scale, metric, ()),
            self._key("*", "*", metric, ()),
            self._key("*", "*", "*", ()),
        ]

    # ── 학습 ─────────────────────────────────────────────────────
    def fit(self, examples):
        """examples: [{grid:[tok], qfam:[per-step], scale:str|[per-step]}]."""
        o = self.order
        for ex in examples:
            grid, qf, sc = ex["grid"], ex["qfam"], ex["scale"]
            prev = [BOS] * o
            for i, tok in enumerate(grid):
                metric = i % self.steps_per_bar
                pv = tuple(prev[-o:])
                sc_i = sc[i] if isinstance(sc, list) else sc
                for k in self._backoff_keys(qf[i], sc_i, metric, pv):
                    d = self.table.setdefault(k, {})
                    d[str(tok)] = d.get(str(tok), 0) + 1
                prev.append(tok)
            self.meta["phrases"] += 1
        return self

    # ── 추론 ─────────────────────────────────────────────────────
    def blended(self, qfam, scale, metric, prev, decay=0.5) -> dict[int, float]:
        """백오프 '첫 히트만' 절벽 대신 보간 — 단계별 정규화 분포를 감쇠 혼합.

        구체적 컨텍스트가 희소해도 일반 컨텍스트로 부드럽게 섞여 내려간다.
        """
        out: dict[int, float] = {}
        w = 1.0
        for k in self._backoff_keys(qfam, scale, metric, prev):
            d = self.table.get(k)
            if d:
                tot = sum(d.values())
                for t, c in d.items():
                    out[int(t)] = out.get(int(t), 0.0) + w * c / tot
                w *= decay
        return out

    # ── 직렬화 ───────────────────────────────────────────────────
    def to_dict(self):
        return {"meta": self.meta, "table": self.table}

    @staticmethod
    def from_dict(d):
        m = MarkovModel(order=d["meta"].get("order", 2),
                        steps_per_bar=d["meta"].get("steps_per_bar", STEPS_PER_BAR))
        m.meta = d["meta"]
        m.table = d["table"]
        return m

    def save_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)

    @staticmethod
    def load_json(path: str) -> "MarkovModel":
        with open(path, "r", encoding="utf-8") as f:
            return MarkovModel.from_dict(json.load(f))


def is_trained(model: MarkovModel) -> bool:
    return bool(model and model.table and model.meta.get("phrases", 0) > 0)


def load_model() -> "MarkovModel | None":
    """학습본(markov.json) 우선, 없으면 부트스트랩(default_markov.json), 둘 다 없으면 None."""
    for name in ("markov.json", "default_markov.json"):
        p = os.path.join(_MODELS_DIR, name)
        if os.path.exists(p):
            try:
                return MarkovModel.load_json(p)
            except Exception:
                pass
    return None
