import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from player.dummy_timeline import build_dummy_timeline
from player.timeline import Timeline


class SessionStorageTest(unittest.TestCase):
    def test_invalid_root_and_duplicate_grid_are_rejected(self):
        for payload in (None, [], "session"):
            with self.assertRaises(ValueError):
                Timeline.from_dict(payload)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder, "invalid.json")
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    Timeline.load_json(str(path))
        payload = build_dummy_timeline().to_dict()
        payload["bar_times"] = [0, 0, 2]
        with self.assertRaises(ValueError):
            Timeline.from_dict(payload)

    def test_failed_replace_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "session.json")
            tl = build_dummy_timeline()
            tl.save_json(str(path))
            previous = path.read_bytes()
            tl.title = "수정"
            with patch("os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    tl.save_json(str(path))
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["session.json"])

    def test_metadata_and_legacy_load(self):
        tl = build_dummy_timeline()
        self.assertEqual(tl.to_dict().get("schema_version"), 2)
        old = tl.to_dict()
        old.pop("schema_version")
        self.assertEqual(Timeline.from_dict(old).key, tl.key)
        old["schema_version"] = 999
        with self.assertRaises(ValueError):
            Timeline.from_dict(old)

    def test_relocated_media_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio.wav"
            audio.write_bytes(b"audio")
            tl = build_dummy_timeline()
            tl.audio_ref = str(audio)
            path = root / "session.json"
            tl.save_json(str(path))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["audio_ref"] = "Z:/removed/original.wav"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(Timeline.load_json(str(path)).audio_ref, str(audio))


if __name__ == "__main__":
    unittest.main()
