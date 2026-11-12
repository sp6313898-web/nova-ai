import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox

APP = "Nova"
EXE = "NovaAgent.exe"
SETUP = "NovaAgentSetup.exe"
REG = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\NovaAgent"
BG, PANEL, LINE, FG, DIM, HOT = "#000000", "#0a0a0a", "#1d1d1d", "#e8e8e8", "#707070", "#ffffff"
FONT = ("Segoe UI", 10)
NOWIN = 0x08000000


def ps(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                       capture_output=True, text=True, creationflags=NOWIN)
    return r.stdout.strip()


def desktop_dir():
    d = ps("[Environment]::GetFolderPath('Desktop')")
    return d or os.path.join(os.path.expanduser("~"), "Desktop")


def start_menu_dir():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")


def shortcut(lnk, target, workdir):
    q = lambda s: s.replace("'", "''")
    ps("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';"
       "$s.WorkingDirectory='%s';$s.IconLocation='%s,0';$s.Save()" % (q(lnk), q(target), q(workdir), q(target)))


def payload():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "payload", EXE)


def asset(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    c = [int(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * t) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(c)


def fade_in(win, dur=0.4):
    try:
        win.attributes("-alpha", 0.0)
    except Exception:
        return
    t0 = time.perf_counter()

    def step():
        p = min(1.0, (time.perf_counter() - t0) / dur)
        try:
            win.attributes("-alpha", 1 - (1 - p) ** 3)
        except Exception:
            return
        if p < 1:
            win.after(16, step)
    step()


def button(p, text, cmd):
    b = tk.Label(p, text=text, bg=BG, fg=DIM, font=FONT, padx=18, pady=7, cursor="hand2",
                 highlightthickness=1, highlightbackground=LINE)
    st = {"h": 0.0, "t": 0.0}

    def anim():
        if st["h"] != st["t"]:
            d = 0.08
            st["h"] = min(st["t"], st["h"] + d) if st["t"] > st["h"] else max(st["t"], st["h"] - d)
            try:
                b.config(fg=mix(DIM, HOT, st["h"]), highlightbackground=mix(LINE, DIM, st["h"]))
            except tk.TclError:
                return
            b.after(16, anim)

    def go(v):
        st["t"] = v
        anim()
    b.bind("<Enter>", lambda e: go(1.0))
    b.bind("<Leave>", lambda e: go(0.0))
    b.bind("<Button-1>", lambda e: cmd())
    return b


def check(p, text, var):
    return tk.Checkbutton(p, text=text, variable=var, bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
                          activeforeground=HOT, font=FONT, bd=0, highlightthickness=0, anchor="w")


def uninstall():
    root = tk.Tk()
    root.withdraw()
    if not messagebox.askyesno("Nova", "Удалить Nova с этого компьютера?\nНастройки в APPDATA останутся."):
        return
    here = os.path.dirname(os.path.abspath(sys.executable))
    for lnk in (os.path.join(desktop_dir(), APP + ".lnk"), os.path.join(start_menu_dir(), APP + ".lnk")):
        try:
            os.remove(lnk)
        except Exception:
            pass
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG)
    except Exception:
        pass
    subprocess.Popen('cmd /c ping 127.0.0.1 -n 3 >nul & rmdir /s /q "%s"' % here, shell=True,
                     creationflags=NOWIN)
    messagebox.showinfo("Nova", "Nova удалена.")


class Installer:
    def __init__(self):
        r = self.root = tk.Tk()
        r.title("Установка Nova")
        r.configure(bg=BG)
        r.geometry("560x400")
        r.resizable(False, False)
        try:
            r.iconbitmap(default=asset("assets/icon.ico"))
        except Exception:
            pass
        fade_in(r)
        tk.Label(r, text="N O V A", bg=BG, fg=HOT, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=28,
                                                                                         pady=(26, 2))
        tk.Label(r, text="Голосовой ИИ-агент. Установка", bg=BG, fg=DIM, font=FONT).pack(anchor="w", padx=28)
        tk.Frame(r, bg=LINE, height=1).pack(fill="x", padx=28, pady=16)
        tk.Label(r, text="Папка установки", bg=BG, fg=DIM, font=FONT).pack(anchor="w", padx=28)
        row = tk.Frame(r, bg=BG)
        row.pack(fill="x", padx=28, pady=(4, 14))
        self.path = tk.StringVar(value=os.path.join(os.environ.get("LOCALAPPDATA", "C:\\"), "Programs",
                                                    "NovaAgent"))
        tk.Entry(row, textvariable=self.path, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT,
                 highlightthickness=1, highlightbackground=LINE, highlightcolor=DIM).pack(
            side="left", fill="x", expand=True, ipady=5)
        button(row, "Обзор", self.browse).pack(side="left", padx=(8, 0))
        self.v_desk = tk.BooleanVar(value=True)
        self.v_menu = tk.BooleanVar(value=True)
        self.v_run = tk.BooleanVar(value=True)
        for t, v in (("Добавить ярлык на рабочий стол", self.v_desk), ("Добавить в меню Пуск", self.v_menu),
                     ("Запустить после установки", self.v_run)):
            check(r, t, v).pack(anchor="w", padx=28, pady=2)
        self.status = tk.Label(r, text="", bg=BG, fg=DIM, font=FONT)
        self.status.pack(anchor="w", padx=28, pady=(14, 6))
        self.bar = tk.Canvas(r, bg=PANEL, height=3, highlightthickness=0, bd=0)
        self.bar.pack(fill="x", padx=28)
        self.fill = self.bar.create_rectangle(0, 0, 0, 3, fill=HOT, outline="")
        self.prog = 0.0
        self.btn = button(r, "Установить", self.install)
        self.btn.pack(anchor="e", padx=28, pady=10)

    def browse(self):
        p = filedialog.askdirectory()
        if p:
            self.path.set(os.path.join(p, "NovaAgent"))

    def say(self, t, p=None):
        self.status.config(text=t)
        if p is not None:
            w = max(1, self.bar.winfo_width())
            start = self.prog
            for i in range(1, 13):
                v = start + (p - start) * (1 - (1 - i / 12.0) ** 3)
                self.bar.coords(self.fill, 0, 0, w * v, 3)
                self.root.update()
                time.sleep(0.012)
            self.prog = p
        self.root.update_idletasks()

    def install(self):
        dest = self.path.get().strip()
        try:
            self.say("Копирование файлов", 0.15)
            os.makedirs(dest, exist_ok=True)
            exe = os.path.join(dest, EXE)
            shutil.copyfile(payload(), exe)
            self.say("Копирование файлов", 0.6)
            setup = os.path.join(dest, SETUP)
            if getattr(sys, "frozen", False):
                shutil.copyfile(sys.executable, setup)
            if self.v_desk.get():
                self.say("Ярлык на рабочем столе", 0.8)
                shortcut(os.path.join(desktop_dir(), APP + ".lnk"), exe, dest)
            if self.v_menu.get():
                os.makedirs(start_menu_dir(), exist_ok=True)
                shortcut(os.path.join(start_menu_dir(), APP + ".lnk"), exe, dest)
            try:
                import winreg
                k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG)
                for n, v in (("DisplayName", "Nova"), ("DisplayVersion", "1.0"), ("InstallLocation", dest),
                             ("DisplayIcon", exe), ("UninstallString", '"%s" --uninstall' % setup)):
                    winreg.SetValueEx(k, n, 0, winreg.REG_SZ, v)
                winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(k)
            except Exception:
                pass
            self.say("Готово", 1.0)
            if self.v_run.get():
                subprocess.Popen([exe], cwd=dest)
            self.root.after(900, self.root.destroy)
        except Exception as e:
            self.say("Ошибка: %s" % e)


if __name__ == "__main__":
    if any(a in ("--uninstall", "/uninstall") for a in sys.argv[1:]):
        uninstall()
    else:
        Installer().root.mainloop()
