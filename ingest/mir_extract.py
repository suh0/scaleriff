"""MIR 추출 — 코드 진행 + 키 + BPM (브리프 §5.1).

한 파이프라인에서 코드/키/BPM·비트·다운비트·무음경계를 뽑는다.
  - 코드: madmom 학습 모델(CNN 특징 + CRF 디코딩). 미설치 시 librosa 크로마
    + maj/min 템플릿 argmax 폴백(무타악기 합성음 등 madmom이 약한 입력용).
  - 비트·다운비트: madmom RNN/DBN(있으면) → librosa beat_track 폴백.
  - 키: Krumhansl–Schmuckler 프로파일(실패 시 코드 다이아토닉 적합도 폴백).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from analyze.theory import CHORD_SPECS, pc_name, scale_pcs

# madmom: 비트·다운비트 + 코드 인식(학습 모델). 설치 시 자동 사용, 없으면 librosa 폴백.
# _madmom_compat가 numpy/collections 옛 별칭을 복원한 뒤 madmom을 import한다(반드시 먼저).
from ingest._madmom_compat import (
    HAS_MADMOM as _HAS_MADMOM, Signal as _Signal,
    RNNDownBeatProcessor, DBNDownBeatTrackingProcessor,
    CNNChordFeatureProcessor, CRFChordRecognitionProcessor)

_MADMOM_SR = 44100   # madmom 모델 학습 SR(검증된 경로). 입력은 이 SR로 리샘플.

DOWNBEAT_METERS = [3, 4]          # 다운비트 트래킹 박자 후보
BPM_MIN, BPM_MAX = 70.0, 185.0    # BPM 옥타브 sanity 목표 범위


@dataclass
class ChordSpan:
    start_sec: float
    end_sec: float
    name: str          # 예 "Dm7"


@dataclass
class MirResult:
    bpm: float
    beat_times: list[float]
    key: str | None
    key_root: int | None
    key_mode: str | None          # "major" | "minor"
    chords: list[ChordSpan] = field(default_factory=list)
    duration: float = 0.0
    downbeat_times: list[float] = field(default_factory=list)  # 마디선 앵커(다운비트)
    beats_per_bar: int = 4
    beat_source: str = "librosa"  # "madmom" | "librosa"
    content_span: tuple[float, float] = (0.0, 0.0)  # 무음 인트로/아웃트로 제외 구간


# ── 비트/다운비트 트래킹 (BPM 옥타브 sanity 포함) ──────────────────
def _octave_fix_bpm(bpm: float) -> float:
    if bpm <= 0:
        return 100.0
    while bpm < BPM_MIN:
        bpm *= 2
    while bpm > BPM_MAX:
        bpm /= 2
    return bpm


def _bpm_from_beats(beat_times) -> float:
    if len(beat_times) < 2:
        return 100.0
    med = float(np.median(np.diff(beat_times)))
    if med <= 0:
        return 100.0
    return round(_octave_fix_bpm(60.0 / med), 1)


def track_beats_downbeats(wav_path: str, y, sr):
    """(beat_times, downbeat_times, beats_per_bar, bpm, source).

    madmom DBNDownBeatTrackingProcessor가 있으면 사용, 없으면 librosa로
    비트를 잡고 다운비트 위상을 추정한다. 둘 다 첫 다운비트를 마디 앵커로 쓴다.
    """
    if _HAS_MADMOM:
        try:
            return _madmom_track(y, sr)
        except Exception:
            pass  # 실패 시 librosa 폴백
    return _librosa_track(y, sr)


def _madmom_signal(y, sr):
    """librosa 샘플(float)을 madmom Signal(int16, _MADMOM_SR)로 변환.

    madmom의 오디오 로더는 시스템 ffmpeg를 찾는데 이 앱은 번들 ffmpeg(다른 이름)를
    쓰므로 파일 경로 대신 메모리 샘플을 직접 Signal로 넘긴다(로딩 의존성 우회).
    """
    import librosa
    if int(sr) != _MADMOM_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=_MADMOM_SR)
    return _Signal((np.clip(y, -1.0, 1.0) * 32767.0).astype(np.int16),
                   sample_rate=_MADMOM_SR)


def _madmom_track(y, sr):
    act = RNNDownBeatProcessor()(_madmom_signal(y, sr))
    proc = DBNDownBeatTrackingProcessor(beats_per_bar=DOWNBEAT_METERS, fps=100)
    out = np.atleast_2d(proc(act))          # Nx2: [time, beat_in_bar(1..N)]
    if out.size == 0:
        raise RuntimeError("madmom: no beats")
    beat_times = out[:, 0].tolist()
    beats_per_bar = int(round(out[:, 1].max())) or 4
    downbeat_times = out[out[:, 1] == 1, 0].tolist()
    return beat_times, downbeat_times, beats_per_bar, _bpm_from_beats(beat_times), "madmom"


def _librosa_track(y, sr):
    import librosa
    _, beat_frames = librosa.beat.beat_track(y=y, sr=sr, trim=False)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    beats_per_bar = 4
    downbeat_times = beat_times[:1]
    if len(beat_frames) >= beats_per_bar:
        # 다운비트 위상 추정: 비트별 onset 강도를 4박 그룹으로 묶어 평균 최대 위상 = 다운비트
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        per_beat = librosa.util.sync(
            onset_env[np.newaxis, :], beat_frames, aggregate=np.mean)[0]
        strengths = [float(np.mean(per_beat[p::beats_per_bar]))
                     if len(per_beat[p::beats_per_bar]) else 0.0
                     for p in range(beats_per_bar)]
        phase = int(np.argmax(strengths))
        downbeat_times = beat_times[phase::beats_per_bar]
    return beat_times, downbeat_times, beats_per_bar, _bpm_from_beats(beat_times), "librosa"


def _snap_to_grid(t: float, grid) -> float:
    if not grid:
        return t
    return min(grid, key=lambda g: abs(g - t))


HARM_RMS_THR_RATIO = 0.10   # 하모닉 RMS 피크 대비 화성 온셋 임계(밴드 진입에 맞춰 낮춤)
HARM_SUSTAIN_SEC = 0.25     # 임계 지속 시간(드럼 트랜지언트 무시, 밴드 진입에 맞춰 낮춤)
STABLE_WINDOW_BARS = 2      # 안정코드 보강은 온셋 근방(이내)만 — 멀면 무시(온셋 우선)
TAIL_RMS_THR_RATIO = 0.06   # 아웃트로 무음 임계(전체 RMS 피크 대비)


def detect_content_span(y, sr, duration: float, downbeat_times=None,
                        chords=None, bar_sec: float = 2.0, log=print):
    """화성 콘텐츠 구간(인트로 드럼·무음 제외). 시작은 '첫 코드 라벨'이 아니라
    실제 하모닉 에너지로 잡는다(§5.2.2 강화).

    1) HPSS 하모닉 성분 RMS → 드럼만 있는 인트로(낮은 하모닉 에너지)를 지나
       임계를 '지속적으로' 넘는 첫 지점 = 화성 온셋
    2) 가장 가까운 다운비트에 스냅
    3) 보강: 온셋 이후 '코드가 ≥1마디 안정 유지되는 첫 지점'과 결합
    4) 끝(아웃트로)은 전체 RMS 꼬리 임계로 산출
    디버그: 감지 시작 시각 + 인트로(버려지는) 코드 라벨 로그 출력.
    """
    import librosa
    downbeat_times = downbeat_times or []
    chords = chords or []

    # ── 1) 하모닉 성분 RMS로 화성 온셋 ───────────────────────────
    onset_sec = 0.0
    try:
        y_harm = librosa.effects.harmonic(y, margin=2.0)
        hrms = librosa.feature.rms(y=y_harm)[0]
        if hrms.size:
            htimes = librosa.times_like(hrms, sr=sr)
            thr = max(float(np.max(hrms)) * HARM_RMS_THR_RATIO, 1e-5)
            dt = (htimes[1] - htimes[0]) if len(htimes) > 1 else 0.05
            win = max(1, int(HARM_SUSTAIN_SEC / dt))
            above = hrms > thr
            onset_idx = next((i for i in range(len(above) - win + 1)
                              if above[i:i + win].all()), None)
            onset_sec = float(htimes[onset_idx]) if onset_idx is not None else 0.0
    except Exception as e:
        log(f"[harmonic-onset] HPSS 실패, RMS 폴백: {e}")

    # 2) 가장 가까운 다운비트에 스냅 → 이것이 콜 시작(밴드 진입). 루프와 분리.
    harm_db = _snap_to_grid(onset_sec, downbeat_times) if downbeat_times else onset_sec

    # 3) 시작점 = 하모닉 온셋(다운비트 스냅) 우선. ≥1마디 안정코드는 '근방 보강'만:
    #    온셋 ±윈도우 안에 있으면 미세 정렬에 쓰고, 멀면 무시(온셋이 밀리지 않게).
    start = harm_db
    win = STABLE_WINDOW_BARS * bar_sec
    stable_start = None
    for c in chords:
        if ((c.end_sec - c.start_sec) >= 0.9 * bar_sec
                and harm_db - 0.5 * bar_sec <= c.start_sec <= harm_db + win):
            stable_start = c.start_sec
            break
    if stable_start is not None and stable_start > harm_db:
        snapped = _snap_to_grid(stable_start, downbeat_times) if downbeat_times else stable_start
        if snapped <= harm_db + win:
            start = snapped

    # ── 4) 끝(아웃트로 무음) — 전체 RMS 꼬리 ────────────────────
    rms = librosa.feature.rms(y=y)[0]
    end = duration
    if rms.size:
        rtimes = librosa.times_like(rms, sr=sr)
        tail_thr = max(float(np.max(rms)) * TAIL_RMS_THR_RATIO, 1e-5)
        above = np.where(rms > tail_thr)[0]
        if above.size:
            end = float(rtimes[min(above[-1] + 1, len(rtimes) - 1)])

    start = max(0.0, start)
    end = min(duration, end)
    if start >= end:
        start, end = harm_db, duration

    # ── 디버그 로그 ───────────────────────────────────────────────
    intro_chords = [(round(c.start_sec, 2), c.name) for c in chords
                    if c.start_sec < start - 1e-3]
    log(f"[harmonic-onset] 하모닉 온셋={onset_sec:.2f}s → 다운비트 스냅={harm_db:.2f}s "
        f"· ≥1마디 안정코드 시작={None if stable_start is None else round(stable_start, 2)} "
        f"⇒ content 시작={start:.2f}s, 끝={end:.2f}s")
    log(f"[harmonic-onset] 인트로(콜 격자에서 제외된) 코드 라벨: {intro_chords}")
    return (start, end)


# ── 코드 추정 폴백(madmom 미설치 시): maj/min 트라이어드 템플릿 argmax ──
# madmom CRF도 maj/min만 출력하므로 어휘를 맞춰 앱 전체 코드 표기를 일관화한다.
def _build_triad_templates() -> tuple[np.ndarray, list[tuple[int, str]]]:
    """12 root × {maj, min} 트라이어드 이진 템플릿(24×12)과 라벨. 내적이 곧 점수."""
    rows, labels = [], []
    for root in range(12):
        for q in ("maj", "min"):
            ivs, _ = CHORD_SPECS[q]
            tones = {(root + i) % 12 for i in ivs}
            rows.append([1.0 if p in tones else 0.0 for p in range(12)])
            labels.append((root, q))
    return np.array(rows), labels


_TRIAD_A, _TRIAD_LABELS = _build_triad_templates()


def _librosa_chords(y, sr, beat_times, beats_per_bar, duration) -> list[ChordSpan]:
    """madmom 미설치/폴백 코드 인식 — beat-sync CENS 크로마 + maj/min 템플릿 argmax.

    비트마다 크로마를 트라이어드 템플릿과 내적해 최고 점수 코드를 고르고(무에너지
    비트는 직전 라벨 유지), 연속 동일 라벨을 ChordSpan으로 병합한다. 합성음·무타악기
    트랙처럼 madmom 모델이 약한 입력의 단순·강건한 대안.
    """
    import librosa
    cens = librosa.feature.chroma_cens(y=y, sr=sr)
    bf = np.clip(librosa.time_to_frames(beat_times, sr=sr), 0, cens.shape[1] - 1)
    sync = (librosa.util.sync(cens, bf, aggregate=np.median)
            if len(bf) >= 2 else cens.mean(axis=1, keepdims=True))
    B = sync.shape[1]
    unit = sync / (np.linalg.norm(sync, axis=0) + 1e-9)

    labels: list[int] = []
    for i in range(B):
        if np.linalg.norm(sync[:, i]) > 1e-6:
            labels.append(int(np.argmax(_TRIAD_A @ unit[:, i])))
        else:
            labels.append(labels[-1] if labels else 0)

    seg = list(beat_times) + [duration]
    spans: list[ChordSpan] = []
    i = 0
    while i < B:
        j = i
        while j + 1 < B and labels[j + 1] == labels[i]:
            j += 1
        root, q = _TRIAD_LABELS[labels[i]]
        name = pc_name(root) + ("m" if q == "min" else "")
        end = seg[j + 1] if j + 1 < len(seg) else duration
        spans.append(ChordSpan(float(seg[i]), float(end), name))
        i = j + 1
    return spans or [ChordSpan(0.0, duration, "C")]


# Krumhansl–Schmuckler 키 프로파일
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


class MirBackend:
    """코드/키/BPM·비트·다운비트·무음경계를 한 번에 추출(§5.1).

    코드 인식은 madmom 학습 모델(설치 시) → 없으면 librosa 크로마 폴백.
    use_madmom=False면 madmom이 있어도 폴백을 강제한다(무타악기 합성음 테스트용).
    """

    def __init__(self, use_madmom: bool | None = None):
        # None → 자동(madmom 있으면 사용). 명시 False면 폴백 강제.
        self.use_madmom = _HAS_MADMOM if use_madmom is None else (use_madmom and _HAS_MADMOM)

    def analyze(self, wav_path: str, progress_cb=None) -> MirResult:
        import librosa

        def cb(p, m):
            if progress_cb:
                progress_cb(p, m)

        cb(42, "오디오 로딩…")
        y, sr = librosa.load(wav_path, sr=None, mono=True)
        duration = len(y) / sr

        cb(48, "비트·다운비트 트래킹…")
        beat_times, downbeat_times, beats_per_bar, bpm, source = \
            track_beats_downbeats(wav_path, y, sr)
        if len(beat_times) < 2:
            step = 60.0 / (bpm if bpm > 0 else 100.0)
            beat_times = list(np.arange(0, duration, step))
            downbeat_times = beat_times[::beats_per_bar]
        cb(52, f"비트 소스: {source} · {bpm:.0f}BPM · {beats_per_bar}/4")

        cb(55, "화성(크로마) 분석…")
        y_harm = librosa.effects.harmonic(y, margin=2.0)
        chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr)   # 키 추정용

        if self.use_madmom:
            cb(62, "코드 인식(madmom 학습 모델)… 잠시 걸려요")
            chords = _madmom_chords(y, sr, beat_times, beats_per_bar, duration)
        else:
            cb(62, "코드 추정(librosa 폴백)…")
            chords = _librosa_chords(y, sr, beat_times, beats_per_bar, duration)

        cb(66, "화성 온셋·무음 경계…")
        bar_sec = beats_per_bar * (60.0 / bpm if bpm > 0 else 0.5)

        def _dbg(msg):
            print(msg)        # 디버그 콘솔
            cb(66, msg)       # 분석 중 화면 로그
        content_span = detect_content_span(y, sr, duration, downbeat_times,
                                            chords, bar_sec, log=_dbg)

        cb(68, "키 추정…")
        key_root, key_mode = self._estimate_key(chroma, chords)
        key = f"{pc_name(key_root)} {key_mode}" if key_root is not None else None

        return MirResult(bpm=bpm, beat_times=beat_times, key=key,
                         key_root=key_root, key_mode=key_mode,
                         chords=chords, duration=duration,
                         downbeat_times=downbeat_times,
                         beats_per_bar=beats_per_bar, beat_source=source,
                         content_span=content_span)

    # ── 키 추정 ──────────────────────────────────────────────────
    def _estimate_key(self, chroma, chords):
        profile = chroma.mean(axis=1)
        if np.linalg.norm(profile) < 1e-6:
            return self._key_from_chords(chords)
        profile = profile / np.linalg.norm(profile)
        best_score, best = -1e9, (0, "major")
        for root in range(12):
            for mode, ks in (("major", _KS_MAJOR), ("minor", _KS_MINOR)):
                prof = np.roll(ks, root)
                prof = prof / np.linalg.norm(prof)
                score = float(np.dot(prof, profile))
                if score > best_score:
                    best_score, best = score, (root, mode)
        return best

    @staticmethod
    def _key_from_chords(chords):
        """폴백(§5.1): 추출된 코드들의 다이아토닉 적합도 최대인 키 선택."""
        from analyze.theory import parse_chord
        roots = [parse_chord(c.name).root for c in chords]
        best_fit, best = -1, (0, "major")
        for root in range(12):
            for mode in ("major", "minor"):
                scale = set(scale_pcs(root, mode))
                fit = sum(1 for r in roots if r in scale)
                if fit > best_fit:
                    best_fit, best = fit, (root, mode)
        return best


# ── madmom 코드 인식(학습 모델) ───────────────────────────────────
def _madmom_label_to_name(lab: str) -> str | None:
    """madmom 코드 라벨('C:maj','A#:min','N')을 앱 코드명('C','A#m')으로.

    madmom CRF는 maj/min 트라이어드만 출력(7th 없음). 근음 표기는 샵으로
    pc_name과 동일하므로 parse_chord가 그대로 해석한다. 'N'(무코드)은 None.
    """
    if not lab or lab.startswith("N"):
        return None
    root, _, qual = lab.partition(":")
    return f"{root}m" if qual.strip().lower().startswith("min") else root


def _madmom_chords(y, sr, beat_times, beats_per_bar, duration) -> list[ChordSpan]:
    """madmom CNN 특징 + CRF 디코딩으로 코드 진행 추정 후 비트 격자에 정렬.

    프레임 단위 예측을 비트 중앙값으로 샘플 → 무코드('N')는 이웃 코드로 채워
    연속성을 유지 → 같은 라벨끼리 병합해 ChordSpan으로 만든다.
    """
    sig = _madmom_signal(y, sr)
    raw = CRFChordRecognitionProcessor()(CNNChordFeatureProcessor()(sig))
    spans_raw = [(float(s), float(e), str(lab)) for s, e, lab in raw]

    def label_at(t: float) -> str:
        for s, e, lab in spans_raw:
            if s <= t < e:
                return lab
        return "N"

    B = len(beat_times)
    if B < 2:   # 비트 격자 없음 → 원시 스팬 직접 사용
        spans = [ChordSpan(s, e, _madmom_label_to_name(l))
                 for s, e, l in spans_raw if _madmom_label_to_name(l)]
        return spans or [ChordSpan(0.0, duration, "C")]

    seg_bounds = list(beat_times) + [duration]
    beat_lab = [label_at((seg_bounds[i] + seg_bounds[i + 1]) / 2) for i in range(B)]

    # 'N' 채우기(앞으로 채운 뒤 선행 N은 뒤로) — 마디 연속성 유지
    real = [i for i, l in enumerate(beat_lab) if l != "N"]
    if not real:
        beat_lab = ["C:maj"] * B
    else:
        last = beat_lab[real[0]]
        for i in range(B):
            if beat_lab[i] == "N":
                beat_lab[i] = last
            else:
                last = beat_lab[i]
        for i in range(real[0]):
            beat_lab[i] = beat_lab[real[0]]

    spans: list[ChordSpan] = []
    i = 0
    while i < B:
        j = i
        while j + 1 < B and beat_lab[j + 1] == beat_lab[i]:
            j += 1
        name = _madmom_label_to_name(beat_lab[i]) or "C"
        spans.append(ChordSpan(float(seg_bounds[i]), float(seg_bounds[j + 1]), name))
        i = j + 1
    return spans or [ChordSpan(0.0, duration, "C")]


def get_backend(name: str = "auto") -> MirBackend:
    """MIR 백엔드 팩토리.

    'auto'(기본): madmom 설치 시 학습 모델로 코드 인식, 없으면 librosa 폴백.
    'librosa': madmom이 있어도 librosa 폴백 강제(무타악기 합성음 테스트용).
    'madmom': madmom 강제(미설치 시 에러).
    """
    if name == "auto":
        return MirBackend()
    if name == "madmom":
        if not _HAS_MADMOM:
            raise RuntimeError("madmom 미설치 — pip install madmom (setuptools<81)")
        return MirBackend(use_madmom=True)
    if name == "librosa":
        return MirBackend(use_madmom=False)
    raise ValueError(f"알 수 없는 MIR 백엔드: {name}")
