import ctypes
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes

VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "enter": 0x0D, "tab": 0x09, "esc": 0x1B,
      "space": 0x20, "backspace": 0x08, "delete": 0x2E, "up": 0x26, "down": 0x28, "left": 0x25,
      "right": 0x27, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22}
for _i in range(1, 13):
    VK["f%d" % _i] = 0x6F + _i


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _IU(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("i", _IU)]


def _send(vk=0, scan=0, flags=0):
    inp = INPUT(1, _IU(ki=KEYBDINPUT(vk, scan, flags, 0, None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def type_text(text):
    for ch in text:
        if ch == "\n":
            _send(0x0D)
            _send(0x0D, 0, 2)
        else:
            _send(0, ord(ch), 4)
            _send(0, ord(ch), 4 | 2)
        time.sleep(0.004)


def press(combo):
    keys = []
    for p in combo.lower().replace(" ", "").split("+"):
        if p in VK:
            keys.append(VK[p])
        elif len(p) == 1:
            keys.append(ord(p.upper()))
        else:
            return False
    u = ctypes.windll.user32
    for k in keys:
        u.keybd_event(k, 0, 0, 0)
    for k in reversed(keys):
        u.keybd_event(k, 0, 2, 0)
    return True


def click(x, y, right=False, double=False):
    u = ctypes.windll.user32
    u.SetCursorPos(int(x), int(y))
    d, up = (0x8, 0x10) if right else (0x2, 0x4)
    for _ in range(2 if double else 1):
        u.mouse_event(d, 0, 0, 0, 0)
        u.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.05)


def scroll(n):
    ctypes.windll.user32.mouse_event(0x800, 0, 0, int(n) * 120, 0)


def screen_size():
    u = ctypes.windll.user32
    return u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def clip_get():
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetClipboardData.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not u.OpenClipboard(0):
        return ""
    try:
        h = u.GetClipboardData(13)
        if not h:
            return ""
        p = k.GlobalLock(h)
        s = ctypes.wstring_at(p) if p else ""
        k.GlobalUnlock(h)
        return s
    finally:
        u.CloseClipboard()


def clip_set(text):
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    data = (text + "\0").encode("utf-16-le")
    h = k.GlobalAlloc(0x42, len(data))
    p = k.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k.GlobalUnlock(h)
    if u.OpenClipboard(0):
        u.EmptyClipboard()
        u.SetClipboardData(13, h)
        u.CloseClipboard()


def copy_selection():
    old = clip_get()
    clip_set("")
    press("ctrl+c")
    time.sleep(0.2)
    got = clip_get()
    if not got and old:
        clip_set(old)
    return got


def set_volume(pct):
    pct = max(0, min(100, int(pct)))
    u = ctypes.windll.user32
    for _ in range(50):
        u.keybd_event(0xAE, 0, 0, 0)
        u.keybd_event(0xAE, 0, 2, 0)
    for _ in range(pct // 2):
        u.keybd_event(0xAF, 0, 0, 0)
        u.keybd_event(0xAF, 0, 2, 0)


def screenshot_save():
    from PIL import ImageGrab
    d = os.path.join(os.path.expanduser("~"), "Pictures")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "Nova_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
    ImageGrab.grab().save(p)
    return p


# ---------- files ----------
def find_files(query, limit=5, secs=4.0):
    words = [w for w in query.lower().split() if w]
    home = os.path.expanduser("~")
    out, t0 = [], time.time()
    for d in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
        root = os.path.join(home, d)
        for dp, dn, fn in os.walk(root):
            if dp[len(root):].count(os.sep) >= 3:
                dn[:] = []
            for f in fn:
                low = f.lower()
                if all(w in low for w in words):
                    out.append(os.path.join(dp, f))
                    if len(out) >= limit:
                        return out
            if time.time() - t0 > secs:
                return out
    return out


def read_file_text(path, limit=8000):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(path)
        text = "\n".join((pg.extract_text() or "") for pg in r.pages[:15])
    elif ext == ".docx":
        import zipfile
        with zipfile.ZipFile(path) as z:
            x = z.read("word/document.xml").decode("utf-8", "ignore")
        text = re.sub(r"<[^>]+>", "", x.replace("</w:p>", "\n"))
    else:
        with open(path, "rb") as f:
            text = f.read(200000).decode("utf-8", "ignore")
    return text[:limit]


# ---------- system ----------
PROTECTED = {"system", "system idle process", "registry", "explorer.exe", "svchost.exe", "csrss.exe",
             "winlogon.exe", "dwm.exe", "lsass.exe", "services.exe", "smss.exe", "wininit.exe",
             "novaagent.exe", "python.exe", "pythonw.exe", "msmpeng.exe", "memcompression", "fontdrvhost.exe",
             "searchhost.exe", "sihost.exe", "taskhostw.exe", "ctfmon.exe", "audiodg.exe"}


def _procs():
    import psutil
    ps = list(psutil.process_iter(["name", "pid"]))
    for p in ps:
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(0.7)
    rows = []
    for p in ps:
        try:
            rows.append((p.cpu_percent(None) / max(1, os.cpu_count() or 1), p.memory_info().rss / 1048576.0,
                         (p.info["name"] or "?"), p))
        except Exception:
            continue
    return rows


def top_procs():
    rows = sorted(_procs(), key=lambda r: r[0] + r[1] / 400.0, reverse=True)[:3]
    return "Больше всего грузят: " + ", ".join(
        "%s %d процентов процессора, %d мегабайт" % (n.replace(".exe", ""), c, m) for c, m, n, _ in rows)


def kill_heavy():
    import psutil
    me = os.getpid()
    killed = []
    for c, m, n, p in _procs():
        if n.lower() in PROTECTED or p.pid == me or (c < 15 and m < 800):
            continue
        try:
            p.terminate()
            killed.append(n.replace(".exe", ""))
        except Exception:
            pass
    return ("Закрыл: " + ", ".join(killed)) if killed else "Тяжёлых программ не нашёл"


def sysinfo():
    import psutil
    cpu = psutil.cpu_percent(interval=0.6)
    ram = psutil.virtual_memory().percent
    s = "Процессор загружен на %d процентов, память на %d" % (cpu, ram)
    b = psutil.sensors_battery()
    if b:
        s += ", заряд %d процентов%s" % (b.percent, ", на зарядке" if b.power_plugged else "")
    return s


def battery():
    import psutil
    b = psutil.sensors_battery()
    if not b:
        return "Батареи нет, компьютер работает от сети"
    return "Заряд %d процентов%s" % (b.percent, ", на зарядке" if b.power_plugged else "")


def temperature():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZone | "
                            "Select-Object -First 1).CurrentTemperature"],
                           capture_output=True, text=True, timeout=8, creationflags=0x08000000)
        v = float(r.stdout.strip())
        return "Температура процессора около %d градусов" % round(v / 10.0 - 273.15)
    except Exception:
        return "Датчик температуры недоступен на этом компьютере"


def shutdown(restart=False):
    subprocess.Popen(["shutdown", "/r" if restart else "/s", "/t", "30"], creationflags=0x08000000)
    return "Через 30 секунд. Скажите отмени выключение, чтобы остановить"


def shutdown_cancel():
    subprocess.Popen(["shutdown", "/a"], creationflags=0x08000000)
    return "Отменено"


def set_autostart(on):
    import winreg
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                       winreg.KEY_SET_VALUE)
    try:
        if on:
            if getattr(sys, "frozen", False):
                cmd = '"%s" --tray' % sys.executable
            else:
                cmd = '"%s" "%s" --tray' % (sys.executable.replace("python.exe", "pythonw.exe"),
                                           os.path.abspath(sys.argv[0]))
            winreg.SetValueEx(k, "NovaAgent", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, "NovaAgent")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(k)


# ---------- windows: wait / focus ----------
def _proc_name(pid):
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = wintypes.DWORD(520)
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        k.CloseHandle(h)


def find_window(titles=(), procs=()):
    """Returns hwnd of a visible top-level window whose title contains one of `titles`
    (and/or whose process is one of `procs`), or 0."""
    u = ctypes.windll.user32
    found = []
    titles = [t.lower() for t in titles]
    procs = [p.lower() for p in procs]
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.lower()
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pn = _proc_name(pid.value) if procs else ""
        by_proc = bool(procs) and pn in procs
        by_title = bool(titles) and any(t in title for t in titles)
        # when process names are known, require them: this skips browser tabs called "Telegram Web"
        if (procs and by_proc) or (not procs and by_title):
            found.append(hwnd)
            return False
        return True
    u.EnumWindows(EnumProc(cb), 0)
    return found[0] if found else 0


def focus_window(hwnd):
    u = ctypes.windll.user32
    if not hwnd:
        return False
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Windows blocks SetForegroundWindow from background processes; a tap on Alt lifts the lock
    u.keybd_event(0x12, 0, 0, 0)
    u.keybd_event(0x12, 0, 2, 0)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    return u.GetForegroundWindow() == hwnd


def wait_window(titles=(), procs=(), timeout=10.0, focus=True):
    """Waits until the window exists, then brings it to the front. Returns True if it is in front."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = find_window(titles, procs)
        if h:
            if not focus:
                return True
            if focus_window(h):
                time.sleep(0.4)
                return True
        time.sleep(0.3)
    return False


def process_running(*names):
    try:
        import psutil
        want = {n.lower() for n in names}
        return any((p.info["name"] or "").lower() in want for p in psutil.process_iter(["name"]))
    except Exception:
        return False
