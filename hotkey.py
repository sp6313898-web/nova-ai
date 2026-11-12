import ctypes
import threading
from ctypes import wintypes

MODS = {"alt": 1, "ctrl": 2, "shift": 4, "win": 8}


class Hotkey:
    def __init__(self):
        self.tid = 0
        self.th = None

    def start(self, spec, cb):
        self.stop()
        parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
        mods, vk = 0, 0
        for p in parts:
            if p in MODS:
                mods |= MODS[p]
            elif p == "space":
                vk = 0x20
            elif p.startswith("f") and p[1:].isdigit():
                vk = 0x6F + int(p[1:])
            elif len(p) == 1:
                vk = ord(p.upper())
        if not vk:
            return False

        def loop():
            u, k = ctypes.windll.user32, ctypes.windll.kernel32
            self.tid = k.GetCurrentThreadId()
            if not u.RegisterHotKey(None, 1, mods | 0x4000, vk):
                return
            msg = wintypes.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x312:
                    cb()
            u.UnregisterHotKey(None, 1)
        self.th = threading.Thread(target=loop, daemon=True)
        self.th.start()
        return True

    def stop(self):
        if self.tid:
            try:
                ctypes.windll.user32.PostThreadMessageW(self.tid, 0x12, 0, 0)
            except Exception:
                pass
        self.tid = 0
