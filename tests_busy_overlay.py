"""run_busy 비동기 경로: 계산 중 오버레이가 입력을 막고, 끝나면 done 후 사라진다."""
import time
import unittest

from PyQt6.QtWidgets import QApplication, QWidget

from gui.widgets import busy_overlay as B

app = QApplication.instance() or QApplication([])


class BusyOverlayTest(unittest.TestCase):
    def test_async_overlay_then_done(self):
        B._sync, orig = (lambda: False), B._sync
        try:
            win = QWidget()
            win.resize(400, 300)
            win.show()
            got = []
            B.run_busy(win, lambda: (time.sleep(0.4), 7)[1], got.append)
            end = time.monotonic() + 0.25
            while time.monotonic() < end:
                app.processEvents()
            overlays = win.findChildren(B.BusyOverlay)
            self.assertEqual(len(overlays), 1)
            self.assertIsNotNone(overlays[0]._bg)       # 120ms 뒤 흐린 배경 표시
            self.assertEqual(got, [])
            end = time.monotonic() + 2
            while not got and time.monotonic() < end:
                app.processEvents()
            self.assertEqual(got, [7])
            self.assertFalse(overlays[0].isVisible())
        finally:
            B._sync = orig


if __name__ == "__main__":
    unittest.main()
