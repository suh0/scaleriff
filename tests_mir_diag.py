"""코드 인식 내부 구조 진단 — beat-sync 크로마 캐시 후 루프/세그먼트/템플릿 관찰.

사용: python tests_mir_diag.py <youtube_url> [cache_tag]
"""
import os, sys
os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from ingest.audio_source import resolve_audio
from ingest import mir_extract as M

PCS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=opbMk58n6sA"
TAG = sys.argv[2] if len(sys.argv) > 2 else "diag"
CACHE = os.path.join("cache", f"{TAG}.npz")


def build_cache():
    import librosa
    wav, _, _ = resolve_audio(URL)
    y, sr = librosa.load(wav, sr=None, mono=True)
    bt, db, bpb, bpm, src = M.track_beats_downbeats(wav, y, sr)
    cens = librosa.feature.chroma_cens(y=y, sr=sr)
    bf = np.clip(librosa.time_to_frames(bt, sr=sr), 0, cens.shape[1] - 1)
    sync = librosa.util.sync(cens, bf, aggregate=np.median)
    np.savez(CACHE, sync=sync, bpm=bpm, bpb=bpb, nbeats=len(bt))
    print(f"cached: sync{sync.shape} bpm={bpm:.0f} bpb={bpb} beats={len(bt)}")


def top_chords(vec, k=4):
    nv = np.linalg.norm(vec)
    if nv < 1e-6:
        return []
    sc = M._PEN_A @ (vec / nv)
    idx = np.argsort(sc)[::-1][:k]
    return [(f"{PCS[M._PEN_LABELS[i][0]]}{M._PEN_LABELS[i][1]}", round(float(sc[i]), 3))
            for i in idx]


def main():
    if not os.path.exists(CACHE):
        build_cache()
    d = np.load(CACHE)
    sync, bpm, bpb = d["sync"], int(d["bpm"]), int(d["bpb"])
    B = sync.shape[1]
    unit = sync / (np.linalg.norm(sync, axis=0) + 1e-9)
    L = M._detect_loop_beats(unit, bpb)
    print(f"B={B} beats, bpb={bpb}, loop L={L} ({L//bpb if L else 0} bars/loop)")

    # 전 구간 평균 크로마(키/전체 경향)
    glob = sync.sum(1); glob /= glob.sum() + 1e-9
    print("global chroma:", " ".join(f"{PCS[p]}:{glob[p]:.2f}"
                                     for p in np.argsort(glob)[::-1][:6]))

    if L:
        phase = np.zeros((12, L))
        for i in range(B):
            phase[:, i % L] += sync[:, i]
        nbars = L // bpb
        best = None
        for s in range(L):
            conf = 0.0
            for b in range(nbars):
                v = sum(phase[:, (s + b * bpb + kk) % L] for kk in range(bpb))
                nv = np.linalg.norm(v)
                conf += float(np.max(M._PEN_A @ (v / nv))) if nv > 1e-6 else 0
            if best is None or conf > best[0]:
                best = (conf, s)
        s = best[1]
        print(f"best bar-phase s={s}\n--- loop-averaged bars ---")
        for b in range(nbars):
            v = sum(phase[:, (s + b * bpb + kk) % L] for kk in range(bpb))
            vn = v / (v.sum() + 1e-9)
            cstr = " ".join(f"{PCS[p]}:{vn[p]:.2f}" for p in np.argsort(vn)[::-1][:6])
            print(f"bar{b+1}: [{cstr}]\n       cands {top_chords(v)}")
    else:
        print("NO LOOP — viterbi 경로. 마디별(첫 12마디) 후보:")
        for b in range(12):
            i0 = b * bpb
            if i0 + bpb > B:
                break
            v = sync[:, i0:i0 + bpb].sum(1)
            vn = v / (v.sum() + 1e-9)
            cstr = " ".join(f"{PCS[p]}:{vn[p]:.2f}" for p in np.argsort(vn)[::-1][:5])
            print(f"bar{b+1}: [{cstr}]  cands {top_chords(v)}")


if __name__ == "__main__":
    main()
