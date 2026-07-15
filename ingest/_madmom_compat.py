"""madmom 호환 셰임 — 반드시 madmom import보다 먼저 로드해야 한다.

madmom 0.16.1(2018)은 최신 numpy/Python에서 제거·이동된 API를 쓴다. 빌드된
C 확장은 numpy 2.0 헤더로 컴파일돼 ABI는 맞지만, 순수 파이썬 레벨의 옛 별칭이
import 시점에 깨진다. 여기서 그 별칭만 복원한다(앱의 numpy 2.0 스택은 그대로 둠):

  - collections.MutableSequence 등 → Python 3.10+에서 collections.abc로 이동
  - np.float / np.int / np.bool / np.complex → numpy 1.24+에서 제거

pkg_resources(madmom __init__이 사용)는 setuptools<81에서 제공되므로 별도 처리
불필요(requirements.txt에 핀 고정). 설치/빌드 실패 시 HAS_MADMOM=False로 폴백.

추가 소스 패치(madmom 재설치 시 재적용 필요):
  venv/.../madmom/features/downbeats.py 의 DBNDownBeatTrackingProcessor.process —
  `best = np.argmax(np.asarray(results)[:, 1])` 는 numpy 2.0에서 불균일 배열로
  실패하므로 `best = int(np.argmax([r[1] for r in results]))` 로 교체했다.
"""
from __future__ import annotations

import collections
import collections.abc

for _n in ("MutableSequence", "MutableMapping", "Mapping", "Sequence",
           "Callable", "Iterable", "Hashable"):
    if not hasattr(collections, _n):
        setattr(collections, _n, getattr(collections.abc, _n))

import numpy as np

for _n, _t in (("float", float), ("int", int), ("bool", bool), ("complex", complex)):
    if not hasattr(np, _n):
        setattr(np, _n, _t)

import warnings
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

HAS_MADMOM = False
Signal = None
RNNDownBeatProcessor = DBNDownBeatTrackingProcessor = None
CNNChordFeatureProcessor = CRFChordRecognitionProcessor = None

try:
    from madmom.audio.signal import Signal
    from madmom.features.downbeats import (
        RNNDownBeatProcessor, DBNDownBeatTrackingProcessor)
    from madmom.features.chords import (
        CNNChordFeatureProcessor, CRFChordRecognitionProcessor)
    HAS_MADMOM = True
except Exception:
    pass
