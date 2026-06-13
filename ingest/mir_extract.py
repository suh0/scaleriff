"""MIR 추출 — 코드 진행 + 키 + BPM (브리프 §5.1).

한 파이프라인에서 코드/키/BPM을 뽑는다. 외부 API로 교체 가능하도록
MirBackend 인터페이스로 분리(§2). 기본 구현은 librosa 백엔드.

librosa는 코드 인식을 기본 제공하지 않으므로:
  - beat-sync chroma(chroma_cqt) → 코드 템플릿 매칭으로 코드 추정
  - beat_track → BPM/비트
  - Krumhansl–Schmuckler 키 프로파일 → 키 (실패 시 코드 다이아토닉 적합도 폴백)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from analyze.theory import (
    CHORD_SPECS, SCALE_INTERVALS, pc_name, scale_pcs,
)

# 다운비트 트래킹: madmom 우선(요청), 미설치/빌드툴 부재 시 librosa 폴백.
# madmom은 C 확장 컴파일에 MSVC Build Tools가 필요 → 설치 시 코드 변경 없이 자동 사용.
try:
    from madmom.features.downbeats import (
        RNNDownBeatProcessor, DBNDownBeatTrackingProcessor)
    _HAS_MADMOM = True
except Exception:
    _HAS_MADMOM = False

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
            return _madmom_track(wav_path)
        except Exception:
            pass  # 실패 시 librosa 폴백
    return _librosa_track(y, sr)


def _madmom_track(wav_path: str):
    act = RNNDownBeatProcessor()(wav_path)
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


# ── 코드 추정: 벌점 점수 + 루프 평균 + 비터비 평활 ─────────────────
# 어휘를 5종으로 한정(dim/m7b5는 다이아토닉 코드와 음 겹쳐 오검출 유발).
_CHORD_VOCAB = ["maj7", "m7", "dom7", "maj", "min"]
_PEN_ALPHA = 0.5          # 코드 밖 음 벌점 — 무관한 음(예: G7 마디의 강한 패싱톤) 억제
_CHORD_P_STAY = 0.80      # 비트→다음비트 같은 코드 유지 확률(루프 미검출 시 폴백 평활)
_CHORD_EMIS_GAIN = 16.0   # 방출 점수 게인 — 전이 페널티와 균형
_LOOP_SIM_THR = 0.90      # 반복(루프) 판정 자기유사도 임계
_LOOP_BEAT_CANDS = [8, 12, 16, 24, 32]  # 후보 루프 길이(비트) — 가장 짧은 것 채택


def _build_pen_templates() -> tuple[np.ndarray, list[tuple[int, str]]]:
    """코드 밖 음에 벌점을 주는 매칭 행렬(N×12)과 라벨. 내적이 곧 점수."""
    rows, labels = [], []
    for root in range(12):
        for q in _CHORD_VOCAB:
            ivs, _ = CHORD_SPECS[q]
            tones = {(root + i) % 12 for i in ivs}
            ni = len(tones); no = 12 - ni
            rows.append([(1.0 / ni) if p in tones else (-_PEN_ALPHA / no)
                         for p in range(12)])
            labels.append((root, q))
    return np.array(rows), labels


_PEN_A, _PEN_LABELS = _build_pen_templates()


def _detect_loop_beats(unit: np.ndarray, bpb: int) -> int:
    """비트열 크로마(정규화)에서 반복 주기(비트)를 자기유사도로 검출. 없으면 0.

    백킹 트랙은 같은 진행을 수십 번 반복하므로 이 주기로 평균내면 워킹 베이스·
    패싱톤이 상쇄돼 화성이 또렷해진다.
    """
    B = unit.shape[1]
    for L in _LOOP_BEAT_CANDS:
        if L >= B or (bpb and L % bpb):
            continue
        sims = [float(unit[:, i] @ unit[:, i + L]) for i in range(B - L)]
        if sims and float(np.mean(sims)) > _LOOP_SIM_THR:
            return L
    return 0


def _viterbi_chords(emis: np.ndarray, p_stay: float,
                    gain: float = _CHORD_EMIS_GAIN) -> np.ndarray:
    """비트별 코드 점수(emis: B×N)를 자기전이 선호로 평활 → 코드 인덱스 경로.

    코드는 보통 여러 비트 지속하므로 같은 코드 유지에 보너스를 준다. gain은
    방출 점수 차이를 전이 페널티와 비교 가능한 스케일로 키운다(균형 파라미터).
    """
    B, N = emis.shape
    log_e = gain * (emis - emis.max(axis=1, keepdims=True))   # 0 이하 로그 점수
    l_stay = np.log(p_stay)
    l_change = np.log((1.0 - p_stay) / max(1, N - 1))
    dp = log_e[0].copy()
    bp = np.zeros((B, N), dtype=np.int32)
    for t in range(1, B):
        best_prev = int(np.argmax(dp))
        best_val = dp[best_prev]
        # 전 시점 최고값 기준 '변경' 후보(자기 자신이면 차선)
        second = dp.copy(); second[best_prev] = -np.inf
        second_idx = int(np.argmax(second)); second_val = second[second_idx]
        new_dp = np.empty(N)
        for j in range(N):
            stay = dp[j] + l_stay
            if best_prev != j:
                change_val, change_idx = best_val + l_change, best_prev
            else:
                change_val, change_idx = second_val + l_change, second_idx
            if stay >= change_val:
                new_dp[j] = stay + log_e[t, j]; bp[t, j] = j
            else:
                new_dp[j] = change_val + log_e[t, j]; bp[t, j] = change_idx
        dp = new_dp
    path = np.zeros(B, dtype=np.int32)
    path[-1] = int(np.argmax(dp))
    for t in range(B - 1, 0, -1):
        path[t - 1] = bp[t, path[t]]
    return path


# Krumhansl–Schmuckler 키 프로파일
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _chord_label(root: int, quality: str) -> str:
    suffix = {
        "maj": "", "min": "m", "dom7": "7", "maj7": "maj7",
        "m7": "m7", "dim": "dim", "m7b5": "m7b5",
    }[quality]
    return f"{pc_name(root)}{suffix}"


class MirBackend(ABC):
    @abstractmethod
    def analyze(self, wav_path: str) -> MirResult: ...


class LibrosaBackend(MirBackend):
    def __init__(self, min_chord_beats: int = 1):
        self.min_chord_beats = min_chord_beats

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
        # 코드 추정은 CENS(에너지 정규화·평활) — 화성 인식에 더 강건
        cens = librosa.feature.chroma_cens(y=y, sr=sr)

        cb(62, "코드 추정…")
        chords = self._chords_from_chroma(cens, sr, beat_times, beats_per_bar, duration)

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

    # ── 코드 추정 ────────────────────────────────────────────────
    def _chords_from_chroma(self, cens, sr, beat_times,
                            beats_per_bar, duration) -> list[ChordSpan]:
        """루프 평균 + 코드-밖-음 벌점 점수로 안정적인 코드 진행 추정.

        반복(루프)이 검출되면 모든 사이클의 크로마를 같은 위상끼리 평균내
        워킹 베이스·패싱톤을 상쇄하고, 마디 위상을 자동 정렬해 마디당 코드를
        고른다(전 구간에 같은 진행 반복). 루프가 없으면 비트별 비터비로 폴백.
        """
        import librosa
        bf = np.clip(librosa.time_to_frames(beat_times, sr=sr), 0, cens.shape[1] - 1)
        if len(bf) >= 2:
            sync = librosa.util.sync(cens, bf, aggregate=np.median)
        else:
            sync = cens.mean(axis=1, keepdims=True)
        B = sync.shape[1]
        bpb = max(1, int(beats_per_bar))
        unit = sync / (np.linalg.norm(sync, axis=0) + 1e-9)

        L = _detect_loop_beats(unit, bpb)
        if L and 2 * bpb <= L < B:
            # 1) 사이클 평균(워킹 베이스·패싱톤 상쇄)
            phase = np.zeros((12, L))
            for i in range(B):
                phase[:, i % L] += sync[:, i]
            # 2) 마디 위상 자동 정렬(코드 점수 신뢰도 최대) → 마디별 코드 인덱스
            nbars = L // bpb
            best = None
            for s in range(L):
                idxs, conf = [], 0.0
                for b in range(nbars):
                    v = sum(phase[:, (s + b * bpb + k) % L] for k in range(bpb))
                    nv = np.linalg.norm(v)
                    sc = _PEN_A @ (v / nv) if nv > 1e-6 else np.zeros(len(_PEN_LABELS))
                    idxs.append(int(np.argmax(sc))); conf += float(np.max(sc))
                if best is None or conf > best[0]:
                    best = (conf, s, idxs)
            _, s, bar_idx = best
            beat_label = [bar_idx[(((i % L) - s) % L) // bpb] for i in range(B)]
        else:
            # 루프 없음 → 비트별 벌점 점수 + 비터비 평활
            emis = np.zeros((B, len(_PEN_LABELS)))
            for i in range(B):
                if np.linalg.norm(sync[:, i]) > 1e-6:
                    emis[i] = _PEN_A @ unit[:, i]
            beat_label = list(_viterbi_chords(emis, _CHORD_P_STAY))

        seg_bounds = list(beat_times)
        if len(seg_bounds) < B + 1:
            seg_bounds = seg_bounds + [duration]
        spans: list[ChordSpan] = []
        i = 0
        while i < B:
            j = i
            while j + 1 < B and beat_label[j + 1] == beat_label[i]:
                j += 1
            root, q = _PEN_LABELS[int(beat_label[i])]
            start = seg_bounds[i] if i < len(seg_bounds) else (i * 0.5)
            end = seg_bounds[j + 1] if j + 1 < len(seg_bounds) else duration
            spans.append(ChordSpan(float(start), float(end), _chord_label(root, q)))
            i = j + 1
        if not spans:
            spans = [ChordSpan(0.0, duration, "C")]
        return spans

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


def get_backend(name: str = "librosa") -> MirBackend:
    """MIR 백엔드 팩토리 (§2: 교체 가능 인터페이스).

    향후 'madmom' / 'external_api' 등을 추가할 수 있다.
    """
    if name == "librosa":
        return LibrosaBackend()
    raise ValueError(f"알 수 없는 MIR 백엔드: {name}")
