import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf
from ingest.mir_extract import MirBackend


class MirFlagsTest(unittest.TestCase):
    def test_imputed_beats_are_not_reported_as_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            sr = 22050
            path = Path(folder, "tone.wav")
            sf.write(path, .1 * np.sin(2 * np.pi * 220 * np.arange(4 * sr) / sr), sr)
            with patch("ingest.mir_extract.track_beats_downbeats", return_value=([], [], 4, 100, "librosa")):
                result = MirBackend(use_madmom=False).analyze(str(path))
            self.assertFalse(getattr(result, "beat_detected", True), "기본 격자를 검출된 비트로 표시함")
            self.assertGreater(len(result.beat_times), 2)


if __name__ == "__main__":
    unittest.main()
