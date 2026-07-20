"""연습 기록 영속화(§7.5 학습루프 최소 연결) — 패스 요약 append + 종류별 최근 평균.

경로: data/practice_log.jsonl. 환경변수 SCALERIFF_PRACTICE_LOG로 재지정(테스트용).
쓰기: ScoreEngine._finalize(패스 완료 1건 = 1줄). 읽기: generate.rebake_kind.
"""
from __future__ import annotations
import json
import os
import time

_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "practice_log.jsonl")


def _path() -> str:
    return os.environ.get("SCALERIFF_PRACTICE_LOG") or _DEFAULT


def append(record: dict) -> None:
    """패스 요약 1건 append(ts 자동 부여)."""
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), **record}, ensure_ascii=False) + "\n")


def recent_right_pct(kind: str, n: int = 20) -> float | None:
    """해당 스케일 종류 최근 n개 패스의 right_pct 평균. 기록 없으면 None."""
    try:
        with open(_path(), encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    vals = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("kind") == kind and r.get("right_pct") is not None:
            vals.append(r["right_pct"])
    vals = vals[-n:]
    return sum(vals) / len(vals) if vals else None
